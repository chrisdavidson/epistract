#!/usr/bin/env python3
"""Standalone runner for the workbench browser check (Phase 08 gap closure).

Boots the workbench server on port 8045 with a synthetic ANTHROPIC_API_KEY,
runs tests/test_workbench_browser.py via pytest, then tears the server down.

Usage:
    python3 scripts/run_workbench_browser_check.py
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

PORT = 8045
HOST = "127.0.0.1"
HEALTH_URL = f"http://{HOST}:{PORT}/api/health"
ROOT_URL = f"http://{HOST}:{PORT}/"
PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = "tests/corpora/09_arxiv_cs/output"
DOMAIN = "arxiv-cs"
BOOT_TIMEOUT = 30  # seconds to wait for /api/health
TEARDOWN_GRACE = 5  # seconds before SIGKILL


def _port_in_use() -> bool:
    """Return True if the port is already responding."""
    try:
        with urllib.request.urlopen(ROOT_URL, timeout=2):
            return True
    except Exception:
        return False


def _wait_for_health(timeout: int) -> bool:
    """Poll /api/health until it returns 200 or timeout expires."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(HEALTH_URL, timeout=2) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(1)
    return False


def _teardown(proc: subprocess.Popen) -> None:  # type: ignore[type-arg]
    """Gracefully terminate the server process."""
    if proc.poll() is not None:
        return  # already exited
    print(f"Tearing down server (pid {proc.pid})...")
    proc.terminate()
    try:
        proc.wait(timeout=TEARDOWN_GRACE)
    except subprocess.TimeoutExpired:
        print("Grace period expired — sending SIGKILL")
        proc.kill()
        proc.wait()
    print("Server stopped.")


def main() -> int:
    # Step 1: check port is free
    if _port_in_use():
        print(
            f"ERROR: port {PORT} is already in use. "
            "Kill the existing process and retry.",
            file=sys.stderr,
        )
        return 2

    # Step 2: build child environment
    env = os.environ.copy()
    env["ANTHROPIC_API_KEY"] = "sk-test"
    # Strip conflicting provider keys so /api/models returns only 'anthropic'
    for k in ("AZURE_FOUNDRY_API_KEY", "ANTHROPIC_FOUNDRY_API_KEY", "OPENROUTER_API_KEY"):
        env.pop(k, None)

    # Step 3: launch server
    cmd = [
        sys.executable,
        "scripts/launch_workbench.py",
        OUTPUT_DIR,
        "--domain",
        DOMAIN,
        "--port",
        str(PORT),
        "--host",
        HOST,
    ]
    print(f"Starting workbench: {' '.join(cmd)}")
    proc = subprocess.Popen(
        cmd,
        cwd=str(PROJECT_ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )

    result = None
    try:
        # Step 4: wait for /api/health
        print(f"Waiting up to {BOOT_TIMEOUT}s for {HEALTH_URL}...")
        if not _wait_for_health(BOOT_TIMEOUT):
            # Drain output for diagnostics
            out, _ = proc.communicate(timeout=3)
            tail = (out or b"").decode(errors="replace")[-2000:]
            print(
                f"ERROR: server did not become healthy within {BOOT_TIMEOUT}s.\n"
                f"--- server output (tail) ---\n{tail}",
                file=sys.stderr,
            )
            return 3

        print("Server is up. Running browser check...")

        # Step 5: run pytest
        pytest_cmd = [
            sys.executable,
            "-m",
            "pytest",
            "tests/test_workbench_browser.py",
            "-v",
            "--no-header",
            "-p",
            "no:cacheprovider",
        ]
        result = subprocess.run(pytest_cmd, cwd=str(PROJECT_ROOT))

    finally:
        _teardown(proc)

    return result.returncode if result is not None else 1


if __name__ == "__main__":
    sys.exit(main())
