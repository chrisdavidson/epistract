"""scripts/extract_corpus.py against a local OpenAI-compatible server (stub)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import httpx
import pytest
from openai import OpenAI

from core.llm_client import LOCAL_PLACEHOLDER_KEY

pytestmark = pytest.mark.unit

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FENCE = "`" * 3
EMPTY = '{"entities": [], "relations": []}'


def _load():
    spec = importlib.util.spec_from_file_location(
        "extract_corpus_under_test", PROJECT_ROOT / "scripts" / "extract_corpus.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def ec():
    return _load()


@pytest.fixture
def sleeps(ec, monkeypatch):
    calls: list[float] = []
    monkeypatch.setattr(ec, "_sleep", calls.append)
    return calls


def _client(stub) -> OpenAI:
    return OpenAI(
        api_key=LOCAL_PLACEHOLDER_KEY,
        base_url=f"{stub.base_url}/v1",
        max_retries=0,
        http_client=httpx.Client(trust_env=False),
    )


def _chat_requests(stub) -> list[dict]:
    return [r for r in stub.requests if r["path"].endswith("/chat/completions")]


# -- target resolution ---------------------------------------------------


def test_target_openrouter_default(ec, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    assert ec._resolve_target(None, None) == {
        "provider": "openrouter",
        "api_base": "https://openrouter.ai/api/v1",
        "api_key": "k",
        "real_key": "k",
        "model": "anthropic/claude-sonnet-4.6",
    }


def test_target_no_env_no_key_names_both_vars(ec, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(ValueError) as exc:
        ec._resolve_target(None, None)
    assert "OPENROUTER_API_KEY" in str(exc.value)
    assert "EPISTRACT_LLM_BASE_URL" in str(exc.value)


def test_target_local_autopicks_model(ec, fake_openai_server, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-secret")
    t = ec._resolve_target(fake_openai_server.base_url, None)
    assert t["provider"] == "local"
    assert t["api_base"] == f"{fake_openai_server.base_url}/v1"
    assert t["api_key"] == LOCAL_PLACEHOLDER_KEY  # never the OpenRouter key
    assert t["model"] == "Phi-3-mini-4k-instruct-q4.gguf"


def test_target_local_model_precedence(ec, fake_openai_server, monkeypatch):
    monkeypatch.setenv("EPISTRACT_LLM_MODEL", "from-env")
    assert ec._resolve_target(fake_openai_server.base_url, None)["model"] == "from-env"
    assert ec._resolve_target(fake_openai_server.base_url, "m")["model"] == "m"


def test_target_local_key_only_from_llm_api_key(ec, fake_openai_server, monkeypatch):
    monkeypatch.setenv("EPISTRACT_LLM_API_KEY", "srv-key")
    t = ec._resolve_target(fake_openai_server.base_url, "m")
    assert t["api_key"] == "srv-key"


def test_target_env_base_url_and_flag_override(ec, fake_openai_server, monkeypatch):
    monkeypatch.setenv("EPISTRACT_LLM_BASE_URL", "http://127.0.0.1:1")
    assert ec._resolve_target(None, "m")["api_base"] == "http://127.0.0.1:1/v1"
    t = ec._resolve_target(fake_openai_server.base_url, "m")
    assert t["api_base"] == f"{fake_openai_server.base_url}/v1"


def test_target_provider_env(ec, monkeypatch):
    monkeypatch.setenv("EPISTRACT_LLM_BASE_URL", "http://127.0.0.1:1")
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    monkeypatch.setenv("EPISTRACT_LLM_PROVIDER", "openrouter")
    assert ec._resolve_target(None, None)["provider"] == "openrouter"
    monkeypatch.setenv("EPISTRACT_LLM_PROVIDER", "anthropic")
    with pytest.raises(ValueError, match="local and openrouter"):
        ec._resolve_target(None, None)


# -- context-fit warning ---------------------------------------------------


def test_context_warning_small_window(ec):
    msg = ec._context_fit_warning("x" * 46000, 4096, "Phi-3", 8192, 8000)
    assert msg is not None
    assert "WARNING" in msg
    assert "cannot do extraction" in msg
    assert "4096" in msg
    assert "tokens of context" in msg


def test_context_warning_none_when_fits_or_unknown(ec):
    assert ec._context_fit_warning("x" * 46000, 200000, "m", 8192, 8000) is None
    assert ec._context_fit_warning("x" * 46000, None, "m", 8192, 8000) is None


# -- main() ----------------------------------------------------------------


def _corpus(tmp_path: Path) -> Path:
    out = tmp_path / "out"
    (out / "ingested").mkdir(parents=True)
    (out / "ingested" / "doc1.txt").write_text(
        "Semaglutide is a GLP-1 receptor agonist.", encoding="utf-8"
    )
    return out


def _run_main(ec, monkeypatch, out: Path, *extra: str) -> int:
    monkeypatch.setattr(
        sys, "argv", ["extract_corpus.py", str(out), "--domain", "contracts", *extra]
    )
    return ec.main()


def test_main_warns_on_small_context_and_records_run(
    ec, fake_openai_server, monkeypatch, tmp_path, capsys
):
    out = _corpus(tmp_path)
    monkeypatch.setattr(sys, "argv", ["extract_corpus.py", str(out), "--domain", "drug-discovery", "--base-url", fake_openai_server.base_url])
    rc = ec.main()
    err = capsys.readouterr().err
    assert "WARNING" in err and "cannot do extraction" in err
    assert rc == 1  # the chunk cannot fit; the run proceeded and counted a failure
    assert _chat_requests(fake_openai_server) == []
    run = json.loads((out / "extract_run.json").read_text())
    assert run["provider"] == "local"
    assert run["base_url"] == f"{fake_openai_server.base_url}/v1"
    assert run["model"] == "Phi-3-mini-4k-instruct-q4.gguf"
    assert run["total_cost_usd"] is None


def test_main_local_derives_max_tokens_from_window(
    ec, fake_openai_server, monkeypatch, tmp_path, capsys
):
    fake_openai_server.n_ctx = fake_openai_server.props_n_ctx = 32768
    fake_openai_server.queue_content(EMPTY)
    out = _corpus(tmp_path)
    assert _run_main(ec, monkeypatch, out, "--base-url", fake_openai_server.base_url) == 0
    reqs = _chat_requests(fake_openai_server)
    assert len(reqs) == 1
    system = reqs[0]["json"]["messages"][0]["content"]
    user = reqs[0]["json"]["messages"][1]["content"]
    expected = min(8192, 32768 - len(system) // 3 - len(user) // 3 - 64)
    assert reqs[0]["json"]["max_tokens"] == expected
    assert "OPENROUTER" not in reqs[0]["headers"].get("authorization", "")
    assert reqs[0]["headers"]["authorization"] == f"Bearer {LOCAL_PLACEHOLDER_KEY}"
    assert "cost n/a" in capsys.readouterr().out


def test_main_local_unknown_window_omits_max_tokens(
    ec, fake_openai_server, monkeypatch, tmp_path
):
    fake_openai_server.n_ctx = fake_openai_server.props_n_ctx = None
    fake_openai_server.queue_content(EMPTY)
    out = _corpus(tmp_path)
    assert _run_main(ec, monkeypatch, out, "--base-url", fake_openai_server.base_url) == 0
    assert "max_tokens" not in _chat_requests(fake_openai_server)[0]["json"]


def test_openrouter_budget_stays_8192(ec):
    assert ec._request_budget("openrouter", None, "s", "u") == 8192


def test_main_stops_on_quota_and_writes_summary(
    ec, fake_openai_server, monkeypatch, tmp_path, capsys, sleeps
):
    fake_openai_server.n_ctx = fake_openai_server.props_n_ctx = 32768
    fake_openai_server.queue_429_daily()
    out = _corpus(tmp_path)
    (out / "ingested" / "doc2.txt").write_text("Second doc.", encoding="utf-8")
    rc = _run_main(ec, monkeypatch, out, "--base-url", fake_openai_server.base_url)
    assert rc == 3
    assert "quota" in capsys.readouterr().err
    assert len(_chat_requests(fake_openai_server)) == 1  # doc2 never attempted
    assert sleeps == []
    run = json.loads((out / "extract_run.json").read_text())
    assert run["stopped"] == "quota"


def test_main_no_target_exits_2(ec, monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    out = _corpus(tmp_path)
    assert _run_main(ec, monkeypatch, out) == 2
    assert "OPENROUTER_API_KEY" in capsys.readouterr().err


# -- call_llm retries and parsing --------------------------------------------


def test_call_llm_quota_stops_after_one_attempt(ec, fake_openai_server, sleeps):
    fake_openai_server.queue_429_daily()
    with pytest.raises(ec.ExtractStop) as exc:
        ec.call_llm(_client(fake_openai_server), "m", "sys", "chunk")
    assert exc.value.kind == "quota"
    assert len(_chat_requests(fake_openai_server)) == 1
    assert sleeps == []


def test_call_llm_fatal_rerank_stops_after_one_attempt(ec, fake_openai_server, sleeps):
    fake_openai_server.queue_400_rerank()
    with pytest.raises(ec.ExtractStop) as exc:
        ec.call_llm(_client(fake_openai_server), "m", "sys", "chunk")
    assert exc.value.kind == "fatal"
    assert len(_chat_requests(fake_openai_server)) == 1


def test_call_llm_context_error_is_per_chunk_no_retry(ec, fake_openai_server, sleeps):
    fake_openai_server.queue_status(
        400, {"error": {"message": "request exceeds the available context size"}}
    )
    with pytest.raises(RuntimeError) as exc:
        ec.call_llm(_client(fake_openai_server), "m", "sys", "chunk")
    assert not isinstance(exc.value, ec.ExtractStop)
    assert len(_chat_requests(fake_openai_server)) == 1
    assert sleeps == []


def test_call_llm_transient_retries_then_succeeds(ec, fake_openai_server, sleeps):
    fake_openai_server.queue_status(500, {"error": "boom"})
    fake_openai_server.queue_status(500, {"error": "boom"})
    fake_openai_server.queue_content(EMPTY)
    ents, rels, cost, tokens = ec.call_llm(_client(fake_openai_server), "m", "s", "c")
    assert (ents, rels, cost, tokens) == ([], [], 0.0, 12)
    assert len(_chat_requests(fake_openai_server)) == 3
    assert len(sleeps) == 2


@pytest.mark.parametrize(
    "reply",
    [f"{FENCE}json\n{EMPTY}\n{FENCE}", f"Here you go: {EMPTY}"],
)
def test_call_llm_parses_fenced_and_prose_wrapped(ec, fake_openai_server, reply):
    fake_openai_server.queue_content(reply)
    ents, rels, _, _ = ec.call_llm(_client(fake_openai_server), "m", "s", "c")
    assert (ents, rels) == ([], [])


def test_call_llm_unparseable_fails_after_three_attempts(ec, fake_openai_server, sleeps):
    for _ in range(3):
        fake_openai_server.queue_content("not json at all")
    with pytest.raises(RuntimeError, match="after 3 retries"):
        ec.call_llm(_client(fake_openai_server), "m", "s", "c")
    assert len(_chat_requests(fake_openai_server)) == 3


def test_call_llm_stub_returns_entities_and_zero_cost(ec, fake_openai_server):
    fake_openai_server.queue_content(
        '{"entities": [{"name": "A", "entity_type": "X"}], "relations": []}'
    )
    ents, rels, cost, tokens = ec.call_llm(_client(fake_openai_server), "m", "s", "c")
    assert ents == [{"name": "A", "entity_type": "X"}]
    assert cost == 0.0 and tokens == 12


def test_base_url_overriding_openrouter_provider_prints_notice(monkeypatch, capsys):
    mod = _load()
    monkeypatch.setenv("EPISTRACT_LLM_PROVIDER", "openrouter")
    target = mod._resolve_target("http://localhost:1234/v1", "m")
    assert target["provider"] == "local"
    assert "overrides EPISTRACT_LLM_PROVIDER=openrouter" in capsys.readouterr().err
