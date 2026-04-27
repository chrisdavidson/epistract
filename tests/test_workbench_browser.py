"""Live-browser verification of the chat model selector (Phase 08 gap closure).

Closes verification item #2 from 08-VERIFICATION.md. The workbench server
is expected to be already running on http://127.0.0.1:8045/ with
ANTHROPIC_API_KEY set; scripts/run_workbench_browser_check.py boots it.
"""
from __future__ import annotations

import json
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import Route, Request, sync_playwright  # noqa: E402

WORKBENCH_URL = "http://127.0.0.1:8045"
EXPECTED_ANTHROPIC_IDS = {
    "claude-sonnet-4-20250514",
    "claude-opus-4-20250514",
    "claude-haiku-3-5-20241022",
}
SELECTED_MODEL = "claude-haiku-3-5-20241022"
EVIDENCE_PATH = (
    Path(__file__).resolve().parent
    / "corpora"
    / "09_arxiv_cs"
    / "output"
    / "model_selector_browser_check.json"
)


def _server_up() -> bool:
    try:
        with urllib.request.urlopen(WORKBENCH_URL + "/api/health", timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


@pytest.mark.e2e
def test_model_selector_in_browser():
    assert _server_up(), (
        "workbench not running on 127.0.0.1:8045 — "
        "use scripts/run_workbench_browser_check.py to boot it"
    )

    captured: dict = {}

    def handle_chat(route: Route, request: Request) -> None:
        # Capture the POST body before fulfilling with a minimal SSE.
        try:
            captured["body"] = json.loads(request.post_data or "{}")
        except json.JSONDecodeError:
            captured["body"] = {"_raw": request.post_data}
        route.fulfill(
            status=200,
            headers={"Content-Type": "text/event-stream"},
            body='data: {"type":"done"}\n\n',
        )

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1280, "height": 800})
        page = ctx.new_page()
        page.route("**/api/chat", handle_chat)

        page.goto(WORKBENCH_URL + "/", wait_until="networkidle", timeout=20000)

        # Truth #1: #model-select becomes visible
        page.wait_for_selector(
            "#model-select", state="visible", timeout=10000
        )

        # Truth #2: exactly 3 anthropic options
        option_values = page.eval_on_selector_all(
            "#model-select option",
            "els => els.map(e => e.value).filter(v => v && v.length > 0)",
        )
        assert set(option_values) == EXPECTED_ANTHROPIC_IDS, (
            f"expected {sorted(EXPECTED_ANTHROPIC_IDS)} anthropic models, "
            f"got {sorted(option_values)}"
        )

        # Truth #3: select + send -> model in POST body
        page.select_option("#model-select", SELECTED_MODEL)
        page.fill("#chat-input", "test from browser check")
        with page.expect_request("**/api/chat", timeout=10000):
            page.click(".send-btn")

        assert "body" in captured, "no /api/chat POST observed"
        assert captured["body"].get("model") == SELECTED_MODEL, (
            f"expected model={SELECTED_MODEL} in POST body, "
            f"got {captured['body'].get('model')!r}"
        )

        # Persist evidence
        EVIDENCE_PATH.parent.mkdir(parents=True, exist_ok=True)
        EVIDENCE_PATH.write_text(
            json.dumps(
                {
                    "model": SELECTED_MODEL,
                    "captured_at": datetime.now(timezone.utc).isoformat(),
                    "request_body": captured["body"],
                },
                indent=2,
            )
        )

        browser.close()
