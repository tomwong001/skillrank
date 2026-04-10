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


JUDGE_PROMPT = """Compare two AI skill attempts at this task. Judge which attempt better accomplishes it.

TASK:
{task}

EXPECTED OUTCOMES:
{expected_outcomes}

--- ATTEMPT {label_first} ---
{output_first}

--- ATTEMPT {label_second} ---
{output_second}

Judge criteria:
1. Completeness: does it implement all requirements in the task?
2. Correctness: will the code/commands actually work? Uses real APIs, not invented ones?
3. Concreteness: working code vs hand-wavy "you would do X" commentary?
4. Expected outcome coverage: how many of the expected outcomes does it hit?

Reply with ONE line only in this exact format:
{label_first}|one-sentence reason
OR
{label_second}|one-sentence reason
OR
TIE|one-sentence reason

Do NOT prefix with "VERDICT|" — just the letter and reason. Example:
{label_first}|Uses shadcn Card primitives with cva variants while the other hardcodes Tailwind classes."""


async def call_judge(task: str, expected_outcomes: list,
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

    # Format expected outcomes as bullet list
    if isinstance(expected_outcomes, list):
        expected_text = "\n".join(f"- {o}" for o in expected_outcomes) if expected_outcomes else "(none specified)"
    else:
        expected_text = str(expected_outcomes) if expected_outcomes else "(none specified)"

    prompt = JUDGE_PROMPT.format(
        task=task,
        expected_outcomes=expected_text,
        label_first=label_first,
        label_second=label_second,
        output_first=first_output[:6000],  # truncate to avoid token overflow
        output_second=second_output[:6000],
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
    Canonical verdict is always in terms of original A/B (not swapped).

    Handles multiple formats:
      - "A|reason" (preferred)
      - "VERDICT|A\\nA|reason" (qwen sometimes does this)
      - "B|reason\\nsomething else"
    Strategy: scan every line, find the first one whose prefix is A/B/TIE.
    """
    text = text.strip()
    valid_labels = {label_first.upper(), label_second.upper(), "TIE"}

    raw_verdict = None
    reason = ""
    for line in text.split("\n"):
        line = line.strip()
        if "|" not in line:
            continue
        prefix = line.split("|", 1)[0].strip().upper()
        if prefix in valid_labels:
            raw_verdict = prefix
            reason = line.split("|", 1)[1].strip()
            break

    if raw_verdict is None:
        # Fallback: scan for A, B, or TIE as a standalone token
        for tok in text.split():
            tok_clean = tok.strip(".,:;|").upper()
            if tok_clean in valid_labels:
                raw_verdict = tok_clean
                reason = text[:150]
                break

    if raw_verdict is None:
        return "INCONCLUSIVE", f"unparsable: {text[:100]}"

    # Map to canonical A/B/TIE (unswap if needed)
    if raw_verdict == "TIE":
        return "TIE", reason
    elif raw_verdict == label_first.upper():
        return ("B" if swapped else "A"), reason
    elif raw_verdict == label_second.upper():
        return ("A" if swapped else "B"), reason
    return "INCONCLUSIVE", f"unrecognized: {raw_verdict}"


async def judge_comparison(task: str, expected_outcomes: list,
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
        call_judge(task, expected_outcomes, output_a, output_b, swap)
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
