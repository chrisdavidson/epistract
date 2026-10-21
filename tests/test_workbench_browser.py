"""Headless-chromium click-through of the live workbench Dashboard on the GLP-1 graph."""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

NODE = shutil.which("node")
CHROMIUM = shutil.which("chromium") or shutil.which("chromium-browser")

pytestmark = [
    pytest.mark.unit,
    pytest.mark.skipif(NODE is None, reason="node not installed"),
    pytest.mark.skipif(CHROMIUM is None, reason="chromium not installed"),
]

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "tests" / "js" / "workbench_dashboard_cdp.mjs"
GLP1 = ROOT / "tests" / "corpora" / "06_glp1_landscape" / "output-v3"
GLP1_FILES = ("graph_data.json", "communities.json", "claims_layer.json")


@pytest.fixture(scope="module")
def workbench_url(tmp_path_factory):
    pytest.importorskip("uvicorn")
    work = tmp_path_factory.mktemp("glp1-wb")
    for name in GLP1_FILES:
        shutil.copy2(GLP1 / name, work / name)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    proc = subprocess.Popen(
        [
            sys.executable,
            str(ROOT / "scripts" / "launch_workbench.py"),
            str(work),
            "--port",
            str(port),
            "--host",
            "127.0.0.1",
        ],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        url = f"http://127.0.0.1:{port}"
        deadline = time.time() + 30
        up = False
        while time.time() < deadline and not up:
            if proc.poll() is not None:
                pytest.skip("workbench server exited before answering")
            try:
                with urllib.request.urlopen(f"{url}/api/template", timeout=1) as resp:
                    up = resp.status == 200
            except OSError:
                time.sleep(0.3)
        if not up:
            pytest.skip("workbench server did not answer in time")
        yield url + "/"
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


@pytest.fixture(scope="module")
def chromium_port(tmp_path_factory):
    profile = tmp_path_factory.mktemp("chromium-profile")
    proc = subprocess.Popen(
        [
            CHROMIUM,
            "--headless=new",
            "--no-sandbox",
            "--disable-gpu",
            "--remote-debugging-port=0",
            f"--user-data-dir={profile}",
            "about:blank",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        port_file = profile / "DevToolsActivePort"
        deadline = time.time() + 30
        while time.time() < deadline and not port_file.exists():
            if proc.poll() is not None:
                pytest.skip("chromium exited before opening a debugging port")
            time.sleep(0.2)
        if not port_file.exists():
            pytest.skip("chromium did not open a debugging port")
        yield int(port_file.read_text().splitlines()[0])
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


def _run(port: int, url: str, mode: str) -> dict:
    cmd = [NODE, str(SCRIPT), str(port), url, mode]
    shots = os.environ.get("EPISTRACT_SHOTS_DIR")
    if shots:
        Path(shots).mkdir(parents=True, exist_ok=True)
        cmd.append(shots)
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    assert lines, f"no output from CDP script: {proc.stderr[-500:]}"
    result = json.loads(lines[-1])
    assert "failed" in result, f"no result line: {lines[-5:]}"
    if result["failed"]:
        detail = [ln for ln in lines if '"ok":false' in ln]
        pytest.fail(f"failed checks {result['failed']}: {detail}")
    return result


def test_dashboard_click_through_glp1(chromium_port, workbench_url):
    result = _run(chromium_port, workbench_url, "click")
    assert result["passed"] >= 20, result


def test_dashboard_click_before_graph_ready(chromium_port, workbench_url):
    result = _run(chromium_port, workbench_url, "early")
    assert result["passed"] >= 4, result
