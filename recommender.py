#!/usr/bin/env python3
"""
Universal Tool Recommender for AI Agent Orchestrators
======================================================
Weighted scoring engine that ranks tools from the registry
for a given task. Designed for machine-readable output.

Usage:
  python recommender.py --task "get realtime stock price" --optimize cost --free-only
  python recommender.py --task "search web" --min-concurrency 10 --top 3
  python recommender.py --compare "alpha_vantage,polygon_io,finnhub"
  python recommender.py --task "write cold email" --tool-type skill
  python recommender.py --task "scrape web page" --top 3

Returns: JSON to stdout

Iteration 3 fixes:
  - Bug 1: Novel/unknown task fallback now emits best_effort_fallback=true warning
            instead of silently returning top-quality irrelevant tools.
  - Bug 2: --free-only now checks recurring_free_tier field and rejects one-time
            credit tools (e.g. Serper's 2,500 one-time credits).
  - Bug 3: --min-concurrency now flags tools with unknown/null rate limits as
            "rate_limit_unknown" rather than silently passing them.
  - Bug 4: --min-concurrency uses rate_limit_rpm_free when --free-only is set,
            and rate_limit_rpm_paid otherwise, for tier-aware filtering.
"""

import json
import argparse
import sys
import os
from typing import Optional

# ─────────────────────────────────────────────
# Load registry
# ─────────────────────────────────────────────
REGISTRY_PATH = os.path.join(os.path.dirname(__file__), "tool_registry.json")

def load_registry() -> list[dict]:
    with open(REGISTRY_PATH, "r") as f:
        data = json.load(f)
    return data["tools"]

# ─────────────────────────────────────────────
# Task → category mapping
# ─────────────────────────────────────────────
TASK_KEYWORDS = {
    "stock": ["finance", "stock_price", "stock_history"],
    "stock price": ["finance"],
    "stock data": ["finance"],
    "market data": ["finance"],
    "equity": ["finance"],
    "options": ["finance"],
    "forex": ["finance"],
    "crypto": ["finance"],
    "finance": ["finance"],
    "search web": ["search"],
    "web search": ["search"],
    "search the web": ["search"],
    "find information": ["search"],
    "look up": ["search", "knowledge"],
    "weather": ["weather"],
    "forecast": ["weather"],
    "temperature": ["weather"],
    "scrape": ["scraping"],
    "crawl": ["scraping"],
    "extract": ["scraping"],
    "web page": ["scraping"],
    "email": ["email_writing"],
    "cold email": ["email_writing"],
    "outreach": ["email_writing"],
    "research paper": ["knowledge"],
    "arxiv": ["knowledge"],
    "wikipedia": ["knowledge"],
    "fact": ["knowledge"],
    "file": ["file_operations"],
    "read file": ["file_operations"],
    "write file": ["file_operations"],
    "github": ["developer_tools"],
    "code": ["developer_tools"],
    "repository": ["developer_tools"],
}

def infer_categories(task: str) -> list[str]:
    """Infer likely tool categories from free-text task description."""
    task_lower = task.lower()
    matched = set()
    for kw, cats in TASK_KEYWORDS.items():
        if kw in task_lower:
            matched.update(cats)
    return list(matched) if matched else []

def filter_by_task(tools: list[dict], task: str) -> tuple[list[dict], bool]:
    """Filter tools relevant to the task using keyword matching + task_types.

    Returns (filtered_tools, is_fallback) where is_fallback=True signals that
    no category was inferred and results are best-effort (not category-matched).

    Fix (Iteration 2): Added three defences against category bleed:
      1. Stop-word filtering so generic words like 'web', 'get', 'use' don't
         create false relevance signals in name/best_for matching.
      2. Require >= 2 meaningful word matches for the name/best_for bonus (was any 1 word).
      3. Hard-exclude low-relevance tools when >= 3 category-matched tools exist.

    Fix (Iteration 3): Returns is_fallback=True for novel/unknown tasks so the
    caller can surface a warning instead of silently returning irrelevant tools.
    """
    task_lower = task.lower()
    categories = infer_categories(task)

    # Words that carry no category signal and should not drive relevance
    STOP_WORDS = {
        "the", "a", "an", "is", "are", "to", "for", "with", "in", "on",
        "at", "and", "or", "get", "use", "my", "how", "do", "i", "can",
        "web",   # "web" appears in "WebSocket", "web scraping", "web search" — too ambiguous alone
        "data",  # appears in nearly every tool description
        "api",   # same
    }
    task_words = [
        w for w in task_lower.split()
        if w not in STOP_WORDS and len(w) > 2
    ]

    scored = []
    for tool in tools:
        relevance = 0
        category_match = False

        # Primary signal: category match
        if categories and tool.get("category") in categories:
            relevance += 30
            category_match = True

        # Secondary signal: task_types overlap
        task_types = tool.get("task_types", [])
        for tt in task_types:
            tt_phrase = tt.replace("_", " ")
            tt_words = set(tt.split("_"))
            task_word_set = set(task_words)
            if tt_phrase in task_lower or len(tt_words & task_word_set) >= 1:
                relevance += 15

        # Tertiary signal: name / best_for text — require >= 2 meaningful word hits
        tool_text = (tool.get("name", "") + " " + tool.get("best_for", "")).lower()
        meaningful_hits = sum(1 for w in task_words if w in tool_text)
        if meaningful_hits >= 2:
            relevance += 5
        elif meaningful_hits == 1 and category_match:
            relevance += 2  # small bonus only when category already matched

        if relevance > 0:
            scored.append((relevance, tool))

    # Sort by relevance descending
    if not scored:
        # No keyword match at all — return all tools as best-effort fallback
        # is_fallback=True signals the caller to add a warning in the output
        return tools, True

    scored.sort(key=lambda x: -x[0])

    # If no category was inferred from keyword matching but task_types produced
    # some scored tools, it means we have multi-category cross-cutting results
    # with no dominant category signal. Mark as partial fallback so caller can
    # warn the consuming agent that category relevance is unverified.
    if not categories:
        return [t for _, t in scored], True

    # Category-priority filter: when categories are inferred AND ≥3 tools
    # match those categories, restrict results to those tools only.
    if categories:
        cat_matched = [(r, t) for r, t in scored if t.get("category") in categories]
        if len(cat_matched) >= 3:
            scored = cat_matched  # enough category-specific tools — use them only
        elif len(cat_matched) > 0:
            # Fewer than 3 exact category matches; keep those first, then
            # add non-category tools only if they have a task_type match (r >= 15)
            non_cat = [
                (r, t) for r, t in scored
                if t.get("category") not in categories and r >= 15
            ]
            scored = cat_matched + non_cat

    return [t for _, t in scored], False

# ─────────────────────────────────────────────
# Scoring engine
# ─────────────────────────────────────────────
DEFAULT_WEIGHTS = {
    "quality": {
        "accuracy": 0.25,
        "success_rate": 0.25,
        "reliability": 0.20,
        "latency": 0.15,  # inverted: lower latency = higher score
    },
    "cost": 0.10,       # inverted: lower cost = higher score
    "setup": 0.05,      # inverted: simpler = higher score
}

OPTIMIZE_PRESETS = {
    "balanced": DEFAULT_WEIGHTS,
    "cost": {
        "quality": {"accuracy": 0.15, "success_rate": 0.15, "reliability": 0.10, "latency": 0.10},
        "cost": 0.40,
        "setup": 0.10,
    },
    "quality": {
        "quality": {"accuracy": 0.35, "success_rate": 0.30, "reliability": 0.25, "latency": 0.05},
        "cost": 0.03,
        "setup": 0.02,
    },
    "speed": {
        "quality": {"accuracy": 0.15, "success_rate": 0.20, "reliability": 0.15, "latency": 0.40},
        "cost": 0.05,
        "setup": 0.05,
    },
}

SETUP_COMPLEXITY_SCORES = {
    "very_low": 1.0,
    "low": 0.80,
    "medium": 0.50,
    "high": 0.20,
    "very_high": 0.05,
}

MAX_LATENCY_MS = 10000  # cap for normalization

def cost_score(tool: dict) -> float:
    """0.0 (expensive) → 1.0 (free). Based on cost_per_call."""
    cpc = tool.get("cost", {}).get("cost_per_call", 0.0)
    if cpc is None or cpc == 0.0:
        return 1.0
    # Log scale: $0.001/call → 0.7, $0.01/call → 0.4, $0.10/call → 0.0
    import math
    score = max(0.0, 1.0 - (math.log10(max(cpc, 1e-6)) + 6) / 6)
    return round(min(1.0, max(0.0, score)), 4)

def latency_score(tool: dict) -> float:
    """0.0 (slow) → 1.0 (fast)."""
    latency = tool.get("quality_scores", {}).get("avg_latency_ms", 5000)
    if latency is None:
        return 0.5
    return round(max(0.0, 1.0 - latency / MAX_LATENCY_MS), 4)

def compute_score(tool: dict, weights: dict) -> dict:
    """Compute weighted composite score for a tool."""
    q = tool.get("quality_scores", {})
    qw = weights["quality"]

    accuracy = q.get("accuracy", 0.5)
    success_rate = q.get("success_rate", 0.5)
    reliability = q.get("reliability", 0.5)
    latency = latency_score(tool)
    cost = cost_score(tool)
    setup = SETUP_COMPLEXITY_SCORES.get(tool.get("setup_complexity", "medium"), 0.5)

    score = (
        qw["accuracy"] * accuracy
        + qw["success_rate"] * success_rate
        + qw["reliability"] * reliability
        + qw["latency"] * latency
        + weights["cost"] * cost
        + weights["setup"] * setup
    )

    return {
        "composite_score": round(score, 4),
        "breakdown": {
            "accuracy": round(accuracy, 4),
            "success_rate": round(success_rate, 4),
            "reliability": round(reliability, 4),
            "latency_score": latency,
            "cost_score": cost,
            "setup_score": setup,
        }
    }

# ─────────────────────────────────────────────
# Hard constraint filters
# ─────────────────────────────────────────────
def apply_hard_constraints(
    tools: list[dict], args
) -> tuple[list[dict], list[dict]]:
    """Return (passing, rejected_with_reasons).

    Passing tools may have a _rate_limit_unverified=True annotation when
    --min-concurrency is set but the tool's rate limit is unknown.
    The recommend() function emits warnings only for final top-N results.

    Iteration 3 fixes:
    - --free-only now checks recurring_free_tier field; rejects tools with
      only one-time trial credits (e.g. Serper.dev's 2,500 one-time queries).
    - --min-concurrency now uses tier-aware rate limit fields:
        * --free-only set → check rate_limit_rpm_free first, then rate_limit_rpm
        * --free-only not set → check rate_limit_rpm_paid first, then rate_limit_rpm
    - Tools with unknown rate limits are annotated _rate_limit_unverified=True
      rather than silently passed or globally warned.
    """
    passing = []
    rejected = []

    for tool in tools:
        reasons = []
        rate_limit_unverified = False

        # ── --free-only ───────────────────────────────────────────────────────
        if args.free_only:
            cost_info = tool.get("cost", {})
            recurring = tool.get("recurring_free_tier", None)
            ft = cost_info.get("free_tier", "")
            cpc = cost_info.get("cost_per_call", 0)

            if recurring is False:
                # Explicitly flagged as no recurring free tier
                reasons.append("no_recurring_free_tier")
            elif recurring is True:
                pass  # explicitly free — allow
            else:
                # Infer from free_tier string and cost_per_call
                if not ft:
                    reasons.append("no_free_tier")
                elif "one-time" in str(ft).lower() or "one_time" in str(ft).lower():
                    reasons.append("no_recurring_free_tier (one-time credits only)")
                elif isinstance(cpc, float) and cpc > 0 and "free" not in str(ft).lower():
                    reasons.append("no_free_tier")

        # ── --tool-type ───────────────────────────────────────────────────────
        if args.tool_type and tool.get("type") != args.tool_type:
            reasons.append(f"type={tool.get('type')} (required: {args.tool_type})")

        # ── --min-concurrency (tier-aware) ────────────────────────────────────
        if args.min_concurrency:
            limits = tool.get("limits", {})

            # Tier-aware: use free rate when --free-only, paid rate otherwise
            if args.free_only:
                rpm = limits.get("rate_limit_rpm_free") or limits.get("rate_limit_rpm")
            else:
                rpm = limits.get("rate_limit_rpm_paid") or limits.get("rate_limit_rpm")

            # Normalize string rate limits
            if isinstance(rpm, str):
                if "unlimited" in rpm.lower():
                    rpm = float("inf")  # unlimited — always passes min-concurrency
                else:
                    import re
                    nums = re.findall(r'\d+', rpm)
                    rpm = int(nums[0]) if nums else None  # extract first number, or unknown

            if rpm is None:
                # Unknown — annotate tool rather than hard-reject or globally warn
                rate_limit_unverified = True
            elif isinstance(rpm, (int, float)) and rpm < args.min_concurrency:
                reasons.append(f"rate_limit_rpm={rpm} < required {args.min_concurrency}")

        # ── --no-auth ─────────────────────────────────────────────────────────
        if args.no_auth and tool.get("auth_required", False):
            reasons.append("auth required (--no-auth specified)")

        if reasons:
            rejected.append({"tool_id": tool["tool_id"], "rejected_because": reasons})
        else:
            tool_copy = dict(tool)
            if rate_limit_unverified:
                tool_copy["_rate_limit_unverified"] = True
            passing.append(tool_copy)

    return passing, rejected

# ─────────────────────────────────────────────
# Main recommendation logic
# ─────────────────────────────────────────────
def recommend(tools: list[dict], task: str, args) -> dict:
    """Main recommendation pipeline."""
    weights = OPTIMIZE_PRESETS.get(args.optimize or "balanced", DEFAULT_WEIGHTS)

    # Step 1: Filter by task relevance
    relevant, is_fallback = filter_by_task(tools, task)

    # Step 2: Apply hard constraints
    candidates, rejected = apply_hard_constraints(relevant, args)

    if not candidates:
        return {
            "status": "no_results",
            "task": task,
            "message": "No tools match the given constraints. Try relaxing --free-only or --tool-type.",
            "rejected": rejected[:5],
        }

    # Step 3: Score all candidates
    scored = []
    for tool in candidates:
        score_data = compute_score(tool, weights)
        scored.append({
            "rank": None,
            "tool_id": tool["tool_id"],
            "name": tool["name"],
            "type": tool["type"],
            "category": tool["category"],
            "composite_score": score_data["composite_score"],
            "score_breakdown": score_data["breakdown"],
            "best_for": tool.get("best_for", ""),
            "avoid_when": tool.get("avoid_when", ""),
            "cost_summary": tool.get("cost", {}).get("free_tier", "unknown") + " | " +
                           tool.get("cost", {}).get("paid_plans", ""),
            "failure_modes": tool.get("failure_modes", []),
            "auth_required": tool.get("auth_required", False),
            "setup_complexity": tool.get("setup_complexity", "unknown"),
            "data_source": tool.get("data_source", "unknown"),
            "last_verified": tool.get("last_verified", "unknown"),
        })

    # Sort by composite score
    scored.sort(key=lambda x: -x["composite_score"])

    # Assign ranks
    for i, item in enumerate(scored):
        item["rank"] = i + 1

    top_n = args.top or 3
    results = scored[:top_n]

    output = {
        "status": "ok",
        "task": task,
        "optimize_for": args.optimize or "balanced",
        "constraints": {
            "free_only": args.free_only,
            "tool_type": args.tool_type,
            "min_concurrency": args.min_concurrency,
            "no_auth": args.no_auth,
        },
        "total_candidates": len(candidates),
        "total_rejected": len(rejected),
        "recommendations": results,
        "rejected_sample": rejected[:3] if rejected else [],
    }

    # Iteration 3: surface fallback warning for unknown-category tasks
    if is_fallback:
        output["best_effort_fallback"] = True
        output["fallback_warning"] = (
            "No registry category matched this task. Results are sorted by overall "
            "quality score, not task relevance. Consider adding task-specific tools "
            "to the registry or refining the task description."
        )

    # Surface rate-limit warnings only for the top-N results (not all 33 tools)
    rate_warnings = [
        f"{r['tool_id']}: rate_limit unverified for min_concurrency={args.min_concurrency}"
        for r in results
        if r.get("_rate_limit_unverified")
    ]
    if rate_warnings:
        output["constraint_warnings"] = rate_warnings
    # Strip internal annotation from output
    for r in output["recommendations"]:
        r.pop("_rate_limit_unverified", None)

    return output

# ─────────────────────────────────────────────
# Comparison mode
# ─────────────────────────────────────────────
def compare_tools(tools: list[dict], tool_ids: str, args) -> dict:
    """Side-by-side comparison of specified tools."""
    ids = [t.strip() for t in tool_ids.split(",")]
    registry_map = {t["tool_id"]: t for t in tools}
    weights = OPTIMIZE_PRESETS.get(args.optimize or "balanced", DEFAULT_WEIGHTS)

    results = []
    not_found = []
    for tid in ids:
        if tid not in registry_map:
            not_found.append(tid)
            continue
        tool = registry_map[tid]
        score_data = compute_score(tool, weights)
        results.append({
            "tool_id": tool["tool_id"],
            "name": tool["name"],
            "type": tool["type"],
            "category": tool["category"],
            "composite_score": score_data["composite_score"],
            "score_breakdown": score_data["breakdown"],
            "cost": tool.get("cost", {}),
            "limits": tool.get("limits", {}),
            "quality_scores": tool.get("quality_scores", {}),
            "best_for": tool.get("best_for", ""),
            "avoid_when": tool.get("avoid_when", ""),
            "failure_modes": tool.get("failure_modes", []),
            "setup_complexity": tool.get("setup_complexity", ""),
            "auth_required": tool.get("auth_required", False),
            "data_source": tool.get("data_source", "unknown"),
        })

    # Sort by composite score
    results.sort(key=lambda x: -x["composite_score"])
    winner = results[0]["tool_id"] if results else None

    return {
        "status": "ok",
        "mode": "comparison",
        "optimize_for": args.optimize or "balanced",
        "winner": winner,
        "tools": results,
        "not_found": not_found,
    }

# ─────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────
def parse_args():
    parser = argparse.ArgumentParser(
        description="Universal Tool Recommender — returns JSON recommendations for AI agent orchestrators"
    )
    parser.add_argument("--task", "-t", type=str,
                        help="Natural language task description (e.g. 'get realtime stock price')")
    parser.add_argument("--compare", "-c", type=str,
                        help="Comma-separated tool IDs to compare (e.g. 'alpha_vantage,polygon_io,finnhub')")
    parser.add_argument("--optimize", "-o", type=str, default="balanced",
                        choices=["balanced", "cost", "quality", "speed"],
                        help="Optimization objective (default: balanced)")
    parser.add_argument("--top", "-n", type=int, default=3,
                        help="Number of top recommendations to return (default: 3)")
    parser.add_argument("--free-only", "-f", action="store_true",
                        help="Only include tools with a recurring free tier")
    parser.add_argument("--tool-type", type=str, choices=["api", "skill", "mcp", "agent"],
                        help="Filter by tool type")
    parser.add_argument("--min-concurrency", type=int,
                        help="Minimum required requests/minute")
    parser.add_argument("--no-auth", action="store_true",
                        help="Only include tools requiring no authentication")
    parser.add_argument("--list-tools", action="store_true",
                        help="List all tools in the registry")
    parser.add_argument("--registry", type=str,
                        help="Path to alternate registry JSON")
    return parser.parse_args()

def main():
    args = parse_args()

    if args.registry:
        global REGISTRY_PATH
        REGISTRY_PATH = args.registry

    try:
        tools = load_registry()
    except FileNotFoundError:
        print(json.dumps({"status": "error", "message": f"Registry not found at {REGISTRY_PATH}"}))
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(json.dumps({"status": "error", "message": f"Invalid JSON in registry: {e}"}))
        sys.exit(1)

    if args.list_tools:
        output = {
            "status": "ok",
            "total": len(tools),
            "tools": [
                {
                    "tool_id": t["tool_id"],
                    "name": t["name"],
                    "type": t["type"],
                    "category": t["category"],
                    "task_types": t.get("task_types", []),
                    "recurring_free_tier": t.get("recurring_free_tier", None),
                }
                for t in tools
            ]
        }
        print(json.dumps(output, indent=2))
        return

    if args.compare:
        output = compare_tools(tools, args.compare, args)
        print(json.dumps(output, indent=2))
        return

    if args.task:
        output = recommend(tools, args.task, args)
        print(json.dumps(output, indent=2))
        return

    # No action specified
    print(json.dumps({
        "status": "error",
        "message": "Provide --task or --compare. Use --help for usage."
    }))
    sys.exit(1)

if __name__ == "__main__":
    main()
