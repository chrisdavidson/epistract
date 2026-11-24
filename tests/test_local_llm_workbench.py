"""Workbench support for a local OpenAI-compatible server (LOCAL-03, LOCAL-02)."""

from __future__ import annotations

import asyncio
import time

import httpx
import pytest

from examples.workbench import api_chat
from examples.workbench.api_chat import (
    LOCAL_PLACEHOLDER_KEY,
    _autodetect_local_model,
    _clear_local_models_cache,
    _resolve_api_config,
    active_provider,
    list_local_models,
)

_CLOUD_VARS = (
    "AZURE_FOUNDRY_API_KEY",
    "ANTHROPIC_FOUNDRY_API_KEY",
    "AZURE_FOUNDRY_BASE_URL",
    "ANTHROPIC_FOUNDRY_BASE_URL",
    "AZURE_FOUNDRY_RESOURCE",
    "ANTHROPIC_API_KEY",
    "OPENROUTER_API_KEY",
)
_MODEL = "Phi-3-mini-4k-instruct-q4.gguf"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for var in _CLOUD_VARS:
        monkeypatch.delenv(var, raising=False)
    _clear_local_models_cache()
    yield
    _clear_local_models_cache()


# ---------------------------------------------------------------------------
# Resolver
# ---------------------------------------------------------------------------


def test_local_resolves_from_base_url_only(monkeypatch):
    """LOCAL-03: only EPISTRACT_LLM_BASE_URL set -> local 4-tuple."""
    monkeypatch.setenv("EPISTRACT_LLM_BASE_URL", "http://h:9996")
    assert _resolve_api_config() == (
        LOCAL_PLACEHOLDER_KEY,
        "http://h:9996/v1/chat/completions",
        "",
        "local",
    )


def test_local_model_env_override_and_key(monkeypatch):
    monkeypatch.setenv("EPISTRACT_LLM_BASE_URL", "http://h:9996")
    monkeypatch.setenv("EPISTRACT_LLM_MODEL", "m")
    monkeypatch.setenv("EPISTRACT_LLM_API_KEY", "k")
    assert _resolve_api_config() == ("k", "http://h:9996/v1/chat/completions", "m", "local")
    assert _resolve_api_config(model_override="x")[2] == "x"


@pytest.mark.parametrize(
    "url",
    ["h:9996/v1/", "http://h:9996/v1/chat/completions", "HTTP://h:9996/V1"],
)
def test_local_url_normalisation(monkeypatch, url):
    monkeypatch.setenv("EPISTRACT_LLM_BASE_URL", url)
    assert _resolve_api_config()[1] == "http://h:9996/v1/chat/completions"


def test_local_url_rejects_non_http(monkeypatch):
    monkeypatch.setenv("EPISTRACT_LLM_BASE_URL", "ftp://h")
    with pytest.raises(RuntimeError):
        _resolve_api_config()


def test_local_url_strips_userinfo(monkeypatch):
    monkeypatch.setenv("EPISTRACT_LLM_BASE_URL", "http://user:pw@h:9996/v1")
    url = _resolve_api_config()[1]
    assert "user" not in url and "pw" not in url


def test_d02_base_url_wins_over_cloud_key(monkeypatch):
    """D-02: a set base URL outranks cloud keys and never leaks them."""
    monkeypatch.setenv("EPISTRACT_LLM_BASE_URL", "http://h:9996")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-cloud")
    key, _, _, provider = _resolve_api_config()
    assert provider == "local"
    assert key == LOCAL_PLACEHOLDER_KEY


def test_d02_switch_off_prefers_cloud(monkeypatch):
    monkeypatch.setattr(api_chat, "LOCAL_BASE_URL_WINS", False)
    monkeypatch.setenv("EPISTRACT_LLM_BASE_URL", "http://h:9996")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-cloud")
    assert _resolve_api_config()[3] == "anthropic"
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    assert _resolve_api_config()[3] == "local"


def test_forced_provider_openrouter(monkeypatch):
    monkeypatch.setenv("EPISTRACT_LLM_BASE_URL", "http://h:9996")
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    monkeypatch.setenv("EPISTRACT_LLM_PROVIDER", "openrouter")
    key, _, _, provider = _resolve_api_config()
    assert (key, provider) == ("or-key", "openrouter")


def test_forced_provider_errors(monkeypatch):
    monkeypatch.setenv("EPISTRACT_LLM_PROVIDER", "local")
    with pytest.raises(RuntimeError):
        _resolve_api_config()
    monkeypatch.setenv("EPISTRACT_LLM_PROVIDER", "bogus")
    with pytest.raises(RuntimeError):
        _resolve_api_config()


def test_no_config_unchanged():
    assert _resolve_api_config() == (None, "", "", "")


# ---------------------------------------------------------------------------
# active_provider
# ---------------------------------------------------------------------------


def test_active_provider_values(monkeypatch):
    assert active_provider() is None
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    assert active_provider() == "openrouter"
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    assert active_provider() == "anthropic"
    monkeypatch.setenv("AZURE_FOUNDRY_API_KEY", "k")
    monkeypatch.setenv("AZURE_FOUNDRY_RESOURCE", "r")
    assert active_provider() == "azure-foundry"
    monkeypatch.setenv("AZURE_FOUNDRY_BASE_URL", "https://gw")
    assert active_provider() == "azure-foundry-custom"
    monkeypatch.setenv("EPISTRACT_LLM_BASE_URL", "http://h:1")
    assert active_provider() == "local"


def test_active_provider_never_raises(monkeypatch):
    monkeypatch.setenv("AZURE_FOUNDRY_API_KEY", "k")  # no base url / resource
    assert active_provider() == "azure-foundry"
    monkeypatch.delenv("AZURE_FOUNDRY_API_KEY")
    monkeypatch.setenv("EPISTRACT_LLM_PROVIDER", "bogus")
    assert active_provider() is None
    monkeypatch.setenv("EPISTRACT_LLM_PROVIDER", "local")
    assert active_provider() is None


# ---------------------------------------------------------------------------
# Model listing
# ---------------------------------------------------------------------------


def _models_requests(server):
    return [r for r in server.requests if r["path"] == "/v1/models"]


def test_list_local_models_and_ttl_cache(fake_openai_server):
    url = f"{fake_openai_server.base_url}/v1/chat/completions"
    expected = [{"id": _MODEL, "label": _MODEL}]
    assert asyncio.run(list_local_models(url)) == expected
    assert asyncio.run(list_local_models(url)) == expected
    assert len(_models_requests(fake_openai_server)) == 1


def test_list_local_models_cache_expires(fake_openai_server, monkeypatch):
    url = fake_openai_server.base_url
    asyncio.run(list_local_models(url))
    real = time.monotonic()
    monkeypatch.setattr(api_chat.time, "monotonic", lambda: real + 31)
    asyncio.run(list_local_models(url))
    assert len(_models_requests(fake_openai_server)) == 2


def test_list_local_models_ignores_env_proxy(fake_openai_server, monkeypatch):
    """A local server is never reached through HTTP(S)_PROXY."""
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:9")
    monkeypatch.setenv("http_proxy", "http://127.0.0.1:9")
    monkeypatch.delenv("NO_PROXY", raising=False)
    monkeypatch.delenv("no_proxy", raising=False)
    assert asyncio.run(list_local_models(fake_openai_server.base_url))


def test_list_local_models_sends_key_only_when_set(fake_openai_server, monkeypatch):
    asyncio.run(list_local_models(fake_openai_server.base_url))
    assert "authorization" not in _models_requests(fake_openai_server)[0]["headers"]
    _clear_local_models_cache()
    monkeypatch.setenv("EPISTRACT_LLM_API_KEY", "k")
    asyncio.run(list_local_models(fake_openai_server.base_url))
    assert _models_requests(fake_openai_server)[1]["headers"]["authorization"] == "Bearer k"


def test_list_local_models_failure_raises(fake_openai_server):
    fake_openai_server.models_status = 500
    with pytest.raises(httpx.HTTPError):
        asyncio.run(list_local_models(fake_openai_server.base_url))


def test_autodetect_skips_non_chat_models(fake_openai_server):
    fake_openai_server.models = [
        "nomic-embed-text-v1.5",
        "bge-m3",
        "multilingual-e5-large",
        "some-rerank-model",
        "llama-3.1-8b",
    ]
    assert asyncio.run(_autodetect_local_model(fake_openai_server.base_url)) == "llama-3.1-8b"


def test_autodetect_returns_empty_on_failure(fake_openai_server):
    fake_openai_server.models_status = 500
    assert asyncio.run(_autodetect_local_model(fake_openai_server.base_url)) == ""
    fake_openai_server.models_status = 200
    _clear_local_models_cache()
    fake_openai_server.models = ["bge-m3"]
    assert asyncio.run(_autodetect_local_model(fake_openai_server.base_url)) == ""
