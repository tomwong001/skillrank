"""
Import a curated set of real skills.sh skills into the SkillRank DB.

Skills are grouped by intent. Only skills with verified SKILL.md paths are
included. No bulk eval — skills land at baseline rating. Run bulk_eval.py
afterward to populate ratings.

Usage:
    SKILLRANK_DB=./skillrank.db python -m scripts.import_sample [--intent X]
"""

import argparse
import asyncio
import sys
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from api.database import init_db, get_db, bulk_import_skill  # noqa: E402


# Curated skill catalog — paths verified via GitHub API.
# Each entry: (intent, skill dict)
SKILL_CATALOG = [
    # ── react_component_design ──────────────────────────────────────────
    ("react_component_design", {
        "id": "shadcn/ui/shadcn",
        "name": "shadcn",
        "repo_url": "https://github.com/shadcn/ui",
        "skill_path": "skills/shadcn",
        "author": "shadcn",
        "description": "Official shadcn/ui skill — component discovery, adding, debugging, composition.",
        "raw_url": "https://raw.githubusercontent.com/shadcn/ui/main/skills/shadcn/SKILL.md",
    }),
    ("react_component_design", {
        "id": "nextlevelbuilder/ui-ux-pro-max-skill/ui-ux-pro-max",
        "name": "ui-ux-pro-max",
        "repo_url": "https://github.com/nextlevelbuilder/ui-ux-pro-max-skill",
        "skill_path": ".claude/skills/ui-ux-pro-max",
        "author": "nextlevelbuilder",
        "description": "UI/UX design intelligence with 50+ styles, 161 palettes, 57 font pairings, 10 stacks.",
        "raw_url": "https://raw.githubusercontent.com/nextlevelbuilder/ui-ux-pro-max-skill/main/.claude/skills/ui-ux-pro-max/SKILL.md",
    }),
    ("react_component_design", {
        "id": "wshobson/agents/tailwind-design-system",
        "name": "tailwind-design-system",
        "repo_url": "https://github.com/wshobson/agents",
        "skill_path": "plugins/frontend-mobile-development/skills/tailwind-design-system",
        "author": "wshobson",
        "description": "Scalable design systems with Tailwind CSS v4, design tokens, component libraries.",
        "raw_url": "https://raw.githubusercontent.com/wshobson/agents/main/plugins/frontend-mobile-development/skills/tailwind-design-system/SKILL.md",
    }),
    ("react_component_design", {
        "id": "google-labs-code/stitch-skills/react-components",
        "name": "stitch-react-components",
        "repo_url": "https://github.com/google-labs-code/stitch-skills",
        "skill_path": "skills/react-components",
        "author": "google-labs-code",
        "description": "Converts Stitch designs into modular Vite and React components with AST validation.",
        "raw_url": "https://raw.githubusercontent.com/google-labs-code/stitch-skills/main/skills/react-components/SKILL.md",
    }),
    ("react_component_design", {
        "id": "google-labs-code/stitch-skills/shadcn-ui",
        "name": "stitch-shadcn-ui",
        "repo_url": "https://github.com/google-labs-code/stitch-skills",
        "skill_path": "skills/shadcn-ui",
        "author": "google-labs-code",
        "description": "Expert guidance for integrating and building with shadcn/ui via Stitch.",
        "raw_url": "https://raw.githubusercontent.com/google-labs-code/stitch-skills/main/skills/shadcn-ui/SKILL.md",
    }),

    # ── ui_polish ────────────────────────────────────────────────────────
    ("ui_polish", {
        "id": "pbakaus/impeccable/polish",
        "name": "polish",
        "repo_url": "https://github.com/pbakaus/impeccable",
        "skill_path": ".agents/skills/polish",
        "author": "pbakaus",
        "description": "Final quality pass fixing alignment, spacing, consistency, and micro-detail issues before shipping.",
        "raw_url": "https://raw.githubusercontent.com/pbakaus/impeccable/main/.agents/skills/polish/SKILL.md",
    }),
    ("ui_polish", {
        "id": "pbakaus/impeccable/critique",
        "name": "critique",
        "repo_url": "https://github.com/pbakaus/impeccable",
        "skill_path": ".agents/skills/critique",
        "author": "pbakaus",
        "description": "Evaluate design from a UX perspective — visual hierarchy, information architecture, cognitive load.",
        "raw_url": "https://raw.githubusercontent.com/pbakaus/impeccable/main/.agents/skills/critique/SKILL.md",
    }),
    ("ui_polish", {
        "id": "pbakaus/impeccable/optimize",
        "name": "optimize",
        "repo_url": "https://github.com/pbakaus/impeccable",
        "skill_path": ".agents/skills/optimize",
        "author": "pbakaus",
        "description": "Diagnose and fix UI performance — loading speed, rendering, animations, bundle size.",
        "raw_url": "https://raw.githubusercontent.com/pbakaus/impeccable/main/.agents/skills/optimize/SKILL.md",
    }),
    ("ui_polish", {
        "id": "pbakaus/impeccable/harden",
        "name": "harden",
        "repo_url": "https://github.com/pbakaus/impeccable",
        "skill_path": ".agents/skills/harden",
        "author": "pbakaus",
        "description": "Improve interface resilience — error handling, i18n, text overflow, edge cases.",
        "raw_url": "https://raw.githubusercontent.com/pbakaus/impeccable/main/.agents/skills/harden/SKILL.md",
    }),
    ("ui_polish", {
        "id": "pbakaus/impeccable/distill",
        "name": "distill",
        "repo_url": "https://github.com/pbakaus/impeccable",
        "skill_path": ".agents/skills/distill",
        "author": "pbakaus",
        "description": "Strip designs to their essence — remove unnecessary complexity, simplify, declutter.",
        "raw_url": "https://raw.githubusercontent.com/pbakaus/impeccable/main/.agents/skills/distill/SKILL.md",
    }),

    # ── seo_cro ──────────────────────────────────────────────────────────
    ("seo_cro", {
        "id": "coreyhaines31/marketingskills/seo-audit",
        "name": "seo-audit",
        "repo_url": "https://github.com/coreyhaines31/marketingskills",
        "skill_path": "skills/seo-audit",
        "author": "coreyhaines31",
        "description": "Audit, review, or diagnose SEO issues on a site — technical SEO, meta tags, crawl, indexing.",
        "raw_url": "https://raw.githubusercontent.com/coreyhaines31/marketingskills/main/skills/seo-audit/SKILL.md",
    }),
    ("seo_cro", {
        "id": "coreyhaines31/marketingskills/page-cro",
        "name": "page-cro",
        "repo_url": "https://github.com/coreyhaines31/marketingskills",
        "skill_path": "skills/page-cro",
        "author": "coreyhaines31",
        "description": "Optimize marketing page conversions — homepages, landing, pricing, feature, blog posts.",
        "raw_url": "https://raw.githubusercontent.com/coreyhaines31/marketingskills/main/skills/page-cro/SKILL.md",
    }),
    ("seo_cro", {
        "id": "coreyhaines31/marketingskills/signup-flow-cro",
        "name": "signup-flow-cro",
        "repo_url": "https://github.com/coreyhaines31/marketingskills",
        "skill_path": "skills/signup-flow-cro",
        "author": "coreyhaines31",
        "description": "Optimize signup/registration flows, friction removal, drop-off recovery.",
        "raw_url": "https://raw.githubusercontent.com/coreyhaines31/marketingskills/main/skills/signup-flow-cro/SKILL.md",
    }),
    ("seo_cro", {
        "id": "coreyhaines31/marketingskills/programmatic-seo",
        "name": "programmatic-seo",
        "repo_url": "https://github.com/coreyhaines31/marketingskills",
        "skill_path": "skills/programmatic-seo",
        "author": "coreyhaines31",
        "description": "Build pages at scale to target keywords — programmatic SEO strategy and execution.",
        "raw_url": "https://raw.githubusercontent.com/coreyhaines31/marketingskills/main/skills/programmatic-seo/SKILL.md",
    }),
    ("seo_cro", {
        "id": "coreyhaines31/marketingskills/ai-seo",
        "name": "ai-seo",
        "repo_url": "https://github.com/coreyhaines31/marketingskills",
        "skill_path": "skills/ai-seo",
        "author": "coreyhaines31",
        "description": "Optimize content for AI search engines — get cited by LLMs, appear in AI answers.",
        "raw_url": "https://raw.githubusercontent.com/coreyhaines31/marketingskills/main/skills/ai-seo/SKILL.md",
    }),
]


def fetch_skill_md(url: str) -> str:
    """Fetch a SKILL.md file over HTTP."""
    req = urllib.request.Request(url, headers={"User-Agent": "skillrank-import"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8")


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--intent", default=None, help="Only import this intent")
    args = parser.parse_args()

    await init_db()
    db = await get_db()
    try:
        imported = 0
        skipped = 0
        for intent, skill in SKILL_CATALOG:
            if args.intent and intent != args.intent:
                continue

            print(f"[{intent}] {skill['id']}...", end=" ", flush=True)
            try:
                content = fetch_skill_md(skill["raw_url"])
            except Exception as e:
                print(f"FAIL: {e}")
                skipped += 1
                continue

            if len(content) < 200:
                print(f"SKIP (too short: {len(content)} chars)")
                skipped += 1
                continue

            await bulk_import_skill(
                db,
                skill_id=skill["id"],
                name=skill["name"],
                repo_url=skill["repo_url"],
                skill_path=skill["skill_path"],
                commit_sha="imported",
                intent=intent,
                description=skill["description"],
                author=skill["author"],
                skill_md_content=content,
            )
            print(f"OK ({len(content)} chars)")
            imported += 1

        print()
        print(f"Imported: {imported}")
        print(f"Skipped: {skipped}")
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
