"""Tests for friendly workbench chat error mapping and rendering (ERR-01..03)."""

from __future__ import annotations

import json

import httpx
import pytest

from examples.workbench.chat_errors import (
    describe_exception,
    describe_provider_error,
    error_event,
    provider_label,
)

OR_LIMIT_BODY = json.dumps(
    {
        "error": {
            "message": (
                "Key limit exceeded (total limit). "
                "Manage it using https://openrouter.ai/settings/keys"
            ),
            "code": 403,
            "metadata": {
                "limit_source": "openrouter_key_limit",
                "scope": "key_limit",
            },
        }
    }
)
OR_HARNESS_BODY = json.dumps(
    {
        "error": {
            "message": "anthropic/claude-x is only available on agentic harnesses ...",
            "code": 403,
        }
    }
)
ANTH_AUTH_BODY = json.dumps(
    {
        "type": "error",
        "error": {"type": "authentication_error", "message": "invalid x-api-key"},
    }
)
ANTH_OVERLOADED_BODY = json.dumps(
    {
        "type": "error",
        "error": {"type": "overloaded_error", "message": "Overloaded"},
    }
)
TOO_LONG_BODY = json.dumps(
    {"error": {"message": "prompt is too long: 250000 tokens > 200000 maximum"}}
)

MODEL = "vendor/some-model"

# (status, body, label, expected title, hint substrings)
CASES = [
    (
        403,
        OR_LIMIT_BODY,
        "OpenRouter",
        "Spending limit reached for this API key",
        ["openrouter.ai/settings/keys", "model picker"],
    ),
    (
        403,
        OR_HARNESS_BODY,
        "OpenRouter",
        "This model isn't available to your key",
        ["model picker"],
    ),
    (401, "{}", "OpenRouter", "API key not accepted", ["OPENROUTER_API_KEY", "restart"]),
    (401, "{}", "Anthropic", "API key not accepted", ["ANTHROPIC_API_KEY", "restart"]),
    (
        401,
        "{}",
        "Azure AI Foundry",
        "API key not accepted",
        ["AZURE_FOUNDRY_API_KEY", "restart"],
    ),
    (401, ANTH_AUTH_BODY, "Anthropic", "API key not accepted", ["ANTHROPIC_API_KEY"]),
    (None, ANTH_AUTH_BODY, "Anthropic", "API key not accepted", ["restart"]),
    (402, "{}", "OpenRouter", "Out of credits", ["credits"]),
    (404, "{}", "OpenRouter", "Model not found", ["model"]),
    (429, "{}", "OpenRouter", "Rate limited", ["retry"]),
    (503, "{}", "OpenRouter", "The model provider is having trouble", ["retry"]),
    (
        None,
        ANTH_OVERLOADED_BODY,
        "Anthropic",
        "The model provider is having trouble",
        ["retry"],
    ),
    (
        400,
        TOO_LONG_BODY,
        "Anthropic",
        "Question is too large for this model",
        ["shorter"],
    ),
    (
        400,
        json.dumps({"error": {"message": "bad param"}}),
        "Anthropic",
        "The provider rejected the request",
        ["retry"],
    ),
    (504, "{}", "OpenRouter", "The model took too long to respond", ["try again"]),
    (
        502,
        "<html>Bad Gateway</html>",
        "OpenRouter",
        "The model provider is having trouble",
        ["retry"],
    ),
    (418, "teapot", "OpenRouter", "The model provider returned an error", ["retry"]),
]


@pytest.mark.unit
@pytest.mark.parametrize("status,body,label,title,hint_bits", CASES)
def test_describe_provider_error_table(status, body, label, title, hint_bits):
    info = describe_provider_error(status, body, provider_label=label, model=MODEL)
    assert info["title"] == title, f"Expected {title!r}, got {info['title']!r}"
    for bit in hint_bits:
        assert bit.lower() in info["hint"].lower(), f"{bit!r} not in {info['hint']!r}"
    assert info["message"]
    assert info["status"] == status
    event = json.loads(error_event(info)["data"])
    assert not event["content"].startswith("API error")


@pytest.mark.unit
def test_key_limit_detail_and_message():
    info = describe_provider_error(403, OR_LIMIT_BODY, provider_label="OpenRouter", model=MODEL)
    for bit in ("403", "OpenRouter", MODEL, "Key limit exceeded"):
        assert bit in info["detail"], f"{bit!r} missing from {info['detail']!r}"


@pytest.mark.unit
def test_not_found_message_names_model():
    info = describe_provider_error(404, "{}", provider_label="OpenRouter", model=MODEL)
    assert MODEL in info["message"]


@pytest.mark.unit
def test_detail_without_status_has_no_http():
    info = describe_provider_error(
        None, ANTH_OVERLOADED_BODY, provider_label="Anthropic", model=MODEL
    )
    assert "HTTP" not in info["detail"]
    assert "Overloaded" in info["detail"]


@pytest.mark.unit
def test_non_json_body_detail():
    info = describe_provider_error(
        502, "<html>Bad Gateway</html>", provider_label="OpenRouter", model=MODEL
    )
    assert "Bad Gateway" in info["detail"]


@pytest.mark.unit
def test_detail_truncated():
    info = describe_provider_error(500, "x" * 5000, provider_label="OpenRouter", model=MODEL)
    assert len(info["detail"]) <= 301


@pytest.mark.unit
def test_describe_exception_timeout():
    info = describe_exception(httpx.ConnectTimeout(""), provider_label="OpenRouter", model=MODEL)
    assert info["title"] == "The model took too long to respond"
    assert info["message"].strip()
    assert info["detail"].strip()


@pytest.mark.unit
def test_describe_exception_connect_error():
    info = describe_exception(httpx.ConnectError("boom"), provider_label="OpenRouter", model=MODEL)
    assert info["title"] == "Couldn't reach the model provider"


@pytest.mark.unit
def test_describe_exception_generic():
    info = describe_exception(ValueError(), provider_label="OpenRouter", model=MODEL)
    assert info["title"] == "Something went wrong talking to the model"
    assert "ValueError" in info["detail"]


@pytest.mark.unit
def test_error_event_shape():
    info = describe_provider_error(429, "{}", provider_label="OpenRouter", model=MODEL)
    ev = error_event(info)
    assert list(ev.keys()) == ["data"]
    data = json.loads(ev["data"])
    assert data["type"] == "error"
    for key in ("title", "message", "hint", "detail", "status"):
        assert key in data
    assert data["content"] == f"{data['title']}: {data['message']} {data['hint']}"


@pytest.mark.unit
def test_provider_label():
    assert provider_label("openrouter", "https://openrouter.ai/api") == "OpenRouter"
    assert provider_label("anthropic", "https://api.anthropic.com/v1/messages") == "Anthropic"
    assert (
        provider_label("anthropic", "https://res.services.ai.azure.com/anthropic/v1/messages")
        == "Azure AI Foundry"
    )
