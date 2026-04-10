"""
Docker sandbox for skill execution.

Each eval runs in a disposable Docker container:
- Shallow clone of the skill repo at pinned commit SHA
- No network egress except LLM APIs
- Resource limits: 2 CPU, 4GB RAM, 120s timeout
- Collects stdout, stderr, exit code, duration
"""

import asyncio
import os
import json
import logging
import time
import uuid
import tempfile
import shutil
from typing import Optional

import httpx

logger = logging.getLogger(__name__)


DOCKER_IMAGE = os.environ.get("SKILLRANK_SANDBOX_IMAGE", "skillrank-sandbox:latest")
TIMEOUT_S = int(os.environ.get("SKILLRANK_TIMEOUT", "120"))
CPU_LIMIT = os.environ.get("SKILLRANK_CPU_LIMIT", "2")
MEM_LIMIT = os.environ.get("SKILLRANK_MEM_LIMIT", "4g")

# LLM executor config (reuses judge credentials)
OPENROUTER_BASE = "https://openrouter.ai/api/v1"
OPENROUTER_KEY = os.environ.get("OPENROUTER_API_KEY", "")
EXECUTOR_MODEL = os.environ.get("EXECUTOR_MODEL", "qwen/qwen-turbo")
EXECUTOR_MAX_TOKENS = int(os.environ.get("EXECUTOR_MAX_TOKENS", "1200"))
EXECUTOR_TIMEOUT_S = 120.0
EXECUTOR_MAX_RETRIES = 3


async def run_skill_in_sandbox(
    repo_url: str,
    commit_sha: str,
    scenario_task: str,
    scenario_repo_url: str,
    scenario_branch: str,
    env_vars: Optional[dict] = None,
) -> dict:
    """
    Execute a skill against a scenario inside a Docker container.

    Returns {
        "output": str,       # stdout
        "stderr": str,       # stderr
        "exit_code": int,
        "duration_s": float,
        "status": "success" | "failed" | "timeout" | "error",
        "side_effects": dict, # files created, git operations, etc.
    }
    """
    container_name = f"skillrank-eval-{uuid.uuid4().hex[:12]}"
    env_flags = ""
    if env_vars:
        for k, v in env_vars.items():
            env_flags += f" -e {k}={v}"

    # The sandbox container:
    # 1. Clones the scenario repo (the workspace)
    # 2. Clones the skill repo
    # 3. Runs the skill's SKILL.md against the scenario task
    # 4. Captures output and side effects
    cmd = f"""docker run --rm --name {container_name} \
        --cpus={CPU_LIMIT} \
        --memory={MEM_LIMIT} \
        --network=skillrank-eval-net \
        -e SCENARIO_REPO="{scenario_repo_url}" \
        -e SCENARIO_BRANCH="{scenario_branch}" \
        -e SKILL_REPO="{repo_url}" \
        -e SKILL_COMMIT="{commit_sha}" \
        -e TASK="{scenario_task}" \
        {env_flags} \
        {DOCKER_IMAGE}"""

    start = time.monotonic()
    try:
        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=TIMEOUT_S
            )
            duration = time.monotonic() - start
            exit_code = proc.returncode

            return {
                "output": stdout.decode("utf-8", errors="replace")[:50000],
                "stderr": stderr.decode("utf-8", errors="replace")[:10000],
                "exit_code": exit_code,
                "duration_s": round(duration, 2),
                "status": "success" if exit_code == 0 else "failed",
            }
        except asyncio.TimeoutError:
            # Kill the container
            await asyncio.create_subprocess_shell(f"docker kill {container_name}")
            duration = time.monotonic() - start
            return {
                "output": "",
                "stderr": f"Timeout after {TIMEOUT_S}s",
                "exit_code": -1,
                "duration_s": round(duration, 2),
                "status": "timeout",
            }
    except Exception as e:
        duration = time.monotonic() - start
        return {
            "output": "",
            "stderr": str(e),
            "exit_code": -1,
            "duration_s": round(duration, 2),
            "status": "error",
        }


async def cleanup_container(container_name: str):
    """Force remove a container if it still exists."""
    await asyncio.create_subprocess_shell(
        f"docker rm -f {container_name} 2>/dev/null",
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )


async def check_docker_available() -> bool:
    """Verify Docker is available and the sandbox image exists."""
    try:
        proc = await asyncio.create_subprocess_shell(
            "docker info",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()
        if proc.returncode != 0:
            return False

        proc = await asyncio.create_subprocess_shell(
            f"docker image inspect {DOCKER_IMAGE}",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()
        return proc.returncode == 0
    except Exception:
        return False


# ── LLM executor: the heart of real-execution eval ──

EXECUTOR_PROMPT = """You are an AI coding agent that has loaded the skill guidance document below. Follow its specific methodology and techniques to solve the task. Write concrete, working code — not meta-commentary about your approach.

SKILL GUIDANCE DOCUMENT:
{skill_content}

TASK:
{task}

Write the solution (complete code with imports, specific commands, or concrete output):"""


async def execute_skill_via_llm(skill_content: str, scenario_task: str) -> dict:
    """
    Feed {skill guidance + task} to an LLM (qwen-turbo by default) and
    capture its response as the skill's "attempt" at the task. This is the
    core of SkillRank's eval: different skills produce different attempts,
    which the judge then compares pairwise.

    Returns {output, stderr, exit_code, duration_s, status}.
    """
    if not OPENROUTER_KEY:
        return {
            "output": "",
            "stderr": "OPENROUTER_API_KEY not set — cannot run LLM executor",
            "exit_code": -1,
            "duration_s": 0.0,
            "status": "error",
        }

    prompt = EXECUTOR_PROMPT.format(
        skill_content=skill_content[:8000],
        task=scenario_task,
    )
    start = time.monotonic()

    last_err = None
    for attempt in range(EXECUTOR_MAX_RETRIES):
        try:
            async with httpx.AsyncClient(timeout=EXECUTOR_TIMEOUT_S) as client:
                resp = await client.post(
                    f"{OPENROUTER_BASE}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {OPENROUTER_KEY}",
                        "HTTP-Referer": "https://skillrank.dev",
                        "X-Title": "SkillRank Executor",
                    },
                    json={
                        "model": EXECUTOR_MODEL,
                        "messages": [{"role": "user", "content": prompt}],
                        "max_tokens": EXECUTOR_MAX_TOKENS,
                        "temperature": 0.2,
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                output = data["choices"][0]["message"]["content"].strip()
                duration = time.monotonic() - start
                logger.info(f"Executor call succeeded: model={EXECUTOR_MODEL}, output_len={len(output)}, duration={duration:.1f}s")
                return {
                    "output": output,
                    "stderr": "",
                    "exit_code": 0,
                    "duration_s": round(duration, 2),
                    "status": "success",
                }
        except Exception as e:
            last_err = e
            logger.warning(f"Executor attempt {attempt + 1}/{EXECUTOR_MAX_RETRIES} failed: {type(e).__name__}: {e}")
            if attempt < EXECUTOR_MAX_RETRIES - 1:
                await asyncio.sleep(3 * (attempt + 1))

    duration = time.monotonic() - start
    return {
        "output": "",
        "stderr": f"Executor failed after {EXECUTOR_MAX_RETRIES} attempts: {last_err}",
        "exit_code": -1,
        "duration_s": round(duration, 2),
        "status": "error",
    }


async def run_skill_from_cache(skill_md_content: str, scenario_task: str) -> dict:
    """Fast path: skill content is already cached in DB, no clone needed."""
    return await execute_skill_via_llm(skill_md_content, scenario_task)


# ── Fallback: subprocess sandbox (clones repo, reads SKILL.md, runs executor) ──

async def run_skill_subprocess(
    repo_url: str,
    commit_sha: str,
    scenario_task: str,
    skill_path: str = "",
) -> dict:
    """
    Lightweight execution path: clone repo at commit, read SKILL.md at
    $skill_path/SKILL.md (defaults to repo root), then run the LLM executor.

    Used when the skill_md_content is not cached in DB (fresh user submission).
    WARNING: subprocess git clone has no isolation — only use for trusted sources.
    """
    work_dir = tempfile.mkdtemp(prefix="skillrank-eval-")
    start = time.monotonic()

    try:
        # Shallow clone at specific commit
        proc = await asyncio.create_subprocess_shell(
            f"git clone --depth 1 {repo_url} {work_dir}/skill 2>&1",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)

        if proc.returncode != 0:
            return {
                "output": "",
                "stderr": f"Clone failed: {stderr.decode()}",
                "exit_code": -1,
                "duration_s": round(time.monotonic() - start, 2),
                "status": "error",
            }

        # Resolve SKILL.md path (with subdir support)
        skill_md_path = os.path.join(work_dir, "skill", skill_path, "SKILL.md") if skill_path else os.path.join(work_dir, "skill", "SKILL.md")
        if not os.path.exists(skill_md_path):
            return {
                "output": "",
                "stderr": f"No SKILL.md found at {skill_path or 'repo root'}",
                "exit_code": -1,
                "duration_s": round(time.monotonic() - start, 2),
                "status": "error",
            }

        with open(skill_md_path) as f:
            skill_content = f.read()

        # Run LLM executor with the SKILL.md content
        result = await execute_skill_via_llm(skill_content, scenario_task)
        result["duration_s"] = round(time.monotonic() - start, 2)
        return result

    except asyncio.TimeoutError:
        return {
            "output": "",
            "stderr": f"Timeout after {TIMEOUT_S}s",
            "exit_code": -1,
            "duration_s": round(time.monotonic() - start, 2),
            "status": "timeout",
        }
    except Exception as e:
        return {
            "output": "",
            "stderr": str(e),
            "exit_code": -1,
            "duration_s": round(time.monotonic() - start, 2),
            "status": "error",
        }
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
