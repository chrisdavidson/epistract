"""CLI wiring for local LLM support: enhance preflight/abort/resume, `llm check`,
and the narrator context guard (LOCAL-04, LOCAL-06, LOCAL-08, LOCAL-09)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from core import cli, registry, triple_judge

MODEL = "Phi-3-mini-4k-instruct-q4.gguf"
N_LINKS = 5


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setenv("EPISTRACT_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("EPISTRACT_PROJECT", raising=False)
    proj = registry.init_project("loc", root=tmp_path / "loc", domain="drug-discovery")
    graph = {
        "nodes": [],
        "links": [
            {
                "source": f"a:x{i}",
                "target": f"b:y{i}",
                "relation_type": "R",
                "evidence": f"x{i} acts on y{i}.",
            }
            for i in range(N_LINKS)
        ],
    }
    root = Path(proj["root"])
    (root / "graph_data.json").write_text(json.dumps(graph))
    return root


def _chat_requests(server):
    return [r for r in server.requests if r.get("path", "").endswith("/chat/completions")]


def _enhance(*extra):
    return cli.main(["enhance", "--project", "loc", "--judge", "--llm", *extra])


def _unchanged(root, before):
    assert (root / "graph_data.json").read_text() == before
    assert not (root / "enhancement_report.json").exists()


def test_enhance_no_provider_exits_1_untouched(project, capsys):
    before = (project / "graph_data.json").read_text()
    assert _enhance() == 1
    assert "EPISTRACT_LLM_BASE_URL" in capsys.readouterr().err
    _unchanged(project, before)


def test_enhance_local_success_report_and_checkpoint_cleanup(
    project, fake_openai_server, monkeypatch, capsys
):
    monkeypatch.setenv("EPISTRACT_LLM_BASE_URL", fake_openai_server.base_url)
    assert _enhance() == 0
    err = capsys.readouterr().err
    assert "provider=local" in err and MODEL in err and "judge:" in err
    report = json.loads((project / "enhancement_report.json").read_text())
    j = report["judge"]
    assert j["provider"] == "local" and j["model"] == MODEL
    assert j["base_url"] == fake_openai_server.base_url + "/v1"
    assert j["llm_judged"] == N_LINKS and j["fallback"] == 0
    assert j["resumed"] == 0 and j["aborted"] is False and j["mode"] == "llm"
    assert "local-no-key" not in json.dumps(report)
    assert not (project / ".judge_checkpoint.jsonl").exists()


def test_enhance_json_stdout_is_pure_json(project, fake_openai_server, monkeypatch, capsys):
    monkeypatch.setenv("EPISTRACT_LLM_BASE_URL", fake_openai_server.base_url)
    assert _enhance("--json") == 0
    out = capsys.readouterr()
    assert json.loads(out.out)["judge"]["llm_judged"] == N_LINKS
    assert "judge:" not in out.out and "judge:" in out.err


def test_enhance_preflight_rejects_non_chat_model(
    project, fake_openai_server, monkeypatch, capsys
):
    monkeypatch.setenv("EPISTRACT_LLM_BASE_URL", fake_openai_server.base_url)
    fake_openai_server.queue_400_rerank()
    before = (project / "graph_data.json").read_text()
    assert _enhance() == 1
    assert "not a chat model" in capsys.readouterr().err
    assert len(_chat_requests(fake_openai_server)) == 1
    _unchanged(project, before)


def _abort_after_two(server, monkeypatch):
    monkeypatch.setenv("EPISTRACT_LLM_BASE_URL", server.base_url)
    for _ in range(3):  # preflight + 2 judge calls
        server.queue_content('{"verdict": "supported", "score": 0.9, "reason": "ok"}')
    server.queue_429_daily()


def test_enhance_abort_keeps_checkpoint_then_resumes(
    project, fake_openai_server, monkeypatch, capsys
):
    _abort_after_two(fake_openai_server, monkeypatch)
    before = (project / "graph_data.json").read_text()
    assert _enhance() == 1
    err = capsys.readouterr().err
    assert "aborted" in err and "checkpoint kept" in err
    _unchanged(project, before)
    ckpt = project / ".judge_checkpoint.jsonl"
    lines = [json.loads(x) for x in ckpt.read_text().splitlines() if x.strip()]
    assert len(lines) == 3 and lines[0]["type"] == "header"

    fake_openai_server.requests.clear()
    assert _enhance() == 0
    j = json.loads((project / "enhancement_report.json").read_text())["judge"]
    assert j["resumed"] == 2
    assert len(_chat_requests(fake_openai_server)) == (N_LINKS - 2) + 1
    assert not ckpt.exists()


def test_enhance_fresh_ignores_checkpoint(project, fake_openai_server, monkeypatch):
    _abort_after_two(fake_openai_server, monkeypatch)
    assert _enhance() == 1
    assert _enhance("--fresh") == 0
    j = json.loads((project / "enhancement_report.json").read_text())["judge"]
    assert j["resumed"] == 0


def test_enhance_keyboard_interrupt_exits_130(project, monkeypatch, capsys):
    calls = {"n": 0}

    def fn(system, user, **kw):
        calls["n"] += 1
        if calls["n"] == 3:
            raise KeyboardInterrupt
        return '{"verdict": "supported", "score": 0.9, "reason": "ok"}'

    real = triple_judge.make_llm_judge
    monkeypatch.setattr(triple_judge, "make_llm_judge", lambda: real(call_fn=fn))
    before = (project / "graph_data.json").read_text()
    assert _enhance() == 130
    assert "checkpoint kept" in capsys.readouterr().err
    _unchanged(project, before)
    lines = (project / ".judge_checkpoint.jsonl").read_text().splitlines()
    assert len(lines) == 3


def test_enhance_lexical_report_has_no_provider(project):
    assert cli.main(["enhance", "--project", "loc", "--judge"]) == 0
    j = json.loads((project / "enhancement_report.json").read_text())["judge"]
    assert j["mode"] == "lexical" and j["provider"] is None
    assert not (project / ".judge_checkpoint.jsonl").exists()
