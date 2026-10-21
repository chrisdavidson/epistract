"""Headless-chromium checks of the standalone graph.html (compact layout, Filters)."""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from core import run_sift

NODE = shutil.which("node")
CHROMIUM = shutil.which("chromium") or shutil.which("chromium-browser")

pytestmark = [
    pytest.mark.unit,
    pytest.mark.skipif(NODE is None, reason="node not installed"),
    pytest.mark.skipif(CHROMIUM is None, reason="chromium not installed"),
]

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "tests" / "js" / "static_view_cdp.mjs"
GLP1 = ROOT / "tests" / "corpora" / "06_glp1_landscape" / "output-v3"
GLP1_FILES = ("graph_data.json", "communities.json", "claims_layer.json")


@pytest.fixture(scope="module")
def glp1_html(tmp_path_factory):
    work = tmp_path_factory.mktemp("glp1")
    for name in GLP1_FILES:
        shutil.copy2(GLP1 / name, work / name)
    run_sift.cmd_view(str(work), open_browser=False)
    return work / "graph.html"


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


def _run(port: int, url: str, mode: str, shots: Path | None = None) -> dict:
    cmd = [NODE, str(SCRIPT), str(port), url, mode]
    if shots is not None:
        cmd.append(str(shots))
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    assert lines, f"no output from CDP script: {proc.stderr[-500:]}"
    result = json.loads(lines[-1])
    assert "failed" in result, f"no result line: {lines[-5:]}"
    if result["failed"]:
        detail = [ln for ln in lines if '"ok":false' in ln]
        pytest.fail(f"failed checks {result['failed']}: {detail}")
    return result


def test_compact_layout_filters_tab_order_print_and_motion(chromium_port, glp1_html, tmp_path):
    shots = tmp_path / "shots"
    shots.mkdir()
    result = _run(chromium_port, glp1_html.as_uri(), "layout", shots)
    assert result["passed"] >= 20, result
