"""Local transport, error classification, retry policy and JSON extraction.

Covers LOCAL-05 (transport + typed errors + bounded retry) and LOCAL-06
(tolerant JSON extraction from small-model replies).
"""
from __future__ import annotations

import time

import httpx
import pytest

from core import llm_client
from core.llm_client import (
    ERR_FATAL,
    ERR_PER_ITEM,
    ERR_QUOTA,
    ERR_RATE_LIMIT,
    ERR_TRANSIENT,
    LLMCallError,
    LLMConfig,
    LLMFatalError,
    LLMQuotaError,
    LLMTransientError,
    LOCAL_PLACEHOLDER_KEY,
    call_llm,
    classify_error,
    extract_json_object,
)

FENCE = "`" * 3


# -- classify_error ---------------------------------------------------------
def test_classify_429_quota_by_headers():
    reset = str(int((time.time() + 6 * 3600) * 1000))
    h = {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": reset}
    assert classify_error(429, h, "slow down") == ERR_QUOTA


@pytest.mark.parametrize("body", [
    '{"error":{"message":"free-models-per-day"}}',
    "monthly quota exhausted",
    "daily limit reached",
])
def test_classify_429_quota_by_body(body):
    assert classify_error(429, {}, body) == ERR_QUOTA


def test_classify_429_transient():
    h = {"Retry-After": "1", "X-RateLimit-Remaining": "5"}
    assert classify_error(429, h, "") == ERR_RATE_LIMIT


def test_classify_429_reset_near_is_rate_limit():
    h = {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": str(int(time.time()) + 30)}
    assert classify_error(429, h, "") == ERR_RATE_LIMIT


def test_classify_429_long_retry_after_is_quota():
    assert classify_error(429, {"Retry-After": "3600"}, "") == ERR_QUOTA


def test_classify_fatal_statuses():
    body = "x is a rerank model and cannot be used with the chat/completions endpoint"
    assert classify_error(400, {}, body) == ERR_FATAL
    for status in (401, 402, 403, 404):
        assert classify_error(status, {}, "") == ERR_FATAL


def test_classify_context_size_is_per_item():
    assert classify_error(400, {}, "the request exceeds the available context size") == ERR_PER_ITEM
    assert classify_error(413, {}, "") == ERR_PER_ITEM


def test_classify_transient():
    for status in (500, 502, 503, 408, None):
        assert classify_error(status, {}, "") == ERR_TRANSIENT


def test_classify_headers_case_insensitive():
    reset = str(int((time.time() + 6 * 3600) * 1000))
    h = {"x-ratelimit-remaining": "0", "X-RATELIMIT-RESET": reset}
    assert classify_error(429, h, "") == ERR_QUOTA


# -- extract_json_object ----------------------------------------------------
def test_extract_json_variants():
    assert extract_json_object(f'{FENCE}json\n{{"a": 1}}\n{FENCE}') == {"a": 1}
    assert extract_json_object('Sure! {"a": 1} hope that helps }') == {"a": 1}
    assert extract_json_object('<think>x {y}</think>{"a": 2}') == {"a": 2}
    assert extract_json_object('{"a": {"b": 1}} {"c": 2}') == {"a": {"b": 1}}


@pytest.mark.parametrize("text", ["no json", "[1,2]", ""])
def test_extract_json_rejects(text):
    with pytest.raises(ValueError):
        extract_json_object(text)


# -- exceptions -------------------------------------------------------------
def test_exception_hierarchy_and_attrs():
    q = LLMQuotaError("q", reset_at=5.0)
    f = LLMFatalError("f", status=400)
    t = LLMTransientError("t", connect=True)
    for e in (q, f, t):
        assert isinstance(e, LLMCallError)
    assert q.reset_at == 5.0 and f.status == 400 and t.connect is True
    assert LLMTransientError("t").connect is False


# -- transport --------------------------------------------------------------
@pytest.fixture
def sleeps(monkeypatch):
    rec: list[float] = []
    monkeypatch.setattr(llm_client, "_sleep", rec.append)
    return rec


def _cfg(server, key=LOCAL_PLACEHOLDER_KEY):
    return LLMConfig(key, server.base_url + "/v1", "stub-model", "local", 4096)


def _chat_requests(server):
    return [r for r in server.requests if r["path"].endswith("/chat/completions")]


def test_local_call_returns_content_and_body_shape(fake_openai_server):
    fake_openai_server.queue_content("hello")
    out = call_llm("sys", "usr", config=_cfg(fake_openai_server), max_tokens=77,
                   temperature=0.1, effort="high")
    assert out == "hello"
    (req,) = _chat_requests(fake_openai_server)
    assert req["path"] == "/v1/chat/completions"
    body = req["json"]
    assert body["model"] == "stub-model"
    assert body["messages"] == [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "usr"},
    ]
    assert body["max_tokens"] == 77 and body["temperature"] == 0.1
    assert "effort" not in body and "output_config" not in body


def test_local_max_tokens_none_omits_field(fake_openai_server):
    call_llm("s", "u", config=_cfg(fake_openai_server), max_tokens=None)
    (req,) = _chat_requests(fake_openai_server)
    assert "max_tokens" not in req["json"]


def test_cloud_provider_rejects_max_tokens_none():
    cfg = LLMConfig("k", "https://openrouter.ai/api/v1", "m", "openrouter")
    with pytest.raises(ValueError):
        call_llm("s", "u", config=cfg, max_tokens=None)


def test_no_auth_header_for_placeholder_key(fake_openai_server):
    call_llm("s", "u", config=_cfg(fake_openai_server))
    (req,) = _chat_requests(fake_openai_server)
    assert "authorization" not in req["headers"]


def test_bearer_header_with_real_key(fake_openai_server):
    call_llm("s", "u", config=_cfg(fake_openai_server, key="sekrit-k"))
    (req,) = _chat_requests(fake_openai_server)
    assert req["headers"]["authorization"] == "Bearer sekrit-k"


def test_daily_429_raises_quota_without_retry(fake_openai_server, sleeps):
    fake_openai_server.queue_429_daily()
    with pytest.raises(LLMQuotaError) as ei:
        call_llm("s", "u", config=_cfg(fake_openai_server, key="sekrit-k"))
    assert len(_chat_requests(fake_openai_server)) == 1
    assert sleeps == []
    assert "sekrit-k" not in str(ei.value)
    assert ei.value.reset_at is not None


def test_transient_429_retries_with_retry_after(fake_openai_server, sleeps):
    fake_openai_server.queue_429_transient()
    fake_openai_server.queue_content("ok")
    assert call_llm("s", "u", config=_cfg(fake_openai_server)) == "ok"
    assert len(_chat_requests(fake_openai_server)) == 2
    assert sleeps == [1]


def test_retry_after_is_capped(fake_openai_server, sleeps):
    fake_openai_server.queue_status(500, {"error": "x"}, {"Retry-After": "20"})
    fake_openai_server.queue_content("ok")
    assert call_llm("s", "u", config=_cfg(fake_openai_server)) == "ok"
    assert all(s <= llm_client.RETRY_AFTER_CAP_S for s in sleeps)


def test_three_500s_raise_transient(fake_openai_server, sleeps):
    for _ in range(3):
        fake_openai_server.queue_status(500, {"error": "boom"})
    with pytest.raises(LLMTransientError):
        call_llm("s", "u", config=_cfg(fake_openai_server))
    assert len(_chat_requests(fake_openai_server)) == 3
    assert len(sleeps) == 2


def test_rerank_400_is_fatal_no_retry(fake_openai_server, sleeps):
    fake_openai_server.queue_400_rerank()
    with pytest.raises(LLMFatalError) as ei:
        call_llm("s", "u", config=_cfg(fake_openai_server))
    assert ei.value.status == 400
    assert len(_chat_requests(fake_openai_server)) == 1
    assert sleeps == []


def test_context_overflow_400_is_plain_per_item_error(fake_openai_server, sleeps):
    fake_openai_server.queue_status(
        400, {"error": {"message": "the request exceeds the available context size"}}
    )
    with pytest.raises(LLMCallError) as ei:
        call_llm("s", "u", config=_cfg(fake_openai_server))
    assert not isinstance(ei.value, (LLMFatalError, LLMQuotaError, LLMTransientError))
    assert len(_chat_requests(fake_openai_server)) == 1


def test_connection_refused_is_transient_connect(fake_openai_server, sleeps):
    cfg = _cfg(fake_openai_server)
    fake_openai_server.stop()
    with pytest.raises(LLMTransientError) as ei:
        call_llm("s", "u", config=cfg)
    assert ei.value.connect is True
    assert len(sleeps) == 2


def test_unexpected_200_bodies_are_call_errors(fake_openai_server):
    fake_openai_server.queue_status(200, "not json at all")
    fake_openai_server.queue_status(200, {"id": "x"})
    for _ in range(2):
        with pytest.raises(LLMCallError):
            call_llm("s", "u", config=_cfg(fake_openai_server))


def test_local_strips_fences(fake_openai_server):
    fake_openai_server.queue_content(f"{FENCE}json\n{{}}\n{FENCE}")
    assert call_llm("s", "u", config=_cfg(fake_openai_server)) == "{}"


# -- openrouter -------------------------------------------------------------
def _fake_openai(monkeypatch, exc):
    import openai

    seen: dict = {}

    class _Completions:
        def create(self, **kw):
            raise exc

    class _Chat:
        completions = _Completions()

    class _Client:
        chat = _Chat()

        def __init__(self, **kw):
            seen.update(kw)

    monkeypatch.setattr(openai, "OpenAI", _Client)
    return seen


def test_openrouter_max_retries_zero_and_quota_mapping(monkeypatch, sleeps):
    import openai

    resp = httpx.Response(
        429,
        headers={"X-RateLimit-Remaining": "0"},
        text="Rate limit exceeded: free-models-per-day",
        request=httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions"),
    )
    seen = _fake_openai(monkeypatch, openai.APIStatusError("429", response=resp, body=None))
    cfg = LLMConfig("k", "https://openrouter.ai/api/v1", "m", "openrouter")
    with pytest.raises(LLMQuotaError):
        call_llm("s", "u", config=cfg)
    assert seen["max_retries"] == 0
    assert sleeps == []


def test_openrouter_connection_error_is_transient(monkeypatch, sleeps):
    import openai

    req = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions")
    _fake_openai(monkeypatch, openai.APIConnectionError(request=req))
    cfg = LLMConfig("k", "https://openrouter.ai/api/v1", "m", "openrouter")
    with pytest.raises(LLMTransientError) as ei:
        call_llm("s", "u", config=cfg)
    assert ei.value.connect is True
    assert len(sleeps) == 2
