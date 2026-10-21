#!/usr/bin/env python3
"""Capture workbench screenshots via Playwright for docs/screenshots/.

Produces 4 PNGs for the running workbench at http://127.0.0.1:<port>:
  <prefix>-01-dashboard.png     Dashboard panel (entity summary + counts)
  <prefix>-02-chat-welcome.png  Chat welcome with starter questions
  <prefix>-03-graph.png         Interactive vis.js force-directed graph
  <prefix>-04-chat-epistemic.png Chat with a sample question + streamed response

Usage:
    python scripts/capture_workbench_screenshots.py <port> <prefix>
    python scripts/capture_workbench_screenshots.py 8043 clinicaltrials

Set CAPTURE_MODEL to a model id from the picker (for example a ``:free``
OpenRouter model) to answer the chat question with that model, and
CAPTURE_STARTER to the 0-based starter question to ask (default 0).
"""
from __future__ import annotations

import os
import shutil
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parent.parent / "docs" / "screenshots"
VIEWPORT = {"width": 1600, "height": 1000}


def main(port: int, prefix: str) -> int:
    url = f"http://127.0.0.1:{port}"
    OUT.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as pw:
        # Fall back to a system chromium when Playwright's bundled browser
        # has not been downloaded (`playwright install chromium`).
        try:
            browser = pw.chromium.launch(headless=True)
        except Exception:
            system = shutil.which("chromium") or shutil.which("chromium-browser")
            if not system:
                raise
            browser = pw.chromium.launch(headless=True, executable_path=system)
        ctx = browser.new_context(viewport=VIEWPORT, device_scale_factor=2)
        page = ctx.new_page()

        page.goto(url, wait_until="networkidle", timeout=20000)
        page.wait_for_selector("#sidebar-title", timeout=15000)

        # ---- 1) Dashboard ----
        page.click('.nav-link[data-panel="dashboard"]')
        page.wait_for_selector(
            "#dashboard-panel .dashboard-title, #dashboard-panel h2, #dashboard-panel table",
            timeout=20000,
        )
        page.wait_for_timeout(800)
        dst = OUT / f"{prefix}-01-dashboard.png"
        page.screenshot(path=str(dst), full_page=False)
        print(f"wrote {dst}")

        # ---- 2) Chat welcome ----
        page.click('.nav-link[data-panel="chat"]')
        page.wait_for_selector("#welcome #welcome-title", timeout=10000)
        page.wait_for_selector(".starter-card", timeout=10000)
        page.wait_for_timeout(400)
        dst = OUT / f"{prefix}-02-chat-welcome.png"
        page.screenshot(path=str(dst), full_page=False)
        print(f"wrote {dst}")

        # ---- 3) Graph ----
        page.click('.nav-link[data-panel="graph"]')
        page.wait_for_selector("#graph-container canvas", timeout=20000)
        # Wait until the grouped layout has settled (graph.js exposes
        # window._graphDebug), then give the label pass a moment to draw.
        page.wait_for_function(
            """() => { const g = window._graphDebug;
                return !!(g && g.settled && !g.busy
                    && (g.mode === 'none' || g.regionGeometry().length > 0)); }""",
            timeout=60000,
        )
        page.wait_for_timeout(2000)
        dst = OUT / f"{prefix}-03-graph.png"
        page.screenshot(path=str(dst), full_page=False)
        print(f"wrote {dst}")

        # ---- 4) Chat with sample question + streamed answer ----
        page.click('.nav-link[data-panel="chat"]')
        page.wait_for_selector(".starter-card", timeout=10000)
        model = os.environ.get("CAPTURE_MODEL")
        if model:
            page.wait_for_selector(f'#model-select option[value="{model}"]', state="attached", timeout=15000)
            page.select_option("#model-select", model)
        starter = int(os.environ.get("CAPTURE_STARTER", "0"))
        page.click(f".starter-card >> nth={starter}")

        # Wait for an assistant message bubble to appear (chat.js uses .chat-msg--assistant)
        page.wait_for_selector(".chat-msg--assistant", timeout=25000)

        # Wait for the stream to stabilize: poll DOM for 20s and snapshot when
        # the message text length stops growing for 2s in a row.
        last_len = -1
        stable_for = 0
        deadline = time.time() + 90  # max wait
        while time.time() < deadline:
            try:
                html = page.evaluate(
                    "() => { const els = document.querySelectorAll('.chat-msg--assistant'); return Array.from(els).map(e => e.textContent).join('|'); }"
                )
            except Exception:
                html = ""
            cur_len = len(html or "")
            if cur_len == last_len and cur_len > 50:
                stable_for += 1
                if stable_for >= 4:  # 4 * 500ms = 2s stable
                    break
            else:
                stable_for = 0
                last_len = cur_len
            page.wait_for_timeout(500)

        # Scroll to top of the message to anchor the screenshot on the answer
        page.wait_for_timeout(800)
        dst = OUT / f"{prefix}-04-chat-epistemic.png"
        page.screenshot(path=str(dst), full_page=False)
        print(f"wrote {dst}")

        browser.close()
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python capture_workbench_screenshots.py <port> <prefix>", file=sys.stderr)
        sys.exit(2)
    sys.exit(main(int(sys.argv[1]), sys.argv[2]))
