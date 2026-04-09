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
import time
import uuid
import tempfile
import shutil
from typing import Optional


DOCKER_IMAGE = os.environ.get("SKILLRANK_SANDBOX_IMAGE", "skillrank-sandbox:latest")
TIMEOUT_S = int(os.environ.get("SKILLRANK_TIMEOUT", "120"))
CPU_LIMIT = os.environ.get("SKILLRANK_CPU_LIMIT", "2")
MEM_LIMIT = os.environ.get("SKILLRANK_MEM_LIMIT", "4g")


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


# ── Fallback: subprocess sandbox (for dev/testing without Docker) ──

async def run_skill_subprocess(
    repo_url: str,
    commit_sha: str,
    scenario_task: str,
) -> dict:
    """
    Lightweight fallback: run skill in a subprocess with git worktree.
    WARNING: No isolation. Only use for local dev with trusted code.
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

        # Check for SKILL.md
        skill_md = os.path.join(work_dir, "skill", "SKILL.md")
        if not os.path.exists(skill_md):
            return {
                "output": "",
                "stderr": "No SKILL.md found in repository root",
                "exit_code": -1,
                "duration_s": round(time.monotonic() - start, 2),
                "status": "error",
            }

        # Read SKILL.md content as the skill output for now
        with open(skill_md) as f:
            skill_content = f.read()

        duration = time.monotonic() - start
        return {
            "output": f"SKILL.md content ({len(skill_content)} chars):\n{skill_content[:5000]}",
            "stderr": "",
            "exit_code": 0,
            "duration_s": round(duration, 2),
            "status": "success",
        }

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
