"""
Import a handful of real skills.sh skills into the SkillRank DB.

Pilot scope: 5 react_component_design skills. No bulk eval — skills land at
baseline rating. Running this script from the project root with the DB env var
pointing to the local SQLite file will populate the skills table.

Usage:
    SKILLRANK_DB=./skillrank.db python -m scripts.import_sample
"""

import asyncio
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# Ensure project root is on sys.path so we can import api.*
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from api.database import init_db, get_db, bulk_import_skill  # noqa: E402


# Pilot skill set for react_component_design intent
PILOT_SKILLS = [
    {
        "id": "shadcn/ui/shadcn",
        "name": "shadcn",
        "repo_url": "https://github.com/shadcn/ui",
        "skill_path": "skills/shadcn",
        "author": "shadcn",
        "description": "Official shadcn/ui skill — component discovery, adding, debugging, composition.",
        "raw_url": "https://raw.githubusercontent.com/shadcn/ui/main/skills/shadcn/SKILL.md",
    },
    {
        "id": "nextlevelbuilder/ui-ux-pro-max-skill/ui-ux-pro-max",
        "name": "ui-ux-pro-max",
        "repo_url": "https://github.com/nextlevelbuilder/ui-ux-pro-max-skill",
        "skill_path": ".claude/skills/ui-ux-pro-max",
        "author": "nextlevelbuilder",
        "description": "UI/UX design intelligence with 50+ styles, 161 palettes, 57 font pairings, 10 stacks.",
        "raw_url": "https://raw.githubusercontent.com/nextlevelbuilder/ui-ux-pro-max-skill/main/.claude/skills/ui-ux-pro-max/SKILL.md",
    },
    {
        "id": "wshobson/agents/tailwind-design-system",
        "name": "tailwind-design-system",
        "repo_url": "https://github.com/wshobson/agents",
        "skill_path": "plugins/frontend-mobile-development/skills/tailwind-design-system",
        "author": "wshobson",
        "description": "Scalable design systems with Tailwind CSS v4, design tokens, component libraries.",
        "raw_url": "https://raw.githubusercontent.com/wshobson/agents/main/plugins/frontend-mobile-development/skills/tailwind-design-system/SKILL.md",
    },
    {
        "id": "google-labs-code/stitch-skills/react-components",
        "name": "stitch-react-components",
        "repo_url": "https://github.com/google-labs-code/stitch-skills",
        "skill_path": "skills/react-components",
        "author": "google-labs-code",
        "description": "Converts Stitch designs into modular Vite and React components with AST validation.",
        "raw_url": "https://raw.githubusercontent.com/google-labs-code/stitch-skills/main/skills/react-components/SKILL.md",
    },
    {
        "id": "google-labs-code/stitch-skills/shadcn-ui",
        "name": "stitch-shadcn-ui",
        "repo_url": "https://github.com/google-labs-code/stitch-skills",
        "skill_path": "skills/shadcn-ui",
        "author": "google-labs-code",
        "description": "Expert guidance for integrating and building with shadcn/ui via Stitch.",
        "raw_url": "https://raw.githubusercontent.com/google-labs-code/stitch-skills/main/skills/shadcn-ui/SKILL.md",
    },
]

INTENT = "react_component_design"


def fetch_skill_md(url: str) -> str:
    """Fetch a SKILL.md file over HTTP."""
    req = urllib.request.Request(url, headers={"User-Agent": "skillrank-import"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8")


async def main():
    await init_db()
    db = await get_db()
    try:
        imported = 0
        skipped = 0
        for skill in PILOT_SKILLS:
            print(f"Fetching {skill['id']}...", end=" ", flush=True)
            try:
                content = fetch_skill_md(skill["raw_url"])
            except Exception as e:
                print(f"FAIL: {e}")
                skipped += 1
                continue

            if len(content) < 200:
                print(f"SKIP (content too short: {len(content)} chars)")
                skipped += 1
                continue

            # Use a pseudo commit_sha — we don't pin SHAs for imported skills yet
            commit_sha = "imported"

            await bulk_import_skill(
                db,
                skill_id=skill["id"],
                name=skill["name"],
                repo_url=skill["repo_url"],
                skill_path=skill["skill_path"],
                commit_sha=commit_sha,
                intent=INTENT,
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
