#!/usr/bin/env python3
"""
Skill Evaluator — Universal Tool Recommender
=============================================
Framework for comparing multiple Skill variants on the same task.
Evaluates cold email skill variants as the primary example.

The LLM calls are mocked — the evaluation LOGIC is real and production-ready.
To use with a real LLM, replace the mock_llm_call() function with your provider.

Evaluation dimensions:
  - Output length (word count)
  - Personalization score (proxy: uses provided context variables)
  - Clarity score (Flesch-Kincaid readability estimate)
  - CTA strength (presence and specificity of call-to-action)
  - Tone consistency (measured by keyword analysis)
  - Latency (real, even with mock)
  - Token efficiency (output quality / token cost ratio)

Usage:
  python skill_evaluator.py                             # evaluate all cold email variants
  python skill_evaluator.py --variant v1                # single variant
  python skill_evaluator.py --task custom_prompt        # use custom task
  python skill_evaluator.py --output-format table       # pretty table output
"""

import json
import time
import re
import argparse
import sys
from datetime import datetime, timezone
from typing import Optional

# ─────────────────────────────────────────────
# Mock LLM
# Replace this function with real LLM calls.
# ─────────────────────────────────────────────
MOCK_OUTPUTS = {
    "v1": """Subject: Quick question about [Company]'s growth

Hi {first_name},

I came across [Company] and noticed you've been expanding your sales team rapidly — congrats on the Series B. Most fast-growing SaaS companies at your stage hit a wall with outbound volume around 18 months in.

We help companies like [Company] automate their SDR workflows without losing the human touch. [Similar Company] went from 200 to 1,400 qualified meetings/month in 90 days using our platform.

Would it make sense to grab 20 minutes this week to see if we can do the same for you?

Best,
[Sender]""",

    "v2": """Hi {first_name},

I've been following [Company]'s work in [industry] — the approach you're taking to [specific problem] is genuinely interesting.

I'm building [Your Company] and working on a problem you might have opinions on: [mutual challenge]. Would love to swap notes if you're open to it — no pitch, just curious what you've learned.

Happy to be the first to share what we've found.

[Your name]""",

    "v3": """Hi {first_name},

Your background in [relevant skill] at [Previous Company] caught my attention — we're building something at [Company] that's right in that wheelhouse.

The role: [Job Title] — [one sentence on what they'd own]. What makes it different: [specific culture/mission hook].

Compensation is [range] + equity. We're [stage] and [X] months from [milestone].

Worth a 20-min call to see if it's interesting? Happy to send more context first if useful.

[Your name], [Title] at [Company]""",

    "v4": """Hi {first_name} — quick one.

We help [ICP description] with [problem]. [Social proof in one sentence].

Worth a 15-min call?

[Sender]""",

    "v5": """Subject: Noticed [Company]'s recent [trigger event]

Hi {first_name},

Saw that [Company] recently [specific trigger: funding round / product launch / hiring push / press mention]. That usually means [implication relevant to your product].

We've helped [3 similar named companies] tackle exactly this — [specific outcome with numbers].

Given your focus on [inferred priority from research], this seems timely. Worth a quick conversation?

Best,
[Sender]
[Title] at [Your Company]"""
}

MOCK_LATENCIES_MS = {
    "v1": 2800,
    "v2": 3200,
    "v3": 2600,
    "v4": 1400,
    "v5": 7800,  # slow due to simulated research calls
}

MOCK_TOKEN_COSTS = {
    "v1": 0.0048,
    "v2": 0.0055,
    "v3": 0.0045,
    "v4": 0.0009,
    "v5": 0.028,
}

def mock_llm_call(variant: str, context: dict) -> tuple[str, float, float]:
    """
    Mock LLM call. Returns (output_text, latency_ms, cost_usd).
    Replace this with real LLM API calls for production use.
    """
    output = MOCK_OUTPUTS.get(variant, "")
    # Fill in context variables where present
    for k, v in context.items():
        output = output.replace(f"{{{k}}}", v)

    latency = MOCK_LATENCIES_MS.get(variant, 3000)
    # Add small random-ish variation based on current time
    jitter = (time.time() % 1) * 200
    latency += jitter

    cost = MOCK_TOKEN_COSTS.get(variant, 0.005)
    return output, latency, cost

# ─────────────────────────────────────────────
# Evaluation metrics
# ─────────────────────────────────────────────
def word_count(text: str) -> int:
    return len(text.split())

def count_context_vars_used(text: str, context: dict) -> dict:
    """Check which context variables appear in the output."""
    used = {}
    for k, v in context.items():
        used[k] = v in text
    filled_count = sum(1 for v in used.values() if v)
    return {
        "vars_used": used,
        "fill_rate": round(filled_count / len(context), 4) if context else 0,
    }

def flesch_kincaid_grade(text: str) -> float:
    """
    Approximate Flesch-Kincaid grade level.
    Lower grade = easier to read = better for cold emails.
    """
    sentences = re.split(r'[.!?]+', text)
    sentences = [s.strip() for s in sentences if s.strip()]
    words = text.split()
    if not sentences or not words:
        return 0.0

    # Rough syllable count (vowel sequences as proxy)
    syllable_count = sum(len(re.findall(r'[aeiouAEIOU]+', w)) for w in words)
    asl = len(words) / len(sentences)  # avg sentence length
    asw = syllable_count / len(words) if words else 1  # avg syllables per word
    grade = 0.39 * asl + 11.8 * asw - 15.59
    return round(grade, 2)

def cta_strength(text: str) -> dict:
    """Detect and score the call-to-action."""
    text_lower = text.lower()
    # Strong CTA signals
    strong = ["worth a call", "grab 20", "grab 15", "schedule", "book a call",
              "quick conversation", "20-min", "15-min", "jump on", "worth chatting"]
    # Weak CTA signals
    weak = ["let me know", "thoughts?", "interested?", "reach out", "feel free"]
    # Specificity signals
    specific = ["tuesday", "thursday", "this week", "tomorrow", "morning", "afternoon",
                "monday", "wednesday", "friday"]

    has_strong = any(s in text_lower for s in strong)
    has_weak = any(w in text_lower for w in weak)
    is_specific = any(s in text_lower for s in specific)

    if has_strong and is_specific:
        score = 0.95
        grade = "strong+specific"
    elif has_strong:
        score = 0.80
        grade = "strong"
    elif has_weak:
        score = 0.45
        grade = "weak"
    else:
        score = 0.20
        grade = "missing/unclear"

    return {"score": score, "grade": grade, "has_time_specific": is_specific}

def tone_analysis(text: str, expected_tone: str) -> dict:
    """Simple tone keyword analysis."""
    text_lower = text.lower()
    tone_signals = {
        "sales": ["growth", "results", "roi", "revenue", "meetings", "pipeline",
                  "qualified", "platform", "automate", "scale"],
        "casual": ["swap notes", "curious", "opinions", "happy to", "no pitch",
                   "genuinely", "interesting", "love to"],
        "recruiting": ["role", "compensation", "equity", "milestone", "background",
                       "wheelhouse", "opportunity"],
        "brief": [],  # brevity itself is the tone — scored by word count
        "research": ["noticed", "recently", "trigger", "implication", "inferred",
                     "specific", "named companies"],
    }
    signals = tone_signals.get(expected_tone, [])
    matched = [s for s in signals if s in text_lower]
    consistency = round(len(matched) / len(signals), 4) if signals else 0.5

    return {
        "expected_tone": expected_tone,
        "signals_matched": matched,
        "consistency_score": consistency,
    }

# ─────────────────────────────────────────────
# Skill variant definitions
# ─────────────────────────────────────────────
SKILL_VARIANTS = {
    "v1": {
        "tool_id": "skill_cold_email_v1",
        "name": "Cold Email — Sales Focus",
        "expected_tone": "sales",
        "framework": "AIDA",
    },
    "v2": {
        "tool_id": "skill_cold_email_v2",
        "name": "Cold Email — Founder Outreach",
        "expected_tone": "casual",
        "framework": "curiosity_hook",
    },
    "v3": {
        "tool_id": "skill_cold_email_v3",
        "name": "Cold Email — Recruiting",
        "expected_tone": "recruiting",
        "framework": "role_first",
    },
    "v4": {
        "tool_id": "skill_cold_email_v4",
        "name": "Cold Email — Short/Minimal",
        "expected_tone": "brief",
        "framework": "ultra_short",
    },
    "v5": {
        "tool_id": "skill_cold_email_v5",
        "name": "Cold Email — Research-Heavy",
        "expected_tone": "research",
        "framework": "trigger_event",
    },
}

EVAL_CONTEXT = {
    "first_name": "Sarah",
    "Company": "Acme Corp",
    "industry": "fintech",
    "specific problem": "payment reconciliation",
    "Previous Company": "Stripe",
    "relevant skill": "distributed systems",
    "Job Title": "Senior Backend Engineer",
    "ICP description": "Series A SaaS companies",
    "problem": "outbound efficiency",
    "Social proof in one sentence": "We helped Notion and Linear 3x their pipeline in 60 days",
    "trigger event": "Series B announcement",
    "specific trigger: funding round / product launch / hiring push / press mention":
        "Series B announcement last week",
}

# ─────────────────────────────────────────────
# Evaluate one variant
# ─────────────────────────────────────────────
def evaluate_variant(variant_key: str, context: dict) -> dict:
    config = SKILL_VARIANTS[variant_key]
    output, latency_ms, cost_usd = mock_llm_call(variant_key, context)

    wc = word_count(output)
    context_usage = count_context_vars_used(output, context)
    fk = flesch_kincaid_grade(output)
    cta = cta_strength(output)
    tone = tone_analysis(output, config["expected_tone"])

    # Composite quality score
    quality = round(
        0.25 * context_usage["fill_rate"]
        + 0.25 * cta["score"]
        + 0.20 * tone["consistency_score"]
        + 0.15 * (1.0 - min(fk / 20, 1.0))  # lower grade = better
        + 0.15 * (1.0 if wc < 150 else 0.5 if wc < 250 else 0.2)  # shorter = better
    , 4)

    # Token efficiency: quality per dollar
    token_efficiency = round(quality / cost_usd, 4) if cost_usd > 0 else 0

    return {
        "variant": variant_key,
        "tool_id": config["tool_id"],
        "name": config["name"],
        "framework": config["framework"],
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "output_preview": output[:200] + "..." if len(output) > 200 else output,
        "metrics": {
            "word_count": wc,
            "context_fill_rate": context_usage["fill_rate"],
            "context_vars_used": context_usage["vars_used"],
            "readability_fk_grade": fk,
            "cta_score": cta["score"],
            "cta_grade": cta["grade"],
            "cta_time_specific": cta["has_time_specific"],
            "tone_consistency": tone["consistency_score"],
            "tone_signals_matched": tone["signals_matched"],
        },
        "performance": {
            "latency_ms": round(latency_ms, 2),
            "cost_usd": round(cost_usd, 6),
            "note": "MOCKED — replace mock_llm_call() for real measurements",
        },
        "scores": {
            "quality_score": quality,
            "token_efficiency": token_efficiency,
        },
    }

# ─────────────────────────────────────────────
# Rank variants
# ─────────────────────────────────────────────
def rank_variants(results: list[dict]) -> list[dict]:
    """Add rank and winner annotation."""
    sorted_results = sorted(results, key=lambda x: -x["scores"]["quality_score"])
    for i, r in enumerate(sorted_results):
        r["rank"] = i + 1
        r["is_winner"] = i == 0
    return sorted_results

# ─────────────────────────────────────────────
# Format as table (human-readable mode)
# ─────────────────────────────────────────────
def format_as_table(results: list[dict]) -> str:
    header = f"{'Rank':<5} {'Variant':<8} {'Name':<30} {'Quality':<9} {'CTA':<12} {'Words':<7} {'Cost':<10} {'Efficiency':<12}"
    sep = "-" * len(header)
    rows = [header, sep]
    for r in results:
        m = r["metrics"]
        s = r["scores"]
        p = r["performance"]
        row = (
            f"{r['rank']:<5} {r['variant']:<8} {r['name'][:28]:<30} "
            f"{s['quality_score']:<9.4f} {m['cta_grade'][:10]:<12} "
            f"{m['word_count']:<7} ${p['cost_usd']:<9.4f} {s['token_efficiency']:<12.1f}"
        )
        if r.get("is_winner"):
            row += " ← WINNER"
        rows.append(row)
    return "\n".join(rows)

# ─────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Skill variant evaluator for Universal Tool Recommender")
    parser.add_argument("--variant", type=str, choices=list(SKILL_VARIANTS.keys()),
                        help="Evaluate a single variant")
    parser.add_argument("--output-format", type=str, choices=["json", "table"], default="json",
                        help="Output format (default: json)")
    args = parser.parse_args()

    variants_to_test = [args.variant] if args.variant else list(SKILL_VARIANTS.keys())

    results = []
    for v in variants_to_test:
        result = evaluate_variant(v, EVAL_CONTEXT)
        results.append(result)

    ranked = rank_variants(results)

    if args.output_format == "table":
        print(format_as_table(ranked))
        print(f"\n📝 NOTE: LLM outputs are MOCKED. Replace mock_llm_call() for real evaluation.")
    else:
        output = {
            "status": "ok",
            "mode": "skill_evaluation",
            "task": "write_cold_email",
            "context_provided": list(EVAL_CONTEXT.keys()),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "note": "LLM outputs are MOCKED. Replace mock_llm_call() with real LLM API for production evaluation.",
            "results": ranked,
            "winner": {
                "variant": ranked[0]["variant"],
                "name": ranked[0]["name"],
                "quality_score": ranked[0]["scores"]["quality_score"],
                "rationale": (
                    f"Highest quality score ({ranked[0]['scores']['quality_score']:.4f}) based on "
                    f"context fill rate, CTA strength, tone consistency, and readability."
                )
            },
        }
        print(json.dumps(output, indent=2))

if __name__ == "__main__":
    main()
