"""Tests for the workbench chat Clear control (CHAT-01..03)."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

WORKBENCH_STATIC = Path(__file__).resolve().parent.parent / "examples" / "workbench" / "static"
HARNESS = Path(__file__).resolve().parent / "js" / "clear_chat_harness.mjs"


def _chat_js() -> str:
    text = (WORKBENCH_STATIC / "chat.js").read_text()
    return re.sub(r"//[^\n]*", "", text)


@pytest.mark.unit
def test_clear_button_in_form():
    html = (WORKBENCH_STATIC / "index.html").read_text()
    form = re.search(r'<form[^>]*id="chat-form".*?</form>', html, re.S)
    assert form, "chat-form not found"
    btn = re.search(r'<button[^>]*id="chat-clear-btn"[^>]*>(.*?)</button>', form.group(0), re.S)
    assert btn, "chat-clear-btn missing inside #chat-form"
    tag = re.search(r'<button[^>]*id="chat-clear-btn"[^>]*>', form.group(0)).group(0)
    assert 'type="button"' in tag
    assert "aria-label=" in tag
    assert "display:none" not in tag.replace(" ", "")
    assert btn.group(1).strip(), "button needs a visible label"


@pytest.mark.unit
def test_chat_js_wiring():
    js = _chat_js()
    assert "export function clearChat" in js
    assert "new AbortController" in js
    assert re.search(r"signal\s*:", js), "signal not passed to fetch"
    assert "chatGeneration" in js


@pytest.mark.unit
def test_clear_button_styled():
    css = (WORKBENCH_STATIC / "style.css").read_text()
    assert ".chat-clear-btn" in css


@pytest.mark.unit
def test_clear_chat_behavior():
    if shutil.which("node") is None:
        pytest.skip("node not available")
    result = subprocess.run(["node", str(HARNESS)], timeout=30, capture_output=True, text=True)
    assert result.returncode == 0, (
        f"harness failed\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )
