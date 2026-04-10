"""
SkillRank API — FastAPI application.

Endpoints:
  POST /api/submit          Submit a skill for evaluation
  GET  /api/submit/{id}     Check eval status + scorecard
  GET  /api/skills          List ranked skills by intent
  GET  /api/health          Health check

Dashboard (HTML):
  GET  /                    Leaderboard
  GET  /submit              Submission form
  GET  /skill/{id}          Scorecard view
"""

import os
import uuid
import json
import logging
import httpx
from contextlib import asynccontextmanager

logging.basicConfig(level=logging.INFO)

from fastapi import FastAPI, BackgroundTasks, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, HttpUrl
from typing import Optional

from api.database import (
    init_db, get_db, create_submission, get_submission, get_pending_submission,
    get_skills_by_intent, get_skill, get_intents
)


# ── Lifespan ──

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    await _seed_scenarios()
    yield


app = FastAPI(
    title="SkillRank",
    description="Category-specific eval infrastructure for agent skill selection",
    version="0.1.0",
    lifespan=lifespan,
)


# ── Models ──

class SubmitRequest(BaseModel):
    repo_url: str
    intent: str
    description: Optional[str] = None
    github_pat: str
    skill_path: str = ""  # subdirectory within repo (e.g. "skills/frontend-design")


class SubmitResponse(BaseModel):
    submission_id: str
    status: str
    message: str


# ── GitHub PAT verification ──

async def verify_github_pat(pat: str, repo_url: str) -> tuple[bool, str]:
    """Verify the PAT has access to the repo. Returns (ok, username)."""
    # Extract owner/repo from URL
    parts = repo_url.rstrip("/").split("/")
    if len(parts) < 2:
        return False, ""
    owner, repo = parts[-2], parts[-1]

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            # Check user identity
            user_resp = await client.get(
                "https://api.github.com/user",
                headers={"Authorization": f"Bearer {pat}", "Accept": "application/vnd.github+json"},
            )
            if user_resp.status_code != 200:
                return False, ""
            username = user_resp.json().get("login", "")

            # Check repo access
            repo_resp = await client.get(
                f"https://api.github.com/repos/{owner}/{repo}",
                headers={"Authorization": f"Bearer {pat}", "Accept": "application/vnd.github+json"},
            )
            if repo_resp.status_code != 200:
                return False, username

            # Get HEAD commit SHA
            return True, username
    except Exception:
        return False, ""


async def get_head_sha(repo_url: str, pat: str) -> Optional[str]:
    """Get the HEAD commit SHA for a repo."""
    parts = repo_url.rstrip("/").split("/")
    owner, repo = parts[-2], parts[-1]
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"https://api.github.com/repos/{owner}/{repo}/commits/HEAD",
                headers={"Authorization": f"Bearer {pat}", "Accept": "application/vnd.github+json"},
            )
            if resp.status_code == 200:
                return resp.json().get("sha", "")[:12]
    except Exception:
        pass
    return None


# ── API Endpoints ──

@app.post("/api/submit", response_model=SubmitResponse)
async def submit_skill(req: SubmitRequest, background_tasks: BackgroundTasks):
    """Submit a skill for evaluation."""
    db = await get_db()
    try:
        # Verify PAT
        ok, username = await verify_github_pat(req.github_pat, req.repo_url)
        if not ok:
            raise HTTPException(status_code=401, detail="Invalid GitHub PAT or no access to repo")

        # Dedup check
        pending = await get_pending_submission(db, req.repo_url, req.intent)
        if pending:
            raise HTTPException(status_code=409, detail={
                "message": "Evaluation already in progress for this repo + intent",
                "submission_id": pending["id"],
            })

        # Pin commit SHA
        commit_sha = await get_head_sha(req.repo_url, req.github_pat)
        if not commit_sha:
            raise HTTPException(status_code=422, detail="Could not resolve HEAD commit for repo")

        # Create submission
        sub_id = uuid.uuid4().hex[:16]
        await create_submission(db, sub_id, req.repo_url, commit_sha, req.intent,
                                req.description or "", username)

        # Launch eval in background
        from eval.engine import run_full_eval
        background_tasks.add_task(run_full_eval, sub_id, req.repo_url, commit_sha,
                                  req.intent, req.description or "", username,
                                  req.skill_path)

        return SubmitResponse(
            submission_id=sub_id,
            status="evaluating",
            message=f"Eval started for {req.repo_url} @ {commit_sha}",
        )
    finally:
        await db.close()


@app.get("/api/submit/{submission_id}")
async def get_submission_status(submission_id: str):
    """Check evaluation status and scorecard."""
    db = await get_db()
    try:
        sub = await get_submission(db, submission_id)
        if not sub:
            raise HTTPException(status_code=404, detail="Submission not found")

        result = {
            "submission_id": sub["id"],
            "status": sub["status"],
            "repo_url": sub["repo_url"],
            "commit_sha": sub["commit_sha"],
            "intent": sub["intent"],
            "author": sub["author"],
            "created_at": sub["created_at"],
        }

        if sub["status"] == "complete" and sub["scorecard"]:
            result["scorecard"] = json.loads(sub["scorecard"])
        if sub["status"] == "error" and sub["error"]:
            result["error"] = sub["error"]

        return result
    finally:
        await db.close()


@app.get("/api/skills")
async def list_skills(intent: str = "ship_code"):
    """List ranked skills for an intent."""
    db = await get_db()
    try:
        skills = await get_skills_by_intent(db, intent)
        if not skills:
            return {
                "skills": [],
                "intent": intent,
                "total": 0,
                "message": "No skills evaluated for this intent yet. Submit one?",
            }

        ranked = []
        for i, s in enumerate(skills):
            ranked.append({
                "rank": i + 1,
                "skill_id": s["id"],
                "name": s["name"],
                "author": s["author"],
                "rating": round(s["rating"], 3),
                "rating_variance": round(s["rating_variance"], 4),
                "confidence_95": round(1.96 * (s["rating_variance"] ** 0.5), 3),
                "win_rate": round(
                    (s["wins"] + 0.5 * s["ties"]) / max(1, s["wins"] + s["losses"] + s["ties"]),
                    3
                ),
                "comparisons": s["comparisons"],
                "trusted": s["comparisons"] >= 10,
                "repo_url": s["repo_url"],
                "commit_sha": s["commit_sha"],
                "updated_at": s["updated_at"],
            })

        return {
            "skills": ranked,
            "intent": intent,
            "total": len(ranked),
            "ranked_by": "bradley_terry",
        }
    finally:
        await db.close()


INTENT_DESCRIPTIONS = {
    "react_component_design": "Building React/UI components with modern tooling (shadcn, Tailwind, TypeScript)",
    "ship_code": "Shipping code to production (PRs, tests, deploys)",
    # Add more as new intents are introduced
}


@app.get("/api/intents")
async def list_intents():
    """Return distinct intents with their skill counts and descriptions."""
    db = await get_db()
    try:
        intents = await get_intents(db)
        return {
            "intents": [
                {
                    "id": i["id"],
                    "count": i["count"],
                    "description": INTENT_DESCRIPTIONS.get(i["id"], ""),
                }
                for i in intents
            ],
            "total": len(intents),
        }
    finally:
        await db.close()


@app.get("/api/health")
async def health():
    return {"status": "ok", "version": "0.1.0"}


# ── Dashboard HTML routes ──

DASHBOARD_DIR = os.path.join(os.path.dirname(__file__), "..", "dashboard")


@app.get("/", response_class=HTMLResponse)
async def dashboard_home():
    index_path = os.path.join(DASHBOARD_DIR, "index.html")
    if os.path.exists(index_path):
        with open(index_path) as f:
            return f.read()
    return "<h1>SkillRank</h1><p>Dashboard not built yet.</p>"


@app.get("/submit", response_class=HTMLResponse)
async def dashboard_submit():
    submit_path = os.path.join(DASHBOARD_DIR, "submit.html")
    if os.path.exists(submit_path):
        with open(submit_path) as f:
            return f.read()
    return "<h1>Submit a Skill</h1><p>Form not built yet.</p>"


@app.get("/skill/{skill_id:path}", response_class=HTMLResponse)
async def dashboard_scorecard(skill_id: str):
    scorecard_path = os.path.join(DASHBOARD_DIR, "scorecard.html")
    if os.path.exists(scorecard_path):
        with open(scorecard_path) as f:
            return f.read()
    return f"<h1>Scorecard: {skill_id}</h1><p>Not built yet.</p>"


# ── Seed scenarios on startup ──

async def _seed_scenarios():
    """Load scenarios from scenarios/ directory into DB."""
    from api.database import create_scenario, get_scenarios_by_intent
    db = await get_db()
    try:
        scenarios_dir = os.path.join(os.path.dirname(__file__), "..", "scenarios")
        if not os.path.exists(scenarios_dir):
            return

        for fname in os.listdir(scenarios_dir):
            if fname.endswith(".json"):
                with open(os.path.join(scenarios_dir, fname)) as f:
                    scenario = json.load(f)
                await create_scenario(db, scenario)
    finally:
        await db.close()


# ── Run ──

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api.main:app", host="0.0.0.0", port=8000, reload=True)
