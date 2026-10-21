"""Headless-chromium checks of the live workbench Dashboard: entity click-through and
the Epistemic health section on the GLP-1 v3 graph and the legacy PICALM graph."""

from __future__ import annotations

import contextlib
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
PICALM = ROOT / "tests" / "corpora" / "01_picalm_alzheimers" / "output"
FDA = ROOT / "tests" / "corpora" / "08_fda_labels" / "output"
GLP1_FILES = ("graph_data.json", "communities.json", "claims_layer.json")


def _log_tail(path: Path, limit: int = 2000) -> str:
    """Return the end of a captured process log for a failure message."""
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return "(no log captured)"
    return text[-limit:] or "(log is empty)"


@contextlib.contextmanager
def _serve(tmp_path_factory, corpus: Path, name: str):
    """Serve a copy of `corpus` with the workbench on an ephemeral loopback port."""
    pytest.importorskip("uvicorn")
    work = tmp_path_factory.mktemp(name)
    for fname in GLP1_FILES:
        shutil.copy2(corpus / fname, work / fname)
    # The Documents table needs the ingested texts; triage.json keeps the original
    # file names (taken from the recorded paths' names; nothing depends on the cwd).
    if (corpus / "ingested").is_dir():
        shutil.copytree(corpus / "ingested", work / "ingested")
    if (corpus / "triage.json").is_file():
        shutil.copy2(corpus / "triage.json", work / "triage.json")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    # The tools are present (skipif/importorskip above), so a server that does
    # not come up is a regression: fail with its log rather than skip.
    log_path = work / "server.log"
    log = log_path.open("w")
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
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    try:
        url = f"http://127.0.0.1:{port}"
        deadline = time.time() + 30
        up = False
        while time.time() < deadline and not up:
            if proc.poll() is not None:
                pytest.fail(
                    f"workbench server exited (code {proc.returncode}) before answering:\n"
                    f"{_log_tail(log_path)}"
                )
            try:
                with urllib.request.urlopen(f"{url}/api/template", timeout=1) as resp:
                    up = resp.status == 200
            except OSError:
                time.sleep(0.3)
        if not up:
            pytest.fail(f"workbench server did not answer in time:\n{_log_tail(log_path)}")
        yield url + "/"
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        log.close()


@pytest.fixture(scope="module")
def workbench_url(tmp_path_factory):
    with _serve(tmp_path_factory, GLP1, "glp1-wb") as url:
        yield url


@pytest.fixture(scope="module")
def picalm_workbench_url(tmp_path_factory):
    with _serve(tmp_path_factory, PICALM, "picalm-wb") as url:
        yield url


@pytest.fixture(scope="module")
def fda_workbench_url(tmp_path_factory):
    with _serve(tmp_path_factory, FDA, "fda-wb") as url:
        yield url


@pytest.fixture(scope="module")
def chromium_port(tmp_path_factory):
    profile = tmp_path_factory.mktemp("chromium-profile")
    log_path = tmp_path_factory.mktemp("chromium-log") / "chromium.log"
    log = log_path.open("w")
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
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    try:
        port_file = profile / "DevToolsActivePort"
        deadline = time.time() + 30
        while time.time() < deadline and not port_file.exists():
            if proc.poll() is not None:
                pytest.fail(
                    f"chromium exited (code {proc.returncode}) before opening a debugging "
                    f"port:\n{_log_tail(log_path)}"
                )
            time.sleep(0.2)
        if not port_file.exists():
            pytest.fail(f"chromium did not open a debugging port:\n{_log_tail(log_path)}")
        yield int(port_file.read_text().splitlines()[0])
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        log.close()


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
    if result.get("skipped"):
        pytest.skip(result["skipped"])
    if result["failed"]:
        detail = [ln for ln in lines if '"ok":false' in ln]
        pytest.fail(f"failed checks {result['failed']}: {detail}")
    return result


def test_dashboard_click_through_glp1(chromium_port, workbench_url):
    result = _run(chromium_port, workbench_url, "click")
    assert result["passed"] >= 20, result


def test_dashboard_click_before_graph_ready(chromium_port, workbench_url):
    result = _run(chromium_port, workbench_url, "early")
    assert result["passed"] >= 8, result


def test_dashboard_epistemic_glp1(chromium_port, workbench_url):
    result = _run(chromium_port, workbench_url, "epistemic")
    assert result["passed"] >= 34, result


def test_dashboard_epistemic_before_graph_ready(chromium_port, workbench_url):
    result = _run(chromium_port, workbench_url, "epistemic-early")
    assert result["passed"] >= 7, result


def test_dashboard_epistemic_legacy_picalm(chromium_port, picalm_workbench_url):
    result = _run(chromium_port, picalm_workbench_url, "epistemic-legacy")
    assert result["passed"] >= 6, result


def test_dashboard_documents_glp1(chromium_port, workbench_url):
    result = _run(chromium_port, workbench_url, "documents")
    assert result["passed"] >= 20, result


def test_source_viewer_card_highlight_glp1(chromium_port, workbench_url):
    result = _run(chromium_port, workbench_url, "card-highlight")
    assert result["passed"] >= 8, result


def test_chat_citation_opens_viewer_glp1(chromium_port, workbench_url):
    # The reply is stubbed in the browser (Fetch.fulfillRequest), so no model is
    # called. marked and DOMPurify come from a CDN; without them the run skips.
    result = _run(chromium_port, workbench_url, "citations")
    assert result["passed"] >= 8, result


def test_source_viewer_fda_deep_highlight(chromium_port, fda_workbench_url):
    result = _run(chromium_port, fda_workbench_url, "fda-highlight")
    assert result["passed"] >= 8, result
