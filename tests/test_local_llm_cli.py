"""CLI wiring for local LLM support: enhance preflight/abort/resume, `llm check`,
and the narrator context guard (LOCAL-04, LOCAL-06, LOCAL-08, LOCAL-09)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from core import cli, registry, triple_judge
from core.llm_client import LLMCallError, LLMConfig

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


# -- llm check ----------------------------------------------------------------
def test_llm_check_ok(fake_openai_server, monkeypatch, capsys):
    monkeypatch.setenv("EPISTRACT_LLM_BASE_URL", fake_openai_server.base_url)
    assert cli.main(["llm", "check"]) == 0
    out = capsys.readouterr().out
    for needle in ("local", fake_openai_server.base_url + "/v1", MODEL, "4096", "chat: ok"):
        assert needle in out


def test_llm_check_json_has_no_key(fake_openai_server, monkeypatch, capsys):
    monkeypatch.setenv("EPISTRACT_LLM_BASE_URL", fake_openai_server.base_url)
    assert cli.main(["llm", "check", "--json"]) == 0
    raw = capsys.readouterr().out
    data = json.loads(raw)
    assert set(data) >= {
        "provider", "base_url", "model", "context_window", "models", "chat_ok", "kind", "error",
    }
    assert "api_key" not in data and "local-no-key" not in raw
    assert data["models"] == [MODEL] and data["chat_ok"] is True


def test_llm_check_rerank_model_fails(fake_openai_server, monkeypatch, capsys):
    monkeypatch.setenv("EPISTRACT_LLM_BASE_URL", fake_openai_server.base_url)
    fake_openai_server.queue_400_rerank()
    assert cli.main(["llm", "check", "--json"]) == 1
    data = json.loads(capsys.readouterr().out)
    assert data["kind"] == "not_chat" and data["chat_ok"] is False


def test_llm_check_no_provider(capsys):
    assert cli.main(["llm", "check"]) == 1
    assert "EPISTRACT_LLM_BASE_URL" in capsys.readouterr().err


def test_llm_check_bogus_provider(monkeypatch, capsys):
    monkeypatch.setenv("EPISTRACT_LLM_PROVIDER", "bogus")
    assert cli.main(["llm", "check"]) == 1
    assert "Traceback" not in capsys.readouterr().err


# -- narrator context guard ---------------------------------------------------
def _patch_narrator(monkeypatch, cfg):
    from core import llm_client

    seen = {}

    def fake_call(system, user, **kw):
        seen.update(kw)
        return "briefing"

    monkeypatch.setattr(llm_client, "resolve_api_config", lambda: cfg)
    monkeypatch.setattr(llm_client, "call_llm", fake_call)
    return seen


def _narrate(system_chars):
    from core import label_epistemic as le

    le._summarize_graph_for_narrator = lambda g, c: "x" * system_chars  # type: ignore[assignment]
    return le.narrate_claims_layer({}, {}, "persona")


@pytest.fixture(autouse=True)
def _restore_summarizer():
    from core import label_epistemic as le

    orig = le._summarize_graph_for_narrator
    yield
    le._summarize_graph_for_narrator = orig


def _local(ctx):
    return LLMConfig("local-no-key", "http://h/v1", "m", "local", ctx)


def test_narrator_oversized_prompt_raises(monkeypatch):
    _patch_narrator(monkeypatch, _local(4096))
    with pytest.raises(LLMCallError) as ei:
        _narrate(30000)
    assert "exceeds context" in str(ei.value) and "4096" in str(ei.value)


def test_narrator_clamps_max_tokens_to_window(monkeypatch):
    from core import label_epistemic as le

    cfg = _local(4096)
    seen = _patch_narrator(monkeypatch, cfg)
    assert _narrate(3000) == "briefing"
    est = (len("persona\n\n---\n\n") + 3000 + len(le._NARRATOR_USER_PROMPT)) // 3 + 1
    assert seen["max_tokens"] == min(8192, 4096 - est - 64)
    assert seen["config"] is cfg


def test_narrator_cloud_keeps_8192(monkeypatch):
    seen = _patch_narrator(monkeypatch, LLMConfig("k", "http://h", "m", "anthropic", None))
    _narrate(100)
    assert seen["max_tokens"] == 8192


def test_narrator_local_unknown_window_omits_max_tokens(monkeypatch):
    seen = _patch_narrator(monkeypatch, _local(None))
    _narrate(100)
    assert seen["max_tokens"] is None


def test_narrator_env_cap(monkeypatch):
    monkeypatch.setenv("EPISTRACT_LLM_MAX_TOKENS", "300")
    seen = _patch_narrator(monkeypatch, _local(4096))
    _narrate(100)
    assert seen["max_tokens"] == 300


def _seed_checkpoint(root):
    ckpt = root / ".judge_checkpoint.jsonl"
    ckpt.write_text('{"type": "header"}\n')
    return ckpt


@pytest.mark.parametrize("flag", ["--resolve", "--epistemic"])
def test_enhance_llm_without_judge_keeps_checkpoint(
    project, fake_openai_server, monkeypatch, flag
):
    """WR-01: only a completed LLM judge may delete the checkpoint."""
    monkeypatch.setenv("EPISTRACT_LLM_BASE_URL", fake_openai_server.base_url)
    ckpt = _seed_checkpoint(project)
    assert cli.main(["enhance", "--project", "loc", flag, "--llm"]) == 0
    assert ckpt.exists()


def test_enhance_atomic_write_failure_keeps_graph_and_checkpoint(
    project, fake_openai_server, monkeypatch
):
    """WR-02: a failure while replacing the graph leaves it intact + checkpoint."""
    monkeypatch.setenv("EPISTRACT_LLM_BASE_URL", fake_openai_server.base_url)
    before = (project / "graph_data.json").read_text()
    ckpt = _seed_checkpoint(project)
    real = cli.os.replace

    def boom(src, dst):
        if Path(dst).name == "graph_data.json":
            raise OSError("disk full")
        return real(src, dst)

    monkeypatch.setattr(cli.os, "replace", boom)
    with pytest.raises(OSError):
        _enhance()
    assert (project / "graph_data.json").read_text() == before
    assert ckpt.exists()
    assert not list(project.glob("*.tmp"))


def test_enhance_malformed_base_url_clean_error(project, monkeypatch, capsys):
    """WR-03: no traceback, exit 1, nothing written."""
    monkeypatch.setenv("EPISTRACT_LLM_BASE_URL", "http://[::1")
    before = (project / "graph_data.json").read_text()
    assert _enhance() == 1
    assert "EPISTRACT_LLM_BASE_URL" in capsys.readouterr().err
    _unchanged(project, before)


def test_llm_check_malformed_base_url_clean_error(monkeypatch, capsys):
    monkeypatch.setenv("EPISTRACT_LLM_BASE_URL", "http://[::1")
    assert cli.main(["llm", "check"]) == 1
    assert "EPISTRACT_LLM_BASE_URL" in capsys.readouterr().err


def test_enhance_ctrl_c_during_preflight(project, fake_openai_server, monkeypatch, capsys):
    """IN-02: Ctrl-C in the preflight prints `interrupted`, returns 130."""
    from core import llm_local

    monkeypatch.setenv("EPISTRACT_LLM_BASE_URL", fake_openai_server.base_url)

    def raise_ki(cfg):
        raise KeyboardInterrupt

    monkeypatch.setattr(llm_local, "check_chat", raise_ki)
    before = (project / "graph_data.json").read_text()
    assert _enhance() == 130
    assert "interrupted" in capsys.readouterr().err
    _unchanged(project, before)


def test_enhance_ctrl_c_during_make_llm_judge(project, monkeypatch, capsys):
    def raise_ki(*a, **k):
        raise KeyboardInterrupt

    monkeypatch.setattr(triple_judge, "make_llm_judge", raise_ki)
    before = (project / "graph_data.json").read_text()
    assert _enhance() == 130
    assert "interrupted" in capsys.readouterr().err
    _unchanged(project, before)
