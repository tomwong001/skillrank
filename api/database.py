"""
SQLite database layer for SkillRank.
Handles schema creation, connection management, and all DB operations.
Uses aiosqlite for async FastAPI compatibility.
"""

import aiosqlite
import os
import json
from datetime import datetime, timezone
from typing import Optional

DB_PATH = os.environ.get("SKILLRANK_DB", os.path.join(os.path.dirname(__file__), "..", "skillrank.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS skills (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    repo_url TEXT NOT NULL,
    commit_sha TEXT NOT NULL,
    intent TEXT NOT NULL,
    description TEXT,
    author TEXT NOT NULL,
    rating REAL DEFAULT 1.0,
    rating_variance REAL DEFAULT 1.0,
    comparisons INTEGER DEFAULT 0,
    wins INTEGER DEFAULT 0,
    losses INTEGER DEFAULT 0,
    ties INTEGER DEFAULT 0,
    status TEXT DEFAULT 'active',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(repo_url, intent)
);

CREATE TABLE IF NOT EXISTS submissions (
    id TEXT PRIMARY KEY,
    repo_url TEXT NOT NULL,
    commit_sha TEXT NOT NULL,
    intent TEXT NOT NULL,
    description TEXT,
    author TEXT NOT NULL,
    status TEXT DEFAULT 'pending',
    skill_id TEXT,
    scorecard TEXT,
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (skill_id) REFERENCES skills(id)
);

CREATE TABLE IF NOT EXISTS comparisons (
    id TEXT PRIMARY KEY,
    intent TEXT NOT NULL,
    scenario_id TEXT NOT NULL,
    skill_a_id TEXT NOT NULL,
    skill_b_id TEXT NOT NULL,
    winner TEXT,
    judge_runs TEXT NOT NULL,
    verdict TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (skill_a_id) REFERENCES skills(id),
    FOREIGN KEY (skill_b_id) REFERENCES skills(id)
);

CREATE TABLE IF NOT EXISTS eval_runs (
    id TEXT PRIMARY KEY,
    submission_id TEXT NOT NULL,
    skill_id TEXT NOT NULL,
    scenario_id TEXT NOT NULL,
    output TEXT,
    stderr TEXT,
    exit_code INTEGER,
    duration_s REAL,
    status TEXT DEFAULT 'pending',
    created_at TEXT NOT NULL,
    FOREIGN KEY (submission_id) REFERENCES submissions(id),
    FOREIGN KEY (skill_id) REFERENCES skills(id)
);

CREATE TABLE IF NOT EXISTS scenarios (
    id TEXT PRIMARY KEY,
    intent TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT NOT NULL,
    repo_url TEXT NOT NULL,
    branch TEXT NOT NULL,
    task TEXT NOT NULL,
    expected_outcomes TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


async def get_db() -> aiosqlite.Connection:
    db = await aiosqlite.connect(DB_PATH)
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA foreign_keys=ON")
    return db


async def init_db():
    db = await get_db()
    try:
        await db.executescript(SCHEMA)
        await db.commit()
        await _migrate_v2(db)
    finally:
        await db.close()


async def _migrate_v2(db: aiosqlite.Connection):
    """
    v2 migration: add skill_path, skill_md_content, source columns.
    Purge ship_code legacy data.
    Idempotent via PRAGMA user_version.
    """
    cursor = await db.execute("PRAGMA user_version")
    row = await cursor.fetchone()
    current_version = row[0] if row else 0
    if current_version >= 2:
        return

    # Rebuild skills table with new columns and updated unique constraint
    await db.executescript("""
        CREATE TABLE IF NOT EXISTS skills_v2 (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            repo_url TEXT NOT NULL,
            skill_path TEXT NOT NULL DEFAULT '',
            commit_sha TEXT NOT NULL,
            intent TEXT NOT NULL,
            description TEXT,
            skill_md_content TEXT,
            source TEXT NOT NULL DEFAULT 'user_submit',
            author TEXT NOT NULL,
            rating REAL DEFAULT 1.0,
            rating_variance REAL DEFAULT 1.0,
            comparisons INTEGER DEFAULT 0,
            wins INTEGER DEFAULT 0,
            losses INTEGER DEFAULT 0,
            ties INTEGER DEFAULT 0,
            status TEXT DEFAULT 'active',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(repo_url, skill_path, intent)
        );

        INSERT OR IGNORE INTO skills_v2 (
            id, name, repo_url, skill_path, commit_sha, intent, description,
            skill_md_content, source, author, rating, rating_variance,
            comparisons, wins, losses, ties, status, created_at, updated_at
        )
        SELECT
            id, name, repo_url, '', commit_sha, intent, description,
            NULL, 'user_submit', author, rating, rating_variance,
            comparisons, wins, losses, ties, status, created_at, updated_at
        FROM skills
        WHERE intent != 'ship_code';

        DROP TABLE skills;
        ALTER TABLE skills_v2 RENAME TO skills;
    """)

    # Purge ship_code from related tables
    await db.execute("DELETE FROM submissions WHERE intent = 'ship_code'")
    await db.execute("DELETE FROM comparisons WHERE intent = 'ship_code'")
    await db.execute("DELETE FROM scenarios WHERE intent = 'ship_code'")
    await db.execute(
        "DELETE FROM eval_runs WHERE scenario_id LIKE 'ship_code_%'"
    )

    # Add skill_path to submissions table (ALTER is fine here — no unique constraint change)
    try:
        await db.execute(
            "ALTER TABLE submissions ADD COLUMN skill_path TEXT NOT NULL DEFAULT ''"
        )
    except Exception:
        pass  # Column may already exist if migration re-ran partially

    await db.execute("PRAGMA user_version = 2")
    await db.commit()


# ── Skills ──

async def create_skill(db: aiosqlite.Connection, skill_id: str, name: str,
                       repo_url: str, commit_sha: str, intent: str,
                       description: str, author: str,
                       skill_path: str = "",
                       skill_md_content: Optional[str] = None,
                       source: str = "user_submit") -> dict:
    now = datetime.now(timezone.utc).isoformat()
    await db.execute(
        """INSERT INTO skills (id, name, repo_url, skill_path, commit_sha, intent,
                               description, skill_md_content, source, author,
                               created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(repo_url, skill_path, intent) DO UPDATE SET
             commit_sha=excluded.commit_sha, name=excluded.name,
             description=excluded.description,
             skill_md_content=excluded.skill_md_content,
             updated_at=excluded.updated_at""",
        (skill_id, name, repo_url, skill_path, commit_sha, intent,
         description, skill_md_content, source, author, now, now)
    )
    await db.commit()
    return await get_skill(db, skill_id)


async def bulk_import_skill(db: aiosqlite.Connection, skill_id: str, name: str,
                             repo_url: str, skill_path: str, commit_sha: str,
                             intent: str, description: str, author: str,
                             skill_md_content: str) -> dict:
    """Import a skill from skills.sh (or similar directory) at baseline rating.
    Sets source='skills_sh_import'. No eval triggered — use bulk_eval later."""
    return await create_skill(
        db, skill_id, name, repo_url, commit_sha, intent, description, author,
        skill_path=skill_path,
        skill_md_content=skill_md_content,
        source="skills_sh_import",
    )


async def get_cached_skill_content(db: aiosqlite.Connection, skill_id: str) -> Optional[str]:
    """Return the cached SKILL.md content for a skill, if any."""
    cursor = await db.execute(
        "SELECT skill_md_content FROM skills WHERE id = ?", (skill_id,)
    )
    row = await cursor.fetchone()
    if row and row[0]:
        return row[0]
    return None


async def get_intents(db: aiosqlite.Connection) -> list[dict]:
    """Return distinct intents with skill counts."""
    cursor = await db.execute(
        "SELECT intent, COUNT(*) as count FROM skills WHERE status='active' GROUP BY intent ORDER BY count DESC"
    )
    rows = await cursor.fetchall()
    return [{"id": r["intent"], "count": r["count"]} for r in rows]


async def get_skill(db: aiosqlite.Connection, skill_id: str) -> Optional[dict]:
    cursor = await db.execute("SELECT * FROM skills WHERE id = ?", (skill_id,))
    row = await cursor.fetchone()
    return dict(row) if row else None


async def get_skills_by_intent(db: aiosqlite.Connection, intent: str) -> list[dict]:
    cursor = await db.execute(
        "SELECT * FROM skills WHERE intent = ? AND status = 'active' ORDER BY rating DESC",
        (intent,)
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def update_skill_rating(db: aiosqlite.Connection, skill_id: str,
                              rating: float, variance: float,
                              wins: int, losses: int, ties: int, comparisons: int):
    now = datetime.now(timezone.utc).isoformat()
    await db.execute(
        """UPDATE skills SET rating=?, rating_variance=?, wins=?, losses=?, ties=?,
           comparisons=?, updated_at=? WHERE id=?""",
        (rating, variance, wins, losses, ties, comparisons, now, skill_id)
    )
    await db.commit()


# ── Submissions ──

async def create_submission(db: aiosqlite.Connection, sub_id: str, repo_url: str,
                            commit_sha: str, intent: str, description: str,
                            author: str) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    await db.execute(
        """INSERT INTO submissions (id, repo_url, commit_sha, intent, description, author, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (sub_id, repo_url, commit_sha, intent, description, author, now, now)
    )
    await db.commit()
    return await get_submission(db, sub_id)


async def get_submission(db: aiosqlite.Connection, sub_id: str) -> Optional[dict]:
    cursor = await db.execute("SELECT * FROM submissions WHERE id = ?", (sub_id,))
    row = await cursor.fetchone()
    return dict(row) if row else None


async def update_submission(db: aiosqlite.Connection, sub_id: str, **kwargs):
    now = datetime.now(timezone.utc).isoformat()
    kwargs["updated_at"] = now
    sets = ", ".join(f"{k}=?" for k in kwargs)
    vals = list(kwargs.values()) + [sub_id]
    await db.execute(f"UPDATE submissions SET {sets} WHERE id=?", vals)
    await db.commit()


async def get_pending_submission(db: aiosqlite.Connection, repo_url: str, intent: str) -> Optional[dict]:
    """Check for in-progress eval to prevent duplicates."""
    cursor = await db.execute(
        "SELECT * FROM submissions WHERE repo_url=? AND intent=? AND status IN ('pending','evaluating')",
        (repo_url, intent)
    )
    row = await cursor.fetchone()
    return dict(row) if row else None


# ── Comparisons ──

async def create_comparison(db: aiosqlite.Connection, comp_id: str, intent: str,
                            scenario_id: str, skill_a_id: str, skill_b_id: str,
                            winner: Optional[str], judge_runs: list, verdict: str) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    await db.execute(
        """INSERT INTO comparisons (id, intent, scenario_id, skill_a_id, skill_b_id, winner, judge_runs, verdict, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (comp_id, intent, scenario_id, skill_a_id, skill_b_id, winner, json.dumps(judge_runs), verdict, now)
    )
    await db.commit()
    return {"id": comp_id, "verdict": verdict, "winner": winner}


# ── Eval runs ──

async def create_eval_run(db: aiosqlite.Connection, run_id: str, submission_id: str,
                          skill_id: str, scenario_id: str) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    await db.execute(
        """INSERT INTO eval_runs (id, submission_id, skill_id, scenario_id, created_at)
           VALUES (?, ?, ?, ?, ?)""",
        (run_id, submission_id, skill_id, scenario_id, now)
    )
    await db.commit()
    return {"id": run_id, "status": "pending"}


async def update_eval_run(db: aiosqlite.Connection, run_id: str, **kwargs):
    sets = ", ".join(f"{k}=?" for k in kwargs)
    vals = list(kwargs.values()) + [run_id]
    await db.execute(f"UPDATE eval_runs SET {sets} WHERE id=?", vals)
    await db.commit()


# ── Scenarios ──

async def get_scenarios_by_intent(db: aiosqlite.Connection, intent: str) -> list[dict]:
    cursor = await db.execute("SELECT * FROM scenarios WHERE intent = ?", (intent,))
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def create_scenario(db: aiosqlite.Connection, scenario: dict):
    await db.execute(
        """INSERT OR IGNORE INTO scenarios (id, intent, name, description, repo_url, branch, task, expected_outcomes, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (scenario["id"], scenario["intent"], scenario["name"], scenario["description"],
         scenario["repo_url"], scenario["branch"], scenario["task"],
         json.dumps(scenario["expected_outcomes"]), datetime.now(timezone.utc).isoformat())
    )
    await db.commit()
