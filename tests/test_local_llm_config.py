"""Resolver, URL normaliser and server-probe tests for the local LLM provider (LOCAL-01, LOCAL-02)."""
from __future__ import annotations

import pytest

from core import llm_client, llm_local
from core.llm_client import LLMCallError


def _api(server) -> str:
    return server.base_url + "/v1"


# ---------------------------------------------------------------------------
# list_models / pick_chat_model
# ---------------------------------------------------------------------------
def test_list_models_parses_llamacpp_shape(fake_openai_server):
    """LOCAL-01: llama.cpp /v1/models yields id and n_ctx."""
    assert llm_local.list_models(_api(fake_openai_server)) == [
        {"id": "Phi-3-mini-4k-instruct-q4.gguf", "n_ctx": 4096}
    ]


def test_list_models_no_auth_header_without_key(fake_openai_server):
    llm_local.list_models(_api(fake_openai_server))
    assert "authorization" not in fake_openai_server.requests[-1]["headers"]


def test_list_models_sends_bearer_with_key(fake_openai_server):
    llm_local.list_models(_api(fake_openai_server), api_key="sekret")
    assert fake_openai_server.requests[-1]["headers"]["authorization"] == "Bearer sekret"


def test_list_models_unreachable_names_url_not_key():
    with pytest.raises(LLMCallError) as ei:
        llm_local.list_models("http://127.0.0.1:9/v1", api_key="topsecret")
    assert "http://127.0.0.1:9/v1" in str(ei.value)
    assert "topsecret" not in str(ei.value)


def test_pick_chat_model_skips_embedding_and_rerank():
    assert llm_local.pick_chat_model(["nomic-embed-text", "bge-reranker", "llama3:8b"]) == "llama3:8b"
    assert llm_local.pick_chat_model(["text-embedding-3"]) is None


# ---------------------------------------------------------------------------
# probe_context
# ---------------------------------------------------------------------------
def test_probe_context_from_models_meta(fake_openai_server):
    assert llm_local.probe_context(_api(fake_openai_server), "Phi-3-mini-4k-instruct-q4.gguf") == 4096


def test_probe_context_falls_back_to_props(fake_openai_server):
    fake_openai_server.n_ctx = None
    assert llm_local.probe_context(_api(fake_openai_server), "Phi-3-mini-4k-instruct-q4.gguf") == 4096


def test_probe_context_none_when_unknown(fake_openai_server):
    fake_openai_server.n_ctx = None
    fake_openai_server.props_n_ctx = None
    assert llm_local.probe_context(_api(fake_openai_server), "Phi-3-mini-4k-instruct-q4.gguf") is None


def test_probe_context_takes_smaller_per_slot_value(fake_openai_server):
    fake_openai_server.n_ctx = 8192
    fake_openai_server.props_n_ctx = 2048
    assert llm_local.probe_context(_api(fake_openai_server), "Phi-3-mini-4k-instruct-q4.gguf") == 2048


def test_probe_context_vllm_max_model_len(fake_openai_server):
    fake_openai_server.n_ctx = None
    fake_openai_server.props_n_ctx = None
    fake_openai_server.max_model_len = 32768
    assert llm_local.probe_context(_api(fake_openai_server), "Phi-3-mini-4k-instruct-q4.gguf") == 32768


def test_probe_context_lmstudio(fake_openai_server):
    fake_openai_server.n_ctx = None
    fake_openai_server.props_n_ctx = None
    fake_openai_server.lmstudio_ctx = 8192
    assert llm_local.probe_context(_api(fake_openai_server), "Phi-3-mini-4k-instruct-q4.gguf") == 8192


def test_probe_context_ollama_num_ctx(fake_openai_server):
    fake_openai_server.n_ctx = None
    fake_openai_server.props_n_ctx = None
    fake_openai_server.ollama_parameters = 'stop "<|im_end|>"\nnum_ctx                        16384\n'
    assert llm_local.probe_context(_api(fake_openai_server), "Phi-3-mini-4k-instruct-q4.gguf") == 16384


def test_probe_context_ollama_without_num_ctx_is_none(fake_openai_server):
    fake_openai_server.n_ctx = None
    fake_openai_server.props_n_ctx = None
    fake_openai_server.ollama_parameters = 'stop "<|im_end|>"\n'
    assert llm_local.probe_context(_api(fake_openai_server), "Phi-3-mini-4k-instruct-q4.gguf") is None


def test_probe_context_env_override_makes_no_request(fake_openai_server, monkeypatch):
    monkeypatch.setenv("EPISTRACT_LLM_CONTEXT_WINDOW", "6000")
    assert llm_local.probe_context(_api(fake_openai_server), "m") == 6000
    assert fake_openai_server.requests == []


@pytest.mark.parametrize("bad", ["abc", "0", "-5"])
def test_probe_context_ignores_invalid_override(fake_openai_server, monkeypatch, bad):
    monkeypatch.setenv("EPISTRACT_LLM_CONTEXT_WINDOW", bad)
    assert llm_local.probe_context(_api(fake_openai_server), "Phi-3-mini-4k-instruct-q4.gguf") == 4096


# ---------------------------------------------------------------------------
# cache isolation (conftest autouse owns the clearing)
# ---------------------------------------------------------------------------
def test_models_cache_populated(fake_openai_server):
    llm_local.list_models(_api(fake_openai_server))
    assert llm_local._MODELS_CACHE


def test_models_cache_cleared_between_tests():
    assert llm_local._MODELS_CACHE == {}
    assert llm_local._CTX_CACHE == {}


# ---------------------------------------------------------------------------
# normalise_base_url
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "raw,expected",
    [
        ("harley.home:9996", "http://harley.home:9996/v1"),
        ("harley.home:9996/v1", "http://harley.home:9996/v1"),
        ("http://h:9996/v1/", "http://h:9996/v1"),
        ("http://h:11434/v1/chat/completions", "http://h:11434/v1"),
        ("https://gw/llm/v1", "https://gw/llm/v1"),
        ("http://user:pw@h:1", "http://h:1/v1"),
    ],
)
def test_normalise_base_url(raw, expected):
    assert llm_client.normalise_base_url(raw) == expected


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("http://h:0", "http://h:0/v1"),
        ("HTTP://H:1/V1", "http://h:1/v1"),
        ("http://h:1/v1/models", "http://h:1/v1"),
        ("http://h:1/v1/completions", "http://h:1/v1"),
        ("http://h:1/V1/Chat/Completions", "http://h:1/v1"),
    ],
)
def test_normalise_base_url_edge_cases(raw, expected):
    """WR-02: port 0 kept, suffix matching case-insensitive, /models stripped."""
    assert llm_client.normalise_base_url(raw) == expected


@pytest.mark.parametrize("raw", ["http://h:abc", "http://h:99999"])
def test_normalise_base_url_bad_port_is_config_error(raw):
    """WR-01: a bad port raises LLMConfigError, not a bare ValueError."""
    with pytest.raises(llm_client.LLMConfigError):
        llm_client.normalise_base_url(raw)


def test_normalise_base_url_rejects_other_schemes():
    with pytest.raises(llm_client.LLMConfigError):
        llm_client.normalise_base_url("ftp://h")


# ---------------------------------------------------------------------------
# resolve_api_config
# ---------------------------------------------------------------------------
CLOUD_VARS = (
    "AZURE_FOUNDRY_API_KEY",
    "ANTHROPIC_FOUNDRY_API_KEY",
    "ANTHROPIC_API_KEY",
    "OPENROUTER_API_KEY",
)


@pytest.fixture(autouse=True)
def _no_cloud(monkeypatch):
    for v in CLOUD_VARS:
        monkeypatch.delenv(v, raising=False)


def test_local_from_base_url_only(fake_openai_server, monkeypatch):
    monkeypatch.setenv("EPISTRACT_LLM_BASE_URL", fake_openai_server.base_url)
    cfg = llm_client.resolve_api_config()
    assert cfg.provider == "local"
    assert cfg.base_url == fake_openai_server.base_url + "/v1"
    assert cfg.model == "Phi-3-mini-4k-instruct-q4.gguf"
    assert cfg.context_window == 4096
    assert cfg.api_key == llm_client.LOCAL_PLACEHOLDER_KEY


@pytest.mark.parametrize("suffix", ["", "/v1", "/v1/chat/completions"])
def test_local_url_forms_resolve_identically(fake_openai_server, monkeypatch, suffix):
    monkeypatch.setenv("EPISTRACT_LLM_BASE_URL", fake_openai_server.base_url + suffix)
    assert llm_client.resolve_api_config().base_url == fake_openai_server.base_url + "/v1"


def test_local_model_override_still_probes_context(fake_openai_server, monkeypatch):
    monkeypatch.setenv("EPISTRACT_LLM_BASE_URL", fake_openai_server.base_url)
    monkeypatch.setenv("EPISTRACT_LLM_MODEL", "foo")
    cfg = llm_client.resolve_api_config()
    assert cfg.model == "foo"
    # probe_context ran for "foo": no matching model entry, /props still answers
    assert cfg.context_window == 4096


def test_local_model_override_context_may_be_none(fake_openai_server, monkeypatch):
    fake_openai_server.n_ctx = None
    fake_openai_server.props_n_ctx = None
    monkeypatch.setenv("EPISTRACT_LLM_BASE_URL", fake_openai_server.base_url)
    monkeypatch.setenv("EPISTRACT_LLM_MODEL", "foo")
    assert llm_client.resolve_api_config().context_window is None


def test_local_api_key_from_env(fake_openai_server, monkeypatch):
    monkeypatch.setenv("EPISTRACT_LLM_BASE_URL", fake_openai_server.base_url)
    monkeypatch.setenv("EPISTRACT_LLM_API_KEY", "k")
    assert llm_client.resolve_api_config().api_key == "k"


def test_d02_local_wins_over_cloud_keys(fake_openai_server, monkeypatch):
    monkeypatch.setenv("EPISTRACT_LLM_BASE_URL", fake_openai_server.base_url)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-cloud")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-cloud")
    cfg = llm_client.resolve_api_config()
    assert cfg.provider == "local"
    assert cfg.api_key == llm_client.LOCAL_PLACEHOLDER_KEY
    assert "sk-ant-cloud" not in repr(cfg) and "sk-or-cloud" not in repr(cfg)


def test_d02_switch_false_cloud_wins(fake_openai_server, monkeypatch):
    monkeypatch.setattr(llm_client, "LOCAL_BASE_URL_WINS", False)
    monkeypatch.setenv("EPISTRACT_LLM_BASE_URL", fake_openai_server.base_url)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-cloud")
    assert llm_client.resolve_api_config().provider == "anthropic"
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    assert llm_client.resolve_api_config().provider == "local"


def test_provider_override_anthropic(fake_openai_server, monkeypatch):
    monkeypatch.setenv("EPISTRACT_LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("EPISTRACT_LLM_BASE_URL", fake_openai_server.base_url)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-cloud")
    assert llm_client.resolve_api_config().provider == "anthropic"


@pytest.mark.parametrize("provider", ["local", "anthropic", "openrouter", "foundry"])
def test_provider_override_missing_credentials_raises(monkeypatch, provider):
    monkeypatch.setenv("EPISTRACT_LLM_PROVIDER", provider)
    with pytest.raises(llm_client.LLMConfigError):
        llm_client.resolve_api_config()


def test_provider_override_bogus_raises(monkeypatch):
    monkeypatch.setenv("EPISTRACT_LLM_PROVIDER", "bogus")
    with pytest.raises(llm_client.LLMConfigError):
        llm_client.resolve_api_config()


def test_unset_vars_keep_legacy_order(monkeypatch):
    assert llm_client.resolve_api_config() is None
    monkeypatch.setenv("OPENROUTER_API_KEY", "or")
    assert llm_client.resolve_api_config().provider == "openrouter"
    monkeypatch.setenv("ANTHROPIC_API_KEY", "an")
    cfg = llm_client.resolve_api_config()
    assert (cfg.provider, cfg.api_key) == ("anthropic", "an")
    monkeypatch.setenv("AZURE_FOUNDRY_API_KEY", "fk")
    monkeypatch.setenv("AZURE_FOUNDRY_RESOURCE", "res")
    cfg = llm_client.resolve_api_config()
    assert cfg.api_key == "fk" and "res.services.ai.azure.com" in cfg.base_url


def test_local_unreachable_without_model_raises(monkeypatch):
    monkeypatch.setenv("EPISTRACT_LLM_BASE_URL", "http://127.0.0.1:9")
    with pytest.raises(llm_client.LLMConfigError, match="EPISTRACT_LLM_MODEL"):
        llm_client.resolve_api_config()


def test_local_auto_pick_skips_embedding(fake_openai_server, monkeypatch):
    fake_openai_server.models = ["nomic-embed-text", "qwen2.5:7b"]
    monkeypatch.setenv("EPISTRACT_LLM_BASE_URL", fake_openai_server.base_url)
    assert llm_client.resolve_api_config().model == "qwen2.5:7b"
