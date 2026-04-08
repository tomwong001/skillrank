# SkillRank

Category-specific eval infrastructure for agent skill selection.

## Problem

Agents pick tools based on description quality, not task fitness — tools with better marketing get selected 3.6x more. Skills (MCP tools, agent skills) are new and nobody has solved evaluation for them.

## Approach

- **Skills-first**: Evaluate skills (not APIs) with category-specific rubrics
- **Category-aware eval**: Different dimensions for email_writing vs code_review vs web_search vs debugging
- **LLM-as-judge**: Automated evaluation protocol per category
- **User-submitted skills**: Platform evaluates and showcases, reducing crawl costs

## V1 Categories

| Category | Key Eval Dimensions |
|----------|-------------------|
| email_writing | tone accuracy, format compliance, personalization |
| code_review | issue detection rate, false positive rate, actionability |
| web_search | relevance, freshness, source quality |
| debugging | root cause accuracy, fix correctness, explanation clarity |

## Project Structure

```
├── demo.html              # Interactive scoring engine demo
├── recommender.py         # Weighted scoring engine (4 optimization presets)
├── skill_evaluator.py     # Multi-metric skill comparison framework
├── tool_registry.json     # 35 tools with quality scores
├── build_log.md           # Development iteration log
└── docs/
    └── design.md          # Full design doc from /office-hours
```

## Status

Pre-launch. Design validated via office hours session.
