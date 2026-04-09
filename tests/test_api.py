"""Tests for SkillRank API endpoints."""

import pytest
import pytest_asyncio
import os
import tempfile

# Use temp DB for tests
_test_db = tempfile.mktemp(suffix=".db")
os.environ["SKILLRANK_DB"] = _test_db

from httpx import AsyncClient, ASGITransport
from api.main import app
from api.database import init_db, get_db, create_skill


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    """Fresh DB for each test."""
    os.environ["SKILLRANK_DB"] = tempfile.mktemp(suffix=".db")
    from api import database
    database.DB_PATH = os.environ["SKILLRANK_DB"]
    await init_db()
    yield
    try:
        os.unlink(os.environ["SKILLRANK_DB"])
    except Exception:
        pass


@pytest.fixture
def client():
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


@pytest.mark.asyncio
async def test_health(client):
    resp = await client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"


@pytest.mark.asyncio
async def test_skills_empty(client):
    resp = await client.get("/api/skills?intent=ship_code")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 0
    assert data["skills"] == []
    assert "message" in data


@pytest.mark.asyncio
async def test_skills_with_data(client):
    db = await get_db()
    try:
        await create_skill(db, "test/skill-1", "skill-1",
                           "https://github.com/test/skill-1", "abc123",
                           "ship_code", "A test skill", "testuser")
    finally:
        await db.close()

    resp = await client.get("/api/skills?intent=ship_code")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["skills"][0]["skill_id"] == "test/skill-1"
    assert data["skills"][0]["rank"] == 1


@pytest.mark.asyncio
async def test_submit_no_pat(client):
    """Should reject submission without valid PAT."""
    resp = await client.post("/api/submit", json={
        "repo_url": "https://github.com/test/nonexistent",
        "intent": "ship_code",
        "github_pat": "ghp_invalid",
    })
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_submission_not_found(client):
    resp = await client.get("/api/submit/nonexistent")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_dashboard_pages(client):
    """Dashboard HTML pages should return 200."""
    resp = await client.get("/")
    assert resp.status_code == 200
    assert "SkillRank" in resp.text

    resp = await client.get("/submit")
    assert resp.status_code == 200
    assert "Submit" in resp.text


@pytest.mark.asyncio
async def test_scorecard_page(client):
    resp = await client.get("/skill/test/skill-1")
    assert resp.status_code == 200
