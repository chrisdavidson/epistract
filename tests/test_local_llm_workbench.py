"""Workbench support for a local OpenAI-compatible server (LOCAL-03, LOCAL-02)."""

from __future__ import annotations

import asyncio
import json
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


# ---------------------------------------------------------------------------
# Error messages
# ---------------------------------------------------------------------------

from examples.workbench.chat_errors import (  # noqa: E402
    _env_var_for,
    describe_exception,
    describe_provider_error,
    provider_label,
)

_DAILY_BODY = '{"error":{"message":"Rate limit exceeded: free-models-per-day"}}'


def test_local_label_and_env_var():
    label = provider_label("local", "http://h:9996/v1/chat/completions")
    assert label == "Local model server"
    assert _env_var_for(label) == "EPISTRACT_LLM_BASE_URL"
    assert provider_label("openrouter", "") == "OpenRouter"
    assert provider_label("anthropic", "https://api.anthropic.com/v1/messages") == "Anthropic"
    assert provider_label("anthropic", "https://gw/v1/messages") == "Azure AI Foundry"


def test_local_401_hint_mentions_api_key_var():
    info = describe_provider_error(401, "", provider_label="Local model server", model="m")
    assert "EPISTRACT_LLM_API_KEY" in info["hint"]
    assert "Local model server" in info["message"]


def test_daily_429_worded_as_daily_limit():
    info = describe_provider_error(
        429, _DAILY_BODY, provider_label="OpenRouter", model="x"
    )
    assert info["title"] == "Daily limit reached"
    assert "daily" in info["message"]


def test_daily_429_by_headers_includes_reset_time():
    reset_s = time.time() + 6 * 3600
    info = describe_provider_error(
        429,
        '{"error":{"message":"slow down"}}',
        provider_label="OpenRouter",
        model="x",
        headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": str(int(reset_s * 1000))},
    )
    assert info["title"] == "Daily limit reached"
    from datetime import datetime, timezone

    assert datetime.fromtimestamp(reset_s, tz=timezone.utc).strftime("%H:%M") in info["hint"]
    assert "UTC" in info["hint"]


def test_plain_429_keeps_rate_limited_wording():
    info = describe_provider_error(
        429,
        '{"error":{"message":"Too many requests"}}',
        provider_label="OpenRouter",
        model="x",
        headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": str(int((time.time() + 5) * 1000))},
    )
    assert info["title"] == "Rate limited"


def test_connect_error_local_hint_names_server():
    info = describe_exception(
        httpx.ConnectError("x"),
        provider_label="Local model server",
        model="m",
        base_url="http://h:9996/v1/chat/completions",
    )
    assert info["hint"] == "Is the server running at http://h:9996?"


def test_connect_error_without_base_url_keeps_generic_hint():
    info = describe_exception(
        httpx.ConnectError("x"), provider_label="OpenRouter", model="m"
    )
    assert "internet connection" in info["hint"]


# ---------------------------------------------------------------------------
# Streaming, /api/models and /api/health against the stub server
# ---------------------------------------------------------------------------


def _sse_events(resp) -> list[dict]:
    events = []
    for line in resp.text.splitlines():
        if line.startswith("data:"):
            try:
                events.append(json.loads(line[5:].strip()))
            except ValueError:
                pass
    return events


def _chat(client, **body):
    return client.post("/api/chat", json={"question": "hi", "history": [], **body})


def _completions(server):
    return [r for r in server.requests if r["path"] == "/v1/chat/completions"]


@pytest.fixture
def local_server(fake_openai_server, monkeypatch):
    monkeypatch.setenv("EPISTRACT_LLM_BASE_URL", fake_openai_server.base_url)
    return fake_openai_server


def test_chat_streams_local_answer_without_cloud_headers(client, local_server):
    """LOCAL-03: only the base URL set -> streamed answer, auto-detected model."""
    local_server.queue_sse(["Hel", "lo"])
    resp = _chat(client)
    assert resp.status_code == 200
    events = _sse_events(resp)
    text = "".join(e["content"] for e in events if e.get("type") == "text")
    assert text == "Hello"
    assert events[-1]["type"] == "done"
    assert not [e for e in events if e.get("type") == "error"]
    req = _completions(local_server)[0]
    assert req["json"]["model"] == _MODEL
    for header in ("authorization", "http-referer", "x-title"):
        assert header not in req["headers"]


def test_chat_sends_only_authorization_when_key_set(client, local_server, monkeypatch):
    monkeypatch.setenv("EPISTRACT_LLM_API_KEY", "k")
    local_server.queue_sse(["ok"])
    _chat(client)
    headers = _completions(local_server)[0]["headers"]
    assert headers["authorization"] == "Bearer k"
    assert "http-referer" not in headers and "x-title" not in headers


def test_d02_cloud_key_never_sent_to_local_server(client, local_server, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-cloud")
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-cloud")
    local_server.queue_sse(["ok"])
    _chat(client)
    req = _completions(local_server)[0]
    assert "authorization" not in req["headers"]
    assert "x-api-key" not in req["headers"]


def test_chat_local_has_no_max_tokens_unless_configured(client, local_server, monkeypatch):
    local_server.queue_sse(["a"])
    _chat(client)
    assert "max_tokens" not in _completions(local_server)[0]["json"]
    monkeypatch.setenv("EPISTRACT_LLM_MAX_TOKENS", "300")
    local_server.queue_sse(["a"])
    _chat(client)
    assert _completions(local_server)[1]["json"]["max_tokens"] == 300


def test_chat_openrouter_keeps_max_tokens(monkeypatch):
    captured = {}

    class _Resp:
        status_code = 200
        headers: dict = {}

        async def aiter_lines(self):
            yield "data: [DONE]"

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    class _Client:
        def __init__(self, **kw):
            captured["init"] = kw

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        def stream(self, method, url, **kw):
            captured["json"] = kw["json"]
            captured["headers"] = kw["headers"]
            return _Resp()

    monkeypatch.setattr(api_chat.httpx, "AsyncClient", _Client)

    async def drain():
        return [
            e
            async for e in api_chat._stream_openai_compat(
                "k", "https://openrouter.ai/api/v1/chat/completions", "m", "s", [], "openrouter"
            )
        ]

    asyncio.run(drain())
    assert captured["json"]["max_tokens"] == 4096
    assert captured["headers"]["HTTP-Referer"]
    assert captured["init"].get("trust_env", True) is True


def test_chat_request_model_is_forwarded(client, local_server):
    local_server.queue_sse(["a"])
    _chat(client, model="other-model")
    assert _completions(local_server)[0]["json"]["model"] == "other-model"


def test_chat_outbound_host_is_always_the_env_host(client, local_server):
    """T-11-11: a hostile model string cannot redirect the request."""
    local_server.queue_sse(["a"])
    _chat(client, model="http://evil.example/v1")
    reqs = _completions(local_server)
    assert reqs and reqs[0]["json"]["model"] == "http://evil.example/v1"


def test_chat_without_any_model_reports_env_var(client, local_server):
    local_server.models = []
    resp = _chat(client)
    errors = [e for e in _sse_events(resp) if e.get("type") == "error"]
    assert errors and "EPISTRACT_LLM_MODEL" in errors[0]["message"]
    assert not _completions(local_server)


def test_chat_unreachable_server_hint(client, monkeypatch):
    monkeypatch.setenv("EPISTRACT_LLM_BASE_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("EPISTRACT_LLM_MODEL", "m")
    errors = [e for e in _sse_events(_chat(client)) if e.get("type") == "error"]
    assert errors
    assert "Is the server running at http://127.0.0.1:9?" in errors[0]["hint"]
    assert "Local model server" in errors[0]["message"]


def test_chat_local_daily_429(client, local_server):
    local_server.queue_429_daily()
    errors = [e for e in _sse_events(_chat(client)) if e.get("type") == "error"]
    assert errors[0]["title"] == "Daily limit reached"
    assert "Local model server" in errors[0]["message"]


def test_chat_ignores_env_proxy_for_local(client, local_server, monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:9")
    monkeypatch.setenv("http_proxy", "http://127.0.0.1:9")
    monkeypatch.delenv("NO_PROXY", raising=False)
    monkeypatch.delenv("no_proxy", raising=False)
    local_server.queue_sse(["ok"])
    events = _sse_events(_chat(client))
    assert any(e.get("type") == "text" for e in events)


def test_models_endpoint_local(client, local_server):
    body = client.get("/api/models").json()
    assert body == {
        "provider": "local",
        "default_model": _MODEL,
        "models": [{"id": _MODEL, "label": _MODEL}],
    }


def test_models_endpoint_local_configured_default(client, local_server, monkeypatch):
    monkeypatch.setenv("EPISTRACT_LLM_MODEL", "chosen")
    assert client.get("/api/models").json()["default_model"] == "chosen"


def test_models_endpoint_local_degraded_when_server_down(client, monkeypatch):
    monkeypatch.setenv("EPISTRACT_LLM_BASE_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("EPISTRACT_LLM_MODEL", "m")
    resp = client.get("/api/models")
    assert resp.status_code == 200
    body = resp.json()
    assert body["provider"] == "local"
    assert body["degraded"] is True
    assert body["models"] == [{"id": "m", "label": "m"}]


def test_models_endpoint_never_leaks_key_or_url(client, local_server, monkeypatch):
    monkeypatch.setenv("EPISTRACT_LLM_API_KEY", "super-secret")
    text = client.get("/api/models").text + client.get("/api/health").text
    assert "super-secret" not in text
    assert local_server.base_url not in text


def test_health_reports_local(client, local_server):
    body = client.get("/api/health").json()
    assert body["llm_provider"] == "local"
    assert body["has_api_key"] is True


def test_health_and_models_unchanged_for_anthropic(client, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk")
    health = client.get("/api/health").json()
    assert (health["llm_provider"], health["has_api_key"]) == ("anthropic", True)
    models = client.get("/api/models").json()
    assert models["provider"] == "anthropic"
    assert models["models"] == api_chat.PROVIDER_MODELS["anthropic"]


def test_health_and_models_with_no_provider(client):
    health = client.get("/api/health").json()
    assert (health["llm_provider"], health["has_api_key"]) == (None, False)
    assert client.get("/api/models").json() == {
        "provider": None,
        "default_model": None,
        "models": [],
    }


def test_models_endpoint_degraded_without_model_has_no_empty_id(client, monkeypatch):
    monkeypatch.setenv("EPISTRACT_LLM_BASE_URL", "http://127.0.0.1:9")
    monkeypatch.delenv("EPISTRACT_LLM_MODEL", raising=False)
    body = client.get("/api/models").json()
    assert body["degraded"] is True
    assert body["models"] == []
