"""Map LLM provider errors to friendly, actionable chat messages.

Pure functions (no network, no file I/O). Provider error bodies and
exceptions go in; a dict with ``title``, ``message``, ``hint``, ``detail``
and ``status`` comes out, ready to be sent to the browser as an SSE event.

Usage:
    info = describe_provider_error(
        403, body_text, provider_label="OpenRouter", model="vendor/model"
    )
    yield error_event(info)
"""

from __future__ import annotations

import json
import re

import httpx

DETAIL_LIMIT = 300

_TOO_LARGE_RE = re.compile(r"context|token|length|too long|too large", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def provider_label(provider: str, base_url: str) -> str:
    """Return the human-readable provider name for a resolved API config."""
    if provider == "openrouter":
        return "OpenRouter"
    if provider == "anthropic" and "anthropic.com" in base_url:
        return "Anthropic"
    return "Azure AI Foundry"


def _env_var_for(label: str) -> str:
    """Return the env var that holds the API key for a provider label."""
    if label == "OpenRouter":
        return "OPENROUTER_API_KEY"
    if label == "Anthropic":
        return "ANTHROPIC_API_KEY"
    return "AZURE_FOUNDRY_API_KEY"


def _parse_body(body: str) -> tuple[str, str | None, dict]:
    """Extract (message, anthropic_error_type, openrouter_metadata) from a body."""
    text = (body or "").strip()
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return text, None, {}
    if isinstance(data, dict):
        err = data.get("error")
        if isinstance(err, dict):
            message = err.get("message")
            etype = err.get("type") if data.get("type") == "error" else None
            metadata = err.get("metadata")
            if not isinstance(metadata, dict):
                metadata = {}
            if isinstance(message, str):
                return message, etype if isinstance(etype, str) else None, metadata
        elif isinstance(err, str):
            return err, None, {}
    return text, None, {}


def _truncate(text: str) -> str:
    if len(text) > DETAIL_LIMIT:
        return text[:DETAIL_LIMIT] + "…"
    return text


def _info(title: str, message: str, hint: str, detail: str, status: int | None) -> dict:
    return {
        "title": title,
        "message": message,
        "hint": hint,
        "detail": detail,
        "status": status,
    }


# ---------------------------------------------------------------------------
# Public mapping functions
# ---------------------------------------------------------------------------


def describe_provider_error(
    status: int | None, body: str, *, provider_label: str, model: str
) -> dict:
    """Describe an HTTP or in-stream provider error in plain language."""
    label = provider_label
    msg, etype, meta = _parse_body(body)
    prefix = f"HTTP {status} from {label}" if status is not None else label
    detail = _truncate(f"{prefix} (model: {model}): {msg}")

    def make(title: str, message: str, hint: str) -> dict:
        return _info(title, message, hint, detail, status)

    if status == 401 or etype == "authentication_error":
        return make(
            "API key not accepted",
            f"{label} rejected the API key.",
            f"Check that {_env_var_for(label)} holds a valid, active {label} key, "
            "then restart the workbench.",
        )
    if status == 402:
        return make(
            "Out of credits",
            f"Your {label} account has no credits left for this request.",
            f"Add credits to your {label} account or pick a free model in the model picker.",
        )
    if status == 403 and (
        meta.get("scope") == "key_limit" or "limit_source" in meta or "limit" in msg.lower()
    ):
        if label == "OpenRouter":
            hint = (
                "Raise or remove the key's limit at "
                "https://openrouter.ai/settings/keys, or choose a free model "
                "from the model picker."
            )
        else:
            hint = (
                f"Raise the limit in the {label} console, or choose another "
                "model from the model picker."
            )
        return make(
            "Spending limit reached for this API key",
            "The key has hit its spending limit, so the model could not run.",
            hint,
        )
    if status == 403 or etype == "permission_error":
        return make(
            "This model isn't available to your key",
            f"Your {label} key is not allowed to use the model '{model}'.",
            "Choose a different model in the model picker.",
        )
    if status == 404 or etype == "not_found_error":
        return make(
            "Model not found",
            f"{label} doesn't recognise the model '{model}'.",
            "Choose another model in the model picker.",
        )
    if ((status in (400, 413)) and _TOO_LARGE_RE.search(msg)) or (etype == "request_too_large"):
        return make(
            "Question is too large for this model",
            "The question plus the knowledge graph context exceeded the model's limit.",
            "Try a shorter question or a model with a larger context window.",
        )
    if status == 400 or etype == "invalid_request_error":
        return make(
            "The provider rejected the request",
            f"{label} could not process this request.",
            "Retry, or choose another model. See technical details.",
        )
    if status in (408, 504):
        return make(
            "The model took too long to respond",
            f"{label} did not answer in time.",
            "Try again, or choose a faster model.",
        )
    if status == 429 or etype == "rate_limit_error":
        return make(
            "Rate limited",
            f"{label} is limiting how many requests this key or model can make.",
            "Wait a moment and retry. Free models are often rate-limited, "
            "so you may also pick another model.",
        )
    if status in (500, 502, 503, 529) or etype in ("overloaded_error", "api_error"):
        return make(
            "The model provider is having trouble",
            f"{label} reported a temporary problem.",
            "This is on the provider's side. Retry in a minute or choose another model.",
        )
    return make(
        "The model provider returned an error",
        f"{label} returned an unexpected error.",
        "Retry, or choose another model. See technical details.",
    )


def describe_exception(exc: BaseException, *, provider_label: str, model: str) -> dict:
    """Describe a client-side exception (timeout, connection failure, other)."""
    label = provider_label
    text = str(exc)
    name = type(exc).__name__
    detail = _truncate(f"{label} (model: {model}): {name + ': ' + text if text else name}")
    if isinstance(exc, httpx.TimeoutException):
        return _info(
            "The model took too long to respond",
            f"{label} did not answer in time.",
            "Try again, or choose a faster model.",
            detail,
            None,
        )
    if isinstance(exc, (httpx.ConnectError, httpx.NetworkError)):
        return _info(
            "Couldn't reach the model provider",
            f"The workbench could not connect to {label}.",
            "Check your internet connection and the configured base URL.",
            detail,
            None,
        )
    return _info(
        "Something went wrong talking to the model",
        "An unexpected error interrupted the request.",
        "Retry. See technical details.",
        detail,
        None,
    )


def error_event(info: dict) -> dict:
    """Wrap an error description as an SSE event dict."""
    payload = {
        "type": "error",
        "title": info["title"],
        "message": info["message"],
        "hint": info["hint"],
        "detail": info["detail"],
        "status": info["status"],
        "content": f"{info['title']}: {info['message']} {info['hint']}",
    }
    return {"data": json.dumps(payload)}
