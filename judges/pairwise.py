"""
LLM-as-judge for pairwise skill comparison.

Uses OpenRouter free tier models via OpenAI-compatible API.
Position bias mitigation: randomizes A/B presentation order per run.
3 runs per comparison, majority vote.
Retry logic for rate limits and malformed responses.
"""

import httpx
import random
import asyncio
import os
import json
import logging
from typing import Optional

logger = logging.getLogger(__name__)

OPENROUTER_BASE = "https://openrouter.ai/api/v1"
OPENROUTER_KEY = os.environ.get("OPENROUTER_API_KEY", "")
JUDGE_MODEL = os.environ.get("JUDGE_MODEL", "openrouter/auto")

MAX_RETRIES = 3
RETRY_DELAY = 2.0  # seconds


JUDGE_PROMPT = """You are evaluating two AI skill outputs for the task: "{intent_description}".

Scenario: {scenario_description}

--- OUTPUT FROM SKILL {label_first} ---
{output_first}

--- OUTPUT FROM SKILL {label_second} ---
{output_second}

Which output better accomplishes the task? Consider:
1. Completeness: did the skill do everything asked?
2. Correctness: are the results accurate?
3. Side effects: files created, commands run, errors encountered?
4. Efficiency: token cost, time taken, unnecessary steps?

Respond with EXACTLY one word: "{label_first}" or "{label_second}" or "TIE"
Then a pipe character |
Then a one-sentence reason.

Example: {label_first}|This output created the PR with passing tests while the other skipped tests entirely."""


async def call_judge(intent_desc: str, scenario_desc: str,
                     output_a: str, output_b: str,
                     swap_order: bool = False) -> dict:
    """
    Single judge call. Returns {"verdict": "A"|"B"|"TIE", "reason": str, "swapped": bool}.
    If swap_order=True, B is shown first to mitigate position bias.
    """
    if swap_order:
        label_first, label_second = "B", "A"
        first_output, second_output = output_b, output_a
    else:
        label_first, label_second = "A", "B"
        first_output, second_output = output_a, output_b

    prompt = JUDGE_PROMPT.format(
        intent_description=intent_desc,
        scenario_description=scenario_desc,
        label_first=label_first,
        label_second=label_second,
        output_first=first_output[:4000],  # truncate to avoid token overflow
        output_second=second_output[:4000],
    )

    logger.info(f"Judge call: model={JUDGE_MODEL}, swap={swap_order}, key_set={bool(OPENROUTER_KEY)}")

    for attempt in range(MAX_RETRIES):
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    f"{OPENROUTER_BASE}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {OPENROUTER_KEY}",
                        "HTTP-Referer": "https://skillrank.dev",
                        "X-Title": "SkillRank Judge",
                    },
                    json={
                        "model": JUDGE_MODEL,
                        "messages": [{"role": "user", "content": prompt}],
                        "max_tokens": 100,
                        "temperature": 0.1,
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                text = data["choices"][0]["message"]["content"].strip()
                logger.info(f"Judge response (attempt {attempt+1}): {text[:200]}")

                # Parse "A|reason" or "B|reason" or "TIE|reason"
                verdict, reason = _parse_verdict(text, label_first, label_second, swap_order)
                return {"verdict": verdict, "reason": reason, "swapped": swap_order, "raw": text}

        except (httpx.HTTPStatusError, httpx.TimeoutException, Exception) as e:
            logger.error(f"Judge error (attempt {attempt+1}/{MAX_RETRIES}): {type(e).__name__}: {e}")
            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(RETRY_DELAY * (attempt + 1))
            else:
                return {"verdict": "INCONCLUSIVE", "reason": f"Judge failed after {MAX_RETRIES} attempts: {str(e)}", "swapped": swap_order, "raw": ""}


def _parse_verdict(text: str, label_first: str, label_second: str, swapped: bool) -> tuple[str, str]:
    """Parse judge output into (canonical_verdict, reason).
    Canonical verdict is always in terms of original A/B (not swapped)."""
    text = text.strip()

    # Try pipe-separated format first
    if "|" in text:
        parts = text.split("|", 1)
        raw_verdict = parts[0].strip().upper()
        reason = parts[1].strip() if len(parts) > 1 else ""
    else:
        # Fallback: first word
        words = text.split()
        raw_verdict = words[0].strip().upper() if words else ""
        reason = " ".join(words[1:]) if len(words) > 1 else ""

    # Map to canonical A/B/TIE
    if raw_verdict == "TIE":
        return "TIE", reason
    elif raw_verdict == label_first.upper():
        # If swapped, label_first is "B" but means original B
        return ("B" if swapped else "A"), reason
    elif raw_verdict == label_second.upper():
        return ("A" if swapped else "B"), reason
    else:
        return "INCONCLUSIVE", f"Unparseable verdict: {text[:100]}"


async def judge_comparison(intent_desc: str, scenario_desc: str,
                           output_a: str, output_b: str,
                           num_runs: int = 3) -> dict:
    """
    Run multiple judge calls with position randomization.
    Returns majority vote verdict.

    Position bias mitigation:
    - Run 1: A shown first
    - Run 2: B shown first
    - Run 3: random
    """
    swap_orders = [False, True, random.choice([True, False])][:num_runs]

    # Run judge calls concurrently (paid models have no rate limit)
    tasks = [
        call_judge(intent_desc, scenario_desc, output_a, output_b, swap)
        for swap in swap_orders
    ]
    results = await asyncio.gather(*tasks)

    # Majority vote
    verdicts = [r["verdict"] for r in results]
    verdict_counts = {}
    for v in verdicts:
        if v != "INCONCLUSIVE":
            verdict_counts[v] = verdict_counts.get(v, 0) + 1

    if not verdict_counts:
        return {
            "verdict": "INCONCLUSIVE",
            "reason": "All judge runs were inconclusive",
            "runs": results,
            "confidence": 0,
        }

    winner = max(verdict_counts, key=verdict_counts.get)
    count = verdict_counts[winner]

    # Need majority (>50% of valid runs)
    valid_runs = sum(verdict_counts.values())
    if count <= valid_runs / 2:
        return {
            "verdict": "INCONCLUSIVE",
            "reason": f"No majority: {verdict_counts}",
            "runs": results,
            "confidence": 0,
        }

    return {
        "verdict": winner,
        "reason": next(r["reason"] for r in results if r["verdict"] == winner),
        "runs": results,
        "confidence": count / num_runs,
    }
