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


# Each entry: (intent, {owner, repo, display_name, description, eval_skill_path}).
# eval_skill_path = the sub-directory containing SKILL.md that we feed to the
# executor. The display_name is always "owner/repo". The same repo can appear
# under multiple intents with different representative sub-skills.
SKILL_CATALOG = [
    # ═══════════════════════════════════════════════════════════════════
    # react_component_design — building React/UI components
    # ═══════════════════════════════════════════════════════════════════
    ("react_component_design", {
        "owner": "shadcn", "repo": "ui",
        "display_name": "shadcn/ui",
        "description": "Official shadcn/ui — component discovery, adding, debugging, composition.",
        "eval_skill_path": "skills/shadcn",
    }),
    ("react_component_design", {
        "owner": "pbakaus", "repo": "impeccable",
        "display_name": "pbakaus/impeccable",
        "description": "Impeccable design skills — craft, teach, polish UI with design-system rigor.",
        "eval_skill_path": ".agents/skills/impeccable",
    }),
    ("react_component_design", {
        "owner": "nextlevelbuilder", "repo": "ui-ux-pro-max-skill",
        "display_name": "nextlevelbuilder/ui-ux-pro-max-skill",
        "description": "UI/UX design intelligence with 50+ styles, 161 palettes, 57 font pairings, 10 stacks.",
        "eval_skill_path": ".claude/skills/ui-ux-pro-max",
    }),
    ("react_component_design", {
        "owner": "wshobson", "repo": "agents",
        "display_name": "wshobson/agents",
        "description": "Broad agent library; for React uses the web-component-design sub-skill.",
        "eval_skill_path": "plugins/ui-design/skills/web-component-design",
    }),
    ("react_component_design", {
        "owner": "google-labs-code", "repo": "stitch-skills",
        "display_name": "google-labs-code/stitch-skills",
        "description": "Stitch-to-code workflow; uses react-components sub-skill.",
        "eval_skill_path": "skills/react-components",
    }),
    ("react_component_design", {
        "owner": "vercel-labs", "repo": "agent-skills",
        "display_name": "vercel-labs/agent-skills",
        "description": "Vercel's agent skills pack; uses react-best-practices sub-skill.",
        "eval_skill_path": "skills/react-best-practices",
    }),

    # ═══════════════════════════════════════════════════════════════════
    # ui_polish — visual quality, spacing, hierarchy, design system
    # ═══════════════════════════════════════════════════════════════════
    ("ui_polish", {
        "owner": "pbakaus", "repo": "impeccable",
        "display_name": "pbakaus/impeccable",
        "description": "Impeccable design; for ui_polish uses the polish sub-skill.",
        "eval_skill_path": ".agents/skills/polish",
    }),
    ("ui_polish", {
        "owner": "anthropics", "repo": "skills",
        "display_name": "anthropics/skills",
        "description": "Anthropic's official skill pack; uses the frontend-design sub-skill.",
        "eval_skill_path": "skills/frontend-design",
    }),
    ("ui_polish", {
        "owner": "nextlevelbuilder", "repo": "ui-ux-pro-max-skill",
        "display_name": "nextlevelbuilder/ui-ux-pro-max-skill",
        "description": "UI/UX intelligence covering design quality, hierarchy, spacing, typography.",
        "eval_skill_path": ".claude/skills/ui-ux-pro-max",
    }),
    ("ui_polish", {
        "owner": "google-labs-code", "repo": "stitch-skills",
        "display_name": "google-labs-code/stitch-skills",
        "description": "Stitch skills; uses the taste-design sub-skill for polish.",
        "eval_skill_path": "skills/taste-design",
    }),
    ("ui_polish", {
        "owner": "wshobson", "repo": "agents",
        "display_name": "wshobson/agents",
        "description": "Broad agent library; uses visual-design-foundations for polish work.",
        "eval_skill_path": "plugins/ui-design/skills/visual-design-foundations",
    }),

    # ═══════════════════════════════════════════════════════════════════
    # cloud_deploy — ship apps to cloud/CDN/containers
    # ═══════════════════════════════════════════════════════════════════
    ("cloud_deploy", {
        "owner": "vercel-labs", "repo": "agent-skills",
        "display_name": "vercel-labs/agent-skills",
        "description": "Vercel's deployment skills, CLI patterns, edge/server config.",
        "eval_skill_path": "skills/deploy-to-vercel",
    }),
    ("cloud_deploy", {
        "owner": "microsoft", "repo": "azure-skills",
        "display_name": "microsoft/azure-skills",
        "description": "Azure cloud deployment, resource provisioning, infra-as-code.",
        "eval_skill_path": "skills/azure-deploy",
    }),
    ("cloud_deploy", {
        "owner": "microsoft", "repo": "github-copilot-for-azure",
        "display_name": "microsoft/github-copilot-for-azure",
        "description": "Azure via GitHub Copilot — deployment, upgrade, compute.",
        "eval_skill_path": "plugin/skills/azure-compute",
    }),
    ("cloud_deploy", {
        "owner": "expo", "repo": "skills",
        "display_name": "expo/skills",
        "description": "Expo mobile deployment, EAS build, CI/CD pipelines.",
        "eval_skill_path": "plugins/expo/skills/expo-deployment",
    }),
    ("cloud_deploy", {
        "owner": "wshobson", "repo": "agents",
        "display_name": "wshobson/agents",
        "description": "Broad agent library; uses deployment-pipeline-design sub-skill.",
        "eval_skill_path": "plugins/cicd-automation/skills/deployment-pipeline-design",
    }),
    ("cloud_deploy", {
        "owner": "xixu-me", "repo": "skills",
        "display_name": "xixu-me/skills",
        "description": "Secure Linux cloud hosting and openclaw-secure-linux-cloud workflow.",
        "eval_skill_path": "skills/openclaw-secure-linux-cloud",
    }),
    ("cloud_deploy", {
        "owner": "charon-fan", "repo": "agent-playbook",
        "display_name": "charon-fan/agent-playbook",
        "description": "Agent playbook; uses the deployment-engineer sub-skill.",
        "eval_skill_path": "skills/deployment-engineer",
    }),

    # ═══════════════════════════════════════════════════════════════════
    # database_design — schema design, query patterns, migrations
    # ═══════════════════════════════════════════════════════════════════
    ("database_design", {
        "owner": "supabase", "repo": "agent-skills",
        "display_name": "supabase/agent-skills",
        "description": "Supabase Postgres best practices, RLS, row-level security, migrations.",
        "eval_skill_path": "skills/supabase-postgres-best-practices",
    }),
    ("database_design", {
        "owner": "neondatabase", "repo": "agent-skills",
        "display_name": "neondatabase/agent-skills",
        "description": "Neon serverless Postgres, branching, egress optimization.",
        "eval_skill_path": "skills/neon-postgres",
    }),
    ("database_design", {
        "owner": "get-convex", "repo": "agent-skills",
        "display_name": "get-convex/agent-skills",
        "description": "Convex real-time database — schema, queries, migrations.",
        "eval_skill_path": "skills/convex-quickstart",
    }),
    ("database_design", {
        "owner": "wshobson", "repo": "agents",
        "display_name": "wshobson/agents",
        "description": "Broad agent library; uses postgresql sub-skill for database-design.",
        "eval_skill_path": "plugins/database-design/skills/postgresql",
    }),
    ("database_design", {
        "owner": "microsoft", "repo": "github-copilot-for-azure",
        "display_name": "microsoft/github-copilot-for-azure",
        "description": "Azure database — Postgres, CosmosDB, SQL patterns via Copilot for Azure.",
        "eval_skill_path": "plugin/skills/azure-postgres",
    }),

    # ═══════════════════════════════════════════════════════════════════
    # backend_api_architecture — API design, patterns, auth, microservices
    # ═══════════════════════════════════════════════════════════════════
    ("backend_api_architecture", {
        "owner": "wshobson", "repo": "agents",
        "display_name": "wshobson/agents",
        "description": "Backend development patterns — API design principles, architecture.",
        "eval_skill_path": "plugins/backend-development/skills/api-design-principles",
    }),
    ("backend_api_architecture", {
        "owner": "anthropics", "repo": "skills",
        "display_name": "anthropics/skills",
        "description": "Anthropic's official skill pack; uses the claude-api sub-skill for backend integration.",
        "eval_skill_path": "skills/claude-api",
    }),
    ("backend_api_architecture", {
        "owner": "charon-fan", "repo": "agent-playbook",
        "display_name": "charon-fan/agent-playbook",
        "description": "Agent playbook; uses api-designer sub-skill for backend API design.",
        "eval_skill_path": "skills/api-designer",
    }),
    ("backend_api_architecture", {
        "owner": "vercel-labs", "repo": "agent-skills",
        "display_name": "vercel-labs/agent-skills",
        "description": "Vercel composition patterns and API routes.",
        "eval_skill_path": "skills/composition-patterns",
    }),
    ("backend_api_architecture", {
        "owner": "expo", "repo": "skills",
        "display_name": "expo/skills",
        "description": "Expo API routes, server-side rendering, native data fetching.",
        "eval_skill_path": "plugins/expo/skills/expo-api-routes",
    }),

    # ═══════════════════════════════════════════════════════════════════
    # web_scraping — fetch + parse web content into structured data
    # ═══════════════════════════════════════════════════════════════════
    ("web_scraping", {
        "owner": "firecrawl", "repo": "cli",
        "display_name": "firecrawl/cli",
        "description": "Firecrawl scrape — turn URLs into clean markdown, extract structured data.",
        "eval_skill_path": "skills/firecrawl-scrape",
    }),
    ("web_scraping", {
        "owner": "browser-use", "repo": "browser-use",
        "display_name": "browser-use/browser-use",
        "description": "Browser-use skill for programmatic browser automation and scraping.",
        "eval_skill_path": "skills/browser-use",
    }),
    ("web_scraping", {
        "owner": "jimliu", "repo": "baoyu-skills",
        "display_name": "jimliu/baoyu-skills",
        "description": "baoyu-url-to-markdown — fetch any URL, site-specific adapters (X/Twitter, YouTube, HN).",
        "eval_skill_path": "skills/baoyu-url-to-markdown",
    }),
    ("web_scraping", {
        "owner": "xixu-me", "repo": "skills",
        "display_name": "xixu-me/skills",
        "description": "Browser automation via use-my-browser skill.",
        "eval_skill_path": "skills/use-my-browser",
    }),

    # ═══════════════════════════════════════════════════════════════════
    # debugging_investigation — root cause, systematic debug, testing
    # ═══════════════════════════════════════════════════════════════════
    ("debugging_investigation", {
        "owner": "obra", "repo": "superpowers",
        "display_name": "obra/superpowers",
        "description": "Systematic debugging — hypothesis-driven root-cause investigation.",
        "eval_skill_path": "skills/systematic-debugging",
    }),
    ("debugging_investigation", {
        "owner": "anthropics", "repo": "skills",
        "display_name": "anthropics/skills",
        "description": "webapp-testing — browser-based testing and bug reproduction.",
        "eval_skill_path": "skills/webapp-testing",
    }),
    ("debugging_investigation", {
        "owner": "wshobson", "repo": "agents",
        "display_name": "wshobson/agents",
        "description": "Developer essentials; uses debugging-strategies sub-skill.",
        "eval_skill_path": "plugins/developer-essentials/skills/debugging-strategies",
    }),
    ("debugging_investigation", {
        "owner": "lllllllama", "repo": "ai-paper-reproduction-skill",
        "display_name": "lllllllama/ai-paper-reproduction-skill",
        "description": "Safe-debug workflow for reproducing research code, iterative fix loops.",
        "eval_skill_path": "skills/safe-debug",
    }),
    ("debugging_investigation", {
        "owner": "charon-fan", "repo": "agent-playbook",
        "display_name": "charon-fan/agent-playbook",
        "description": "Agent playbook; uses the debugger sub-skill for systematic investigation.",
        "eval_skill_path": "skills/debugger",
    }),

    # ═══════════════════════════════════════════════════════════════════
    # content_generation — create images, slides, docs, blog posts
    # ═══════════════════════════════════════════════════════════════════
    ("content_generation", {
        "owner": "anthropics", "repo": "skills",
        "display_name": "anthropics/skills",
        "description": "anthropics/skills pptx — create presentation decks programmatically.",
        "eval_skill_path": "skills/pptx",
    }),
    ("content_generation", {
        "owner": "jimliu", "repo": "baoyu-skills",
        "display_name": "jimliu/baoyu-skills",
        "description": "baoyu-slide-deck — generate slide decks with rich styling and layouts.",
        "eval_skill_path": "skills/baoyu-slide-deck",
    }),
    ("content_generation", {
        "owner": "pexoai", "repo": "pexo-skills",
        "display_name": "pexoai/pexo-skills",
        "description": "Pexo video + image studio for content generation.",
        "eval_skill_path": "skills/videoagent-image-studio",
    }),
    ("content_generation", {
        "owner": "google-labs-code", "repo": "stitch-skills",
        "display_name": "google-labs-code/stitch-skills",
        "description": "Remotion sub-skill for programmatic video content generation.",
        "eval_skill_path": "skills/remotion",
    }),
    ("content_generation", {
        "owner": "wshobson", "repo": "agents",
        "display_name": "wshobson/agents",
        "description": "Business analytics; uses kpi-dashboard-design for data storytelling.",
        "eval_skill_path": "plugins/business-analytics/skills/data-storytelling",
    }),

    # ═══════════════════════════════════════════════════════════════════
    # mobile_development — React Native, Expo, iOS/Android patterns
    # ═══════════════════════════════════════════════════════════════════
    ("mobile_development", {
        "owner": "expo", "repo": "skills",
        "display_name": "expo/skills",
        "description": "Expo — the full framework for building native mobile apps with React Native.",
        "eval_skill_path": "plugins/expo/skills/building-native-ui",
    }),
    ("mobile_development", {
        "owner": "vercel-labs", "repo": "agent-skills",
        "display_name": "vercel-labs/agent-skills",
        "description": "React Native skills from Vercel Labs — patterns and best practices.",
        "eval_skill_path": "skills/react-native-skills",
    }),
    ("mobile_development", {
        "owner": "wshobson", "repo": "agents",
        "display_name": "wshobson/agents",
        "description": "Frontend-mobile plugin; uses react-native-architecture sub-skill.",
        "eval_skill_path": "plugins/frontend-mobile-development/skills/react-native-architecture",
    }),
    ("mobile_development", {
        "owner": "pbakaus", "repo": "impeccable",
        "display_name": "pbakaus/impeccable",
        "description": "Impeccable design; uses adapt sub-skill for responsive/mobile layouts.",
        "eval_skill_path": ".agents/skills/adapt",
    }),

    # ═══════════════════════════════════════════════════════════════════
    # agent_orchestration — multi-agent workflow, sub-agent patterns
    # ═══════════════════════════════════════════════════════════════════
    ("agent_orchestration", {
        "owner": "obra", "repo": "superpowers",
        "display_name": "obra/superpowers",
        "description": "Dispatching parallel sub-agents for complex multi-step tasks.",
        "eval_skill_path": "skills/dispatching-parallel-agents",
    }),
    ("agent_orchestration", {
        "owner": "vercel-labs", "repo": "agent-browser",
        "display_name": "vercel-labs/agent-browser",
        "description": "Vercel agent browser — running agents with browser access and sandbox.",
        "eval_skill_path": "skills/agent-browser",
    }),
    ("agent_orchestration", {
        "owner": "anthropics", "repo": "skills",
        "display_name": "anthropics/skills",
        "description": "skill-creator — meta-skill for designing and packaging new agent skills.",
        "eval_skill_path": "skills/skill-creator",
    }),
    ("agent_orchestration", {
        "owner": "charon-fan", "repo": "agent-playbook",
        "display_name": "charon-fan/agent-playbook",
        "description": "long-task-coordinator — orchestrating multi-phase agent tasks.",
        "eval_skill_path": "skills/long-task-coordinator",
    }),
    ("agent_orchestration", {
        "owner": "wshobson", "repo": "agents",
        "display_name": "wshobson/agents",
        "description": "Agent teams — team composition and parallel feature development patterns.",
        "eval_skill_path": "plugins/agent-teams/skills/parallel-feature-development",
    }),
]


def fetch_skill_md(owner: str, repo: str, path: str) -> str:
    """Fetch SKILL.md over HTTPS. Tries main, then master."""
    for branch in ("main", "master"):
        url = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{path}/SKILL.md"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "skillrank-import"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.read().decode("utf-8")
        except Exception:
            continue
    raise RuntimeError(f"SKILL.md not found at either main or master: {owner}/{repo}/{path}")


async def wipe_catalog_intents(db):
    """Delete all catalog rows + related comparisons/eval_runs for the intents we're about to re-import."""
    intents = sorted({i for (i, _) in SKILL_CATALOG})
    if not intents:
        return
    placeholders = ",".join("?" for _ in intents)
    await db.execute(
        f"DELETE FROM comparisons WHERE intent IN ({placeholders})",
        intents,
    )
    await db.execute(
        f"DELETE FROM eval_runs WHERE skill_id IN (SELECT id FROM skills WHERE intent IN ({placeholders}))",
        intents,
    )
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
                skill_path=entry["eval_skill_path"],
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
