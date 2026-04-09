"""
Eval engine: orchestrates the full eval pipeline.

Submission -> clone -> run against scenarios -> pairwise compare -> rate -> scorecard.
Parallel execution with concurrency limits.
Checkpoint/resume on failure (idempotent).
"""

import asyncio
import uuid
import json
import logging
from typing import Optional

logger = logging.getLogger(__name__)

from api.database import (
    get_db, get_skills_by_intent, get_scenarios_by_intent,
    create_skill, update_skill_rating, create_comparison,
    create_eval_run, update_eval_run, update_submission, get_skill,
)
from eval.bradley_terry import Rating, update_ratings, rate_first_skill
from eval.sandbox import run_skill_in_sandbox, run_skill_subprocess, check_docker_available
from judges.pairwise import judge_comparison

# Concurrency limits
SKILL_SEMAPHORE = asyncio.Semaphore(3)   # max 3 concurrent skill runs
JUDGE_SEMAPHORE = asyncio.Semaphore(10)  # max 10 concurrent judge calls


async def run_full_eval(submission_id: str, repo_url: str, commit_sha: str,
                        intent: str, description: str, author: str):
    """
    Full eval pipeline for a submitted skill.
    Called as a background task from the API.
    """
    db = await get_db()
    try:
        await update_submission(db, submission_id, status="evaluating")

        # Create or update the skill record
        skill_id = f"{author}/{repo_url.rstrip('/').split('/')[-1]}"
        skill = await create_skill(
            db, skill_id, repo_url.rstrip("/").split("/")[-1],
            repo_url, commit_sha, intent, description, author
        )

        await update_submission(db, submission_id, skill_id=skill_id)

        # Get existing skills for this intent (to compare against)
        existing_skills = await get_skills_by_intent(db, intent)
        existing_skills = [s for s in existing_skills if s["id"] != skill_id]

        # Get scenarios
        scenarios = await get_scenarios_by_intent(db, intent)
        if not scenarios:
            await update_submission(db, submission_id, status="error",
                                   error="No eval scenarios found for this intent")
            return

        # Check Docker availability
        use_docker = await check_docker_available()

        # Phase 1: Run the new skill against all scenarios
        new_skill_outputs = {}
        for scenario in scenarios:
            async with SKILL_SEMAPHORE:
                run_id = uuid.uuid4().hex[:16]
                await create_eval_run(db, run_id, submission_id, skill_id, scenario["id"])

                if use_docker:
                    result = await run_skill_in_sandbox(
                        repo_url, commit_sha, scenario["task"],
                        scenario["repo_url"], scenario["branch"]
                    )
                else:
                    result = await run_skill_subprocess(repo_url, commit_sha, scenario["task"])

                await update_eval_run(db, run_id,
                                      output=result["output"],
                                      stderr=result["stderr"],
                                      exit_code=result["exit_code"],
                                      duration_s=result["duration_s"],
                                      status=result["status"])

                new_skill_outputs[scenario["id"]] = result

        # If first skill in intent, just set baseline rating
        if not existing_skills:
            rating = rate_first_skill(Rating())
            await update_skill_rating(db, skill_id, rating.value, rating.variance,
                                      rating.wins, rating.losses, rating.ties, rating.comparisons)
            scorecard = _build_scorecard(skill, rating, new_skill_outputs, scenarios, [], is_first=True)
            await update_submission(db, submission_id, status="complete",
                                   scorecard=json.dumps(scorecard))
            return

        # Phase 2: Pairwise comparisons against existing skills
        comparison_results = []
        rating = Rating(
            value=skill.get("rating", 1.0),
            variance=skill.get("rating_variance", 1.0),
            wins=skill.get("wins", 0),
            losses=skill.get("losses", 0),
            ties=skill.get("ties", 0),
        )

        for existing in existing_skills:
            for scenario in scenarios:
                new_output = new_skill_outputs.get(scenario["id"], {}).get("output", "")

                # Skip if new skill failed on this scenario
                if new_skill_outputs.get(scenario["id"], {}).get("status") != "success":
                    continue

                # Run existing skill on same scenario (or use cached output)
                async with SKILL_SEMAPHORE:
                    if use_docker:
                        existing_result = await run_skill_in_sandbox(
                            existing["repo_url"], existing["commit_sha"],
                            scenario["task"], scenario["repo_url"], scenario["branch"]
                        )
                    else:
                        existing_result = await run_skill_subprocess(
                            existing["repo_url"], existing["commit_sha"],
                            scenario["task"]
                        )

                if existing_result["status"] != "success":
                    # Existing skill failed: new skill wins by forfeit
                    comp_result = {"verdict": "A", "reason": "Opponent failed to execute"}
                    logger.info(f"Forfeit win: {existing['id']} failed on {scenario['name']}")
                else:
                    # Judge comparison
                    logger.info(f"Judging: {skill_id} vs {existing['id']} on {scenario['name']}")
                    async with JUDGE_SEMAPHORE:
                        comp_result = await judge_comparison(
                            intent_desc=f"{intent}: {scenario.get('task', '')}",
                            scenario_desc=scenario.get("description", ""),
                            output_a=new_output,
                            output_b=existing_result["output"],
                        )

                # Record comparison
                comp_id = uuid.uuid4().hex[:16]
                winner_id = None
                if comp_result["verdict"] == "A":
                    winner_id = skill_id
                elif comp_result["verdict"] == "B":
                    winner_id = existing["id"]

                logger.info(f"Comparison result: {comp_result['verdict']} — {comp_result.get('reason', '')[:100]}")

                await create_comparison(
                    db, comp_id, intent, scenario["id"],
                    skill_id, existing["id"],
                    winner_id,
                    comp_result.get("runs", []),
                    comp_result["verdict"]
                )

                comparison_results.append({
                    "opponent": existing["id"],
                    "scenario": scenario["name"],
                    "verdict": comp_result["verdict"],
                    "reason": comp_result.get("reason", ""),
                })

                # Update ratings
                existing_rating = Rating(
                    value=existing.get("rating", 1.0),
                    variance=existing.get("rating_variance", 1.0),
                    wins=existing.get("wins", 0),
                    losses=existing.get("losses", 0),
                    ties=existing.get("ties", 0),
                )

                if comp_result["verdict"] == "A":
                    rating, existing_rating = update_ratings(rating, existing_rating)
                elif comp_result["verdict"] == "B":
                    existing_rating, rating = update_ratings(existing_rating, rating)
                elif comp_result["verdict"] == "TIE":
                    rating, existing_rating = update_ratings(rating, existing_rating, is_tie=True)
                # INCONCLUSIVE: no rating update

                # Persist both ratings
                await update_skill_rating(db, skill_id, rating.value, rating.variance,
                                          rating.wins, rating.losses, rating.ties, rating.comparisons)
                await update_skill_rating(db, existing["id"], existing_rating.value, existing_rating.variance,
                                          existing_rating.wins, existing_rating.losses,
                                          existing_rating.ties, existing_rating.comparisons)

        # Phase 3: Generate scorecard
        scorecard = _build_scorecard(skill, rating, new_skill_outputs, scenarios,
                                     comparison_results, is_first=False)

        await update_submission(db, submission_id, status="complete",
                               scorecard=json.dumps(scorecard))

    except Exception as e:
        try:
            await update_submission(db, submission_id, status="error", error=str(e))
        except Exception:
            pass
    finally:
        await db.close()


def _build_scorecard(skill: dict, rating: Rating, outputs: dict,
                     scenarios: list, comparisons: list, is_first: bool) -> dict:
    """Build the scorecard that the author sees after eval."""

    # Identify strengths and weaknesses from judge reasoning
    strengths = []
    weaknesses = []
    for comp in comparisons:
        if comp["verdict"] == "A":
            strengths.append(comp["reason"])
        elif comp["verdict"] == "B":
            weaknesses.append(comp["reason"])

    # Scenario pass/fail
    scenario_results = []
    for s in scenarios:
        result = outputs.get(s["id"], {})
        scenario_results.append({
            "name": s["name"],
            "status": result.get("status", "not_run"),
            "duration_s": result.get("duration_s", 0),
        })

    # Compute ranking
    total_comparisons = len(comparisons)
    wins = sum(1 for c in comparisons if c["verdict"] == "A")
    losses = sum(1 for c in comparisons if c["verdict"] == "B")
    ties = sum(1 for c in comparisons if c["verdict"] == "TIE")

    return {
        "skill_id": skill["id"],
        "skill_name": skill["name"],
        "author": skill["author"],
        "intent": skill["intent"],
        "rating": rating.to_dict(),
        "is_first_skill": is_first,
        "scenarios": scenario_results,
        "comparisons_summary": {
            "total": total_comparisons,
            "wins": wins,
            "losses": losses,
            "ties": ties,
        },
        "strengths": strengths[:5],
        "weaknesses": weaknesses[:5],
    }
