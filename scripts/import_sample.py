"""
Import a curated set of real skills.sh skill PACKAGES into the SkillRank DB.

Important: a "skill" here is a whole repo/package (e.g. pbakaus/impeccable),
NOT a sub-skill inside it. Each (repo, intent) pair is ONE entry on the
leaderboard. A repo can appear under multiple intents — each with its own
representative sub-skill picked for eval.

Skill ID format: {author}/{repo}@{intent} — the @intent suffix lets the same
repo appear in multiple intents without PK collision. The dashboard strips
the suffix for display.

Usage:
    SKILLRANK_DB=./skillrank.db python -m scripts.import_sample [--intent X] [--wipe]
"""

import argparse
import asyncio
import sys
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from api.database import init_db, get_db, bulk_import_skill  # noqa: E402


# Each entry: one repo representing one intent.
# eval_skill_path = the sub-skill's SKILL.md we feed the executor (stored as skill_path in DB).
# The leaderboard shows display_name (owner/repo), links to the eval_skill_path subdir.
SKILL_CATALOG = [
    # ── react_component_design ──────────────────────────────────────────
    ("react_component_design", {
        "owner": "shadcn",
        "repo": "ui",
        "display_name": "shadcn/ui",
        "description": "Official shadcn/ui — component discovery, adding, debugging, composition.",
        "eval_skill_path": "skills/shadcn",
    }),
    ("react_component_design", {
        "owner": "pbakaus",
        "repo": "impeccable",
        "display_name": "pbakaus/impeccable",
        "description": "Impeccable design skills — for react_component_design, uses the impeccable meta-skill.",
        "eval_skill_path": ".agents/skills/impeccable",
    }),
    ("react_component_design", {
        "owner": "nextlevelbuilder",
        "repo": "ui-ux-pro-max-skill",
        "display_name": "nextlevelbuilder/ui-ux-pro-max-skill",
        "description": "UI/UX design intelligence with 50+ styles, 161 palettes, 57 font pairings, 10 stacks.",
        "eval_skill_path": ".claude/skills/ui-ux-pro-max",
    }),
    ("react_component_design", {
        "owner": "wshobson",
        "repo": "agents",
        "display_name": "wshobson/agents",
        "description": "Broad agent skill library; for react_component_design uses the web-component-design sub-skill.",
        "eval_skill_path": "plugins/ui-design/skills/web-component-design",
    }),
    ("react_component_design", {
        "owner": "google-labs-code",
        "repo": "stitch-skills",
        "display_name": "google-labs-code/stitch-skills",
        "description": "Stitch-to-code workflow; for react_component_design uses the react-components sub-skill.",
        "eval_skill_path": "skills/react-components",
    }),
    ("react_component_design", {
        "owner": "vercel-labs",
        "repo": "agent-skills",
        "display_name": "vercel-labs/agent-skills",
        "description": "Vercel's agent skills pack; uses the react-best-practices sub-skill here.",
        "eval_skill_path": "skills/react-best-practices",
    }),

    # ── ui_polish ────────────────────────────────────────────────────────
    ("ui_polish", {
        "owner": "pbakaus",
        "repo": "impeccable",
        "display_name": "pbakaus/impeccable",
        "description": "Impeccable design skills; for ui_polish uses the polish sub-skill.",
        "eval_skill_path": ".agents/skills/polish",
    }),
    ("ui_polish", {
        "owner": "anthropics",
        "repo": "skills",
        "display_name": "anthropics/skills",
        "description": "Anthropic's official skill pack; for ui_polish uses the frontend-design sub-skill.",
        "eval_skill_path": "skills/frontend-design",
    }),
    ("ui_polish", {
        "owner": "nextlevelbuilder",
        "repo": "ui-ux-pro-max-skill",
        "display_name": "nextlevelbuilder/ui-ux-pro-max-skill",
        "description": "UI/UX intelligence covering design quality, hierarchy, spacing, typography.",
        "eval_skill_path": ".claude/skills/ui-ux-pro-max",
    }),
    ("ui_polish", {
        "owner": "google-labs-code",
        "repo": "stitch-skills",
        "display_name": "google-labs-code/stitch-skills",
        "description": "Stitch skills; for ui_polish uses the taste-design sub-skill.",
        "eval_skill_path": "skills/taste-design",
    }),
    ("ui_polish", {
        "owner": "wshobson",
        "repo": "agents",
        "display_name": "wshobson/agents",
        "description": "Broad agent library; for ui_polish uses the visual-design-foundations sub-skill.",
        "eval_skill_path": "plugins/ui-design/skills/visual-design-foundations",
    }),
]


def fetch_skill_md(owner: str, repo: str, path: str) -> str:
    """Fetch SKILL.md over HTTPS."""
    url = f"https://raw.githubusercontent.com/{owner}/{repo}/main/{path}/SKILL.md"
    req = urllib.request.Request(url, headers={"User-Agent": "skillrank-import"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8")


async def wipe_catalog_intents(db):
    """Delete all catalog rows + related comparisons/eval_runs for the intents we're about to re-import."""
    intents = sorted({i for (i, _) in SKILL_CATALOG})
    if not intents:
        return
    placeholders = ",".join("?" for _ in intents)
    # Delete FK-child tables first
    await db.execute(
        f"DELETE FROM comparisons WHERE intent IN ({placeholders})",
        intents,
    )
    await db.execute(
        f"DELETE FROM eval_runs WHERE skill_id IN (SELECT id FROM skills WHERE intent IN ({placeholders}))",
        intents,
    )
    # Delete skills (PK) — must be after eval_runs due to FK
    await db.execute(
        f"DELETE FROM skills WHERE intent IN ({placeholders})",
        intents,
    )
    await db.commit()
    print(f"Wiped existing rows for intents: {', '.join(intents)}")


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--intent", default=None, help="Only import this intent")
    parser.add_argument("--wipe", action="store_true", help="Wipe existing rows for these intents first")
    args = parser.parse_args()

    await init_db()
    db = await get_db()
    try:
        if args.wipe:
            await wipe_catalog_intents(db)

        imported = 0
        skipped = 0
        for intent, entry in SKILL_CATALOG:
            if args.intent and intent != args.intent:
                continue

            skill_id = f"{entry['owner']}/{entry['repo']}@{intent}"
            print(f"[{intent}] {entry['display_name']} via {entry['eval_skill_path']}...", end=" ", flush=True)
            try:
                content = fetch_skill_md(entry["owner"], entry["repo"], entry["eval_skill_path"])
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
                skill_id=skill_id,
                name=entry["display_name"],
                repo_url=f"https://github.com/{entry['owner']}/{entry['repo']}",
                skill_path=entry["eval_skill_path"],  # where we read SKILL.md from (for link + eval audit)
                commit_sha="imported",
                intent=intent,
                description=entry["description"],
                author=entry["owner"],
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
