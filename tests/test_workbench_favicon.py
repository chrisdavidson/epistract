"""The workbench serves its favicon instead of answering /favicon.ico with a 404."""

from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from examples.workbench.server import create_app

pytestmark = pytest.mark.unit


@pytest.fixture()
def client(tmp_path):
    (tmp_path / "graph_data.json").write_text('{"nodes": [], "links": []}', encoding="utf-8")
    return TestClient(create_app(tmp_path, domain=None))


def test_favicon_ico_served(client):
    resp = client.get("/favicon.ico")
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
    assert resp.headers["content-type"] == "image/x-icon", resp.headers["content-type"]
    assert resp.content[:4] == b"\x00\x00\x01\x00", "favicon.ico is not an ICO file"


def test_favicon_svg_served_and_linked(client):
    resp = client.get("/static/favicon.svg")
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
    assert "image/svg+xml" in resp.headers["content-type"], resp.headers["content-type"]
    index = client.get("/").text
    assert 'href="/static/favicon.svg"' in index, "index.html does not link the SVG icon"
