"""
Run bulk eval on all imported skills for a given intent.

For each scenario × each pair of skills, run the LLM executor on both
(using cached SKILL.md content) and call the pairwise judge. Update
Bradley-Terry ratings after each comparison.

Usage:
    SKILLRANK_DB=./skillrank.db OPENROUTER_API_KEY=sk-... \\
        python -m scripts.bulk_eval --intent react_component_design
"""

import argparse
import asyncio
import json
import sys
import uuid
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from api.database import (  # noqa: E402
    init_db, get_db, get_skills_by_intent, get_scenarios_by_intent,
    update_skill_rating, create_comparison, create_scenario,
)
from eval.bradley_terry import Rating, update_ratings  # noqa: E402
from eval.sandbox import run_skill_from_cache  # noqa: E402
from judges.pairwise import judge_comparison  # noqa: E402


async def seed_scenarios_from_disk(db, scenarios_dir: Path):
    """Idempotently seed scenarios from JSON files on disk."""
    count = 0
    for fname in sorted(scenarios_dir.glob("*.json")):
        with open(fname) as f:
            scenario = json.load(f)
        await create_scenario(db, scenario)
        count += 1
    print(f"Seeded {count} scenario files from {scenarios_dir}")


async def run_bulk_eval(intent: str):
    """Full round-robin eval for all skills in an intent."""
    await init_db()
    db = await get_db()
    try:
        # Seed scenarios from disk (idempotent)
        await seed_scenarios_from_disk(db, PROJECT_ROOT / "scenarios")

        skills = await get_skills_by_intent(db, intent)
        scenarios = await get_scenarios_by_intent(db, intent)

        print(f"Intent: {intent}")
        print(f"Skills: {len(skills)}")
        print(f"Scenarios: {len(scenarios)}")
        if len(skills) < 2 or len(scenarios) < 1:
            print("Not enough skills or scenarios to run eval.")
            return

        if not all(s.get("skill_md_content") for s in skills):
            missing = [s["id"] for s in skills if not s.get("skill_md_content")]
            print(f"Missing cached SKILL.md for: {missing}")
            return

        # Phase 1: executor — for each skill × each scenario, run the LLM once
        print("\nPhase 1: LLM executor")
        print("-" * 70)
        outputs = {}  # outputs[(skill_id, scenario_id)] = str
        for sc in scenarios:
            print(f"\nScenario: {sc['name']}")
            for sk in skills:
                print(f"  {sk['id']:<60}", end=" ", flush=True)
                try:
                    result = await run_skill_from_cache(
                        sk["skill_md_content"], sc["task"]
                    )
                    if result["status"] == "success":
                        outputs[(sk["id"], sc["id"])] = result["output"]
                        print(f"OK ({len(result['output'])} chars)")
                    else:
                        outputs[(sk["id"], sc["id"])] = ""
                        print(f"FAIL: {result['stderr'][:80]}")
                except Exception as e:
                    outputs[(sk["id"], sc["id"])] = ""
                    print(f"EXC: {e}")

        # Phase 2: pairwise judge for each pair × each scenario
        print("\n\nPhase 2: Pairwise judge")
        print("-" * 70)

        # Initialize rating objects from DB
        ratings = {
            s["id"]: Rating(
                value=s.get("rating", 1.0),
                variance=s.get("rating_variance", 1.0),
                wins=s.get("wins", 0),
                losses=s.get("losses", 0),
                ties=s.get("ties", 0),
            )
            for s in skills
        }

        n = len(skills)
        total_pairs = n * (n - 1) // 2
        done = 0
        for sc in scenarios:
            print(f"\nScenario: {sc['name']}")
            for i in range(n):
                for j in range(i + 1, n):
                    a = skills[i]
                    b = skills[j]
                    oa = outputs.get((a["id"], sc["id"]), "")
                    ob = outputs.get((b["id"], sc["id"]), "")

                    if not oa or not ob:
                        print(f"  SKIP (missing output): {a['id']} vs {b['id']}")
                        continue

                    done += 1
                    print(f"  [{done}/{total_pairs * len(scenarios)}] "
                          f"{a['id'].split('/')[-1]:<30} vs "
                          f"{b['id'].split('/')[-1]:<30}", end=" ", flush=True)

                    scenario_desc = sc.get("description", "")
                    expected = sc.get("expected_outcomes", "")
                    if isinstance(expected, str):
                        try:
                            expected = json.loads(expected)
                        except Exception:
                            expected = []
                    exp_text = "\n".join(f"- {o}" for o in expected) if expected else ""
                    full_scenario = f"{scenario_desc}\n\nExpected:\n{exp_text}"

                    comp = await judge_comparison(
                        intent_desc=f"{intent}: {sc.get('task', '')[:300]}",
                        scenario_desc=full_scenario,
                        output_a=oa,
                        output_b=ob,
                    )
                    verdict = comp["verdict"]
                    print(f"-> {verdict}")

                    # Record comparison
                    comp_id = uuid.uuid4().hex[:16]
                    winner_id = None
                    if verdict == "A":
                        winner_id = a["id"]
                    elif verdict == "B":
                        winner_id = b["id"]
                    await create_comparison(
                        db, comp_id, intent, sc["id"],
                        a["id"], b["id"], winner_id,
                        comp.get("runs", []), verdict,
                    )

                    # Update BT ratings
                    if verdict == "A":
                        ratings[a["id"]], ratings[b["id"]] = update_ratings(
                            ratings[a["id"]], ratings[b["id"]]
                        )
                    elif verdict == "B":
                        ratings[b["id"]], ratings[a["id"]] = update_ratings(
                            ratings[b["id"]], ratings[a["id"]]
                        )
                    elif verdict == "TIE":
                        ratings[a["id"]], ratings[b["id"]] = update_ratings(
                            ratings[a["id"]], ratings[b["id"]], is_tie=True
                        )

                    # Persist
                    for sk in (a, b):
                        r = ratings[sk["id"]]
                        await update_skill_rating(
                            db, sk["id"], r.value, r.variance,
                            r.wins, r.losses, r.ties, r.comparisons,
                        )

        # Final ranking
        print("\n\nFINAL RANKING")
        print("=" * 80)
        skills_sorted = sorted(
            skills, key=lambda s: -ratings[s["id"]].value
        )
        for rank, sk in enumerate(skills_sorted, 1):
            r = ratings[sk["id"]]
            print(f"  #{rank:<3} {sk['id']:<55} rating={r.value:.3f}  "
                  f"W:{r.wins}  L:{r.losses}  T:{r.ties}  "
                  f"win_rate={r.win_rate:.2f}")

    finally:
        await db.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--intent", default="react_component_design")
    args = parser.parse_args()
    asyncio.run(run_bulk_eval(args.intent))


if __name__ == "__main__":
    main()
