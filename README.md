# SkillRank

Category-specific eval infrastructure for agent skill selection.

## Problem

Agents pick tools based on description quality, not task fitness. Tools with better marketing get selected 3.6x more. Skills (MCP tools, agent skills) are new and nobody has solved evaluation for them.

## How it works

1. **Submit** your skill (GitHub repo with a SKILL.md)
2. **SkillRank runs it** in a Docker sandbox against hand-crafted scenarios
3. **LLM judges** compare your output against existing skills (pairwise A/B, position bias mitigated)
4. **Bradley-Terry rating** updates, you get a scorecard with strengths/weaknesses
5. **Leaderboard** ranks all skills by intent

## Quick start

```bash
# Install deps
pip install -r requirements.txt

# Run locally
python -m uvicorn api.main:app --reload

# Open http://localhost:8000
```

## API

```
POST /api/submit          Submit a skill for evaluation
GET  /api/submit/:id      Check eval status + scorecard
GET  /api/skills           List ranked skills by intent
GET  /api/health           Health check
```

## Architecture

```
                  ┌─────────────────────────┐
                  │     Dashboard (HTML)     │
                  │  Leaderboard / Submit /  │
                  │       Scorecard          │
                  └───────────┬─────────────┘
                              │
                  ┌───────────▼─────────────┐
                  │     FastAPI Server       │
                  │  POST /submit → eval     │
                  │  GET /skills → ranked    │
                  └───────────┬─────────────┘
                              │
              ┌───────────────┼───────────────┐
              │               │               │
    ┌─────────▼──────┐ ┌─────▼──────┐ ┌──────▼──────┐
    │ Docker Sandbox  │ │ LLM Judge  │ │ Bradley-    │
    │ (skill exec)    │ │ (OpenRouter)│ │ Terry       │
    │ 2CPU/4GB/120s   │ │ 3-run vote │ │ Rating      │
    └────────────────┘ └────────────┘ └─────────────┘
              │               │               │
              └───────────────┼───────────────┘
                              │
                  ┌───────────▼─────────────┐
                  │     SQLite (WAL mode)    │
                  │  skills / submissions /  │
                  │  comparisons / scenarios │
                  └─────────────────────────┘
```

## Project structure

```
skillrank/
├── api/
│   ├── main.py            # FastAPI app, routes, GitHub PAT verification
│   └── database.py        # SQLite schema + async data layer (5 tables)
├── eval/
│   ├── bradley_terry.py   # Rating system with uncertainty intervals
│   ├── engine.py          # Full eval pipeline orchestrator
│   └── sandbox.py         # Docker sandbox + subprocess fallback
├── judges/
│   └── pairwise.py        # LLM-as-judge, position bias mitigation, 3-run vote
├── scenarios/
│   └── ship_code_*.json   # 5 hand-crafted eval scenarios
├── dashboard/
│   ├── index.html         # Leaderboard
│   ├── submit.html        # Submission form + live eval terminal
│   └── scorecard.html     # Skill scorecard (the trading card)
├── tests/                 # 18 tests (rating + API)
├── Dockerfile
├── fly.toml               # Fly.io deploy config
└── requirements.txt
```

## V1 intent: `ship_code`

5 eval scenarios:
1. Python monorepo bug fix
2. TypeScript new feature
3. Documentation update
4. Multi-commit branch needing rebase
5. Failing CI that needs fix before ship

## Deploy

```bash
# Fly.io (SQLite requires single instance)
fly deploy
```

## Environment variables

```
OPENROUTER_API_KEY    # Required for LLM judge
JUDGE_MODEL           # Default: openrouter/auto
SKILLRANK_DB          # Default: ./skillrank.db
SKILLRANK_TIMEOUT     # Default: 120 (seconds)
```

## Status

V1 shipped. 18 tests passing. Local server working. Deploy infra ready.
