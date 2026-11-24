"""Local transport, error classification, retry policy and JSON extraction.

Covers LOCAL-05 (transport + typed errors + bounded retry) and LOCAL-06
(tolerant JSON extraction from small-model replies).
"""
from __future__ import annotations

import time

import pytest

from core.llm_client import (
    ERR_FATAL,
    ERR_PER_ITEM,
    ERR_QUOTA,
    ERR_RATE_LIMIT,
    ERR_TRANSIENT,
    LLMCallError,
    LLMFatalError,
    LLMQuotaError,
    LLMTransientError,
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
