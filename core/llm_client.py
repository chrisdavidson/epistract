"""Synchronous LLM client with provider auto-detection.

Uses the same provider priority as `examples/workbench/api_chat._resolve_api_config()`
(Azure Foundry → Anthropic direct → OpenRouter), plus a `local` provider for any
OpenAI-compatible server (llama.cpp, Ollama, vLLM, LM Studio) selected by
`EPISTRACT_LLM_BASE_URL`, which takes priority over the cloud keys
(`EPISTRACT_LLM_PROVIDER` forces a specific provider). It returns a sync call path
for pipeline scripts like `core/label_epistemic.py`.

The two implementations are deliberately independent: `examples/` is the consumer
layer and depends on core's *output*, not its code (see CLAUDE.md §Layers). They are
NOT a shared abstraction, and an earlier docstring claiming this module "mirrors"
that one was wrong — the OpenRouter defaults had silently diverged. If you change a
default here, change it there too; the model constants below are named so a grep for
`DEFAULT_` finds both call sites.

Callers should import `resolve_api_config()` + `call_llm()` and handle the
`LLMConfigError` / `LLMCallError` exceptions they raise.
"""
from __future__ import annotations

import json
import math
import os
import re
import sys
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from urllib.parse import urlsplit

# ---------------------------------------------------------------------------
# Model defaults
# ---------------------------------------------------------------------------
# Keep in sync with PROVIDER_MODELS and the defaults in
# examples/workbench/api_chat.py. See the module docstring for why these are
# duplicated rather than shared.
DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-5"
DEFAULT_OPENROUTER_MODEL = "anthropic/claude-sonnet-4.6"

# Foundry is a deployment NAME registered in Azure AI Studio, not an Anthropic
# model id — it is whatever the operator called their deployment. Changing this
# default would break every existing install whose Azure deployment is named
# `claude-sonnet-4-6`, so it is intentionally left alone. Operators point it at
# a newer model with AZURE_FOUNDRY_DEPLOYMENT.
DEFAULT_FOUNDRY_DEPLOYMENT = "claude-sonnet-4-6"

# Sent as the api_key of a keyless local server; the transport omits the
# Authorization header when the key equals this value.
LOCAL_PLACEHOLDER_KEY = "local-no-key"

# When True, EPISTRACT_LLM_BASE_URL wins over Foundry/Anthropic/OpenRouter keys.
# When False, it is only used after those find no key; EPISTRACT_LLM_PROVIDER
# still overrides either way.
LOCAL_BASE_URL_WINS = True

VALID_PROVIDERS = ("local", "anthropic", "openrouter", "foundry")


class LLMConfigError(RuntimeError):
    """Raised when credentials are set but incomplete (e.g., Foundry key without endpoint)."""


class LLMCallError(RuntimeError):
    """Raised when the LLM call itself fails."""


class LLMQuotaError(LLMCallError):
    """A daily/monthly quota is exhausted; retrying will not help."""

    def __init__(self, message: str, reset_at: float | None = None):
        super().__init__(message)
        self.reset_at = reset_at  # epoch seconds, when known


class LLMFatalError(LLMCallError):
    """A deterministic failure (bad model, auth, endpoint); retrying cannot help."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class LLMTransientError(LLMCallError):
    """A retryable failure (rate limit, 5xx, timeout, connection problem)."""

    def __init__(self, message: str, connect: bool = False, retryable: bool = True):
        super().__init__(message)
        self.connect = connect
        self.retryable = retryable  # False: transient, but re-sending won't help


class _RateLimited(LLMTransientError):
    """Transient 429 carrying the server's Retry-After hint."""

    def __init__(self, message: str, retry_after: float | None = None):
        super().__init__(message)
        self.retry_after = retry_after


# classify_error() results.
ERR_QUOTA = "quota"
ERR_RATE_LIMIT = "rate_limit"
ERR_FATAL = "fatal"
ERR_PER_ITEM = "per_item"
ERR_TRANSIENT = "transient"

_QUOTA_RE = re.compile(
    r"per-day|per day|daily|quota|free-models-per-day"
    r"|insufficient[\w\s-]{0,20}(?:credit|quota|balance|fund)",
    re.I,
)
_CONTEXT_RE = re.compile(
    r"too long|exceed|too large|maximum.*tokens"
    r"|context[\w\s-]{0,20}(?:length|window|size|exceed|too long|maximum)",
    re.I,
)

# A 429 whose reset is further away than this is a quota, not a rate limit.
QUOTA_RESET_HORIZON_S = 120
# Retry-After up to this is a transient rate limit (we wait it out); above it
# the 429 is treated as a quota and fails fast with the reset time.
RETRY_AFTER_CAP_S = 60
RETRY_ANNOUNCE_S = 5  # waits at least this long are announced on stderr
RETRY_MAX_ATTEMPTS = 3
RETRY_BACKOFF_S = (2.0, 4.0, 8.0)
_ERROR_EXCERPT_CHARS = 300

# Indirection so tests can record sleeps instead of waiting.
_sleep = time.sleep


@dataclass(frozen=True)
class LLMConfig:
    api_key: str
    base_url: str  # For anthropic-native: full /v1/messages URL. For OpenRouter: /v1 base.
    model: str
    provider: str  # "anthropic" | "openrouter" | "local"
    context_window: int | None = None  # local provider only; None = unknown


def _ensure_messages_suffix(url: str) -> str:
    """For anthropic-native gateways: ensure URL ends with /v1/messages."""
    url = url.rstrip("/")
    if url.endswith("/v1/messages"):
        return url
    if url.endswith("/v1"):
        return url + "/messages"
    return url + "/v1/messages"


def normalise_base_url(url: str) -> str:
    """Return the OpenAI-compatible API base (``<root>/v1``) for a user-supplied URL.

    Accepts ``host:port``, ``http://host:port``, ``.../v1`` and
    ``.../v1/chat/completions``. Userinfo is stripped; only http(s) is allowed.
    """
    raw = (url or "").strip()
    if not raw:
        raise LLMConfigError("EPISTRACT_LLM_BASE_URL is empty")
    if "://" not in raw:
        raw = "http://" + raw
    parts = urlsplit(raw)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise LLMConfigError(
            f"EPISTRACT_LLM_BASE_URL must be an http(s) URL, got scheme "
            f"{parts.scheme!r}"
        )
    host = parts.hostname
    if ":" in host:  # IPv6 literal
        host = f"[{host}]"
    try:
        port = parts.port
    except ValueError:
        raise LLMConfigError(
            "EPISTRACT_LLM_BASE_URL has an invalid port (expected 0-65535)"
        ) from None
    if port is not None:
        host = f"{host}:{port}"
    path = parts.path.rstrip("/")
    for suffix in ("/chat/completions", "/completions", "/models"):
        if path.lower().endswith(suffix):
            path = path[: -len(suffix)].rstrip("/")
            break
    if path.lower().endswith("/v1"):
        path = path[: -len("/v1")]
    return f"{parts.scheme}://{host}{path}/v1"


def _resolve_foundry() -> LLMConfig | None:
    foundry_key = os.environ.get("AZURE_FOUNDRY_API_KEY") or os.environ.get(
        "ANTHROPIC_FOUNDRY_API_KEY"
    )
    if not foundry_key:
        return None
    custom_base = (
        os.environ.get("AZURE_FOUNDRY_BASE_URL")
        or os.environ.get("ANTHROPIC_FOUNDRY_BASE_URL")
        or ""
    ).strip()
    resource = os.environ.get("AZURE_FOUNDRY_RESOURCE", "").strip()
    deployment = (
        os.environ.get("AZURE_FOUNDRY_DEPLOYMENT")
        or os.environ.get("ANTHROPIC_FOUNDRY_DEPLOYMENT")
        or DEFAULT_FOUNDRY_DEPLOYMENT
    )
    if custom_base:
        base_url = _ensure_messages_suffix(custom_base)
    elif resource:
        base_url = f"https://{resource}.services.ai.azure.com/anthropic/v1/messages"
    else:
        raise LLMConfigError(
            "Foundry API key is set but neither AZURE_FOUNDRY_BASE_URL "
            "(or ANTHROPIC_FOUNDRY_BASE_URL) nor AZURE_FOUNDRY_RESOURCE "
            "is configured. Set one and retry, or unset the key to fall "
            "back to ANTHROPIC_API_KEY / OPENROUTER_API_KEY."
        )
    return LLMConfig(foundry_key, base_url, deployment, "anthropic")


def _resolve_anthropic() -> LLMConfig | None:
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
    if not anthropic_key:
        return None
    return LLMConfig(
        anthropic_key,
        "https://api.anthropic.com/v1/messages",
        DEFAULT_ANTHROPIC_MODEL,
        "anthropic",
    )


def _resolve_openrouter() -> LLMConfig | None:
    openrouter_key = os.environ.get("OPENROUTER_API_KEY")
    if not openrouter_key:
        return None
    return LLMConfig(
        openrouter_key,
        "https://openrouter.ai/api/v1",
        os.environ.get("OPENROUTER_MODEL", DEFAULT_OPENROUTER_MODEL),
        "openrouter",
    )


# (api_base, model) pairs already announced on stderr (cleared by llm_local.clear_cache).
_ANNOUNCED_MODELS: set = set()


def _resolve_local() -> LLMConfig | None:
    """Local OpenAI-compatible server from EPISTRACT_LLM_* (None when no base URL)."""
    raw_url = os.environ.get("EPISTRACT_LLM_BASE_URL", "").strip()
    if not raw_url:
        return None
    from .llm_local import list_models, pick_chat_model, probe_context

    api_base = normalise_base_url(raw_url)
    real_key = os.environ.get("EPISTRACT_LLM_API_KEY", "").strip() or None
    model = os.environ.get("EPISTRACT_LLM_MODEL", "").strip()
    if not model:
        try:
            ids = [m["id"] for m in list_models(api_base, real_key)]
        except LLMCallError as e:
            raise LLMConfigError(
                f"could not determine a chat model at {api_base}; set "
                f"EPISTRACT_LLM_MODEL ({e})"
            ) from e
        model = pick_chat_model(ids) or ""
        if not model:
            raise LLMConfigError(
                f"could not determine a chat model at {api_base}; set "
                "EPISTRACT_LLM_MODEL (no chat-capable model is served)"
            )
        if (api_base, model) not in _ANNOUNCED_MODELS:
            _ANNOUNCED_MODELS.add((api_base, model))
            print(f"[epistract] local LLM model: {model} ({api_base})", file=sys.stderr)
    return LLMConfig(
        real_key or LOCAL_PLACEHOLDER_KEY,
        api_base,
        model,
        "local",
        probe_context(api_base, model, real_key),
    )


_MISSING_HINT = {
    "local": "EPISTRACT_LLM_BASE_URL",
    "anthropic": "ANTHROPIC_API_KEY (or AZURE_FOUNDRY_API_KEY for a gateway)",
    "openrouter": "OPENROUTER_API_KEY",
    "foundry": "AZURE_FOUNDRY_API_KEY with AZURE_FOUNDRY_BASE_URL or AZURE_FOUNDRY_RESOURCE",
}


def resolve_api_config() -> LLMConfig | None:
    """Return configured LLMConfig, or None when no credentials are present.

    Priority: EPISTRACT_LLM_PROVIDER (explicit, fail-loud) → local
    (EPISTRACT_LLM_BASE_URL, see LOCAL_BASE_URL_WINS) → Azure Foundry (Azure AI
    Foundry or custom Anthropic gateway) → Anthropic direct → OpenRouter.
    Raises LLMConfigError when Foundry key is set but endpoint config is
    missing, or when a forced provider lacks its credentials (never silently
    falls through).
    """
    forced = os.environ.get("EPISTRACT_LLM_PROVIDER", "").strip().lower()
    if forced:
        if forced not in VALID_PROVIDERS:
            raise LLMConfigError(
                f"EPISTRACT_LLM_PROVIDER={forced!r} is not one of "
                f"{', '.join(VALID_PROVIDERS)}"
            )
        resolver = {
            "local": _resolve_local,
            "anthropic": lambda: _resolve_anthropic() or _resolve_foundry(),
            "openrouter": _resolve_openrouter,
            "foundry": _resolve_foundry,
        }[forced]
        cfg = resolver()
        if cfg is None:
            raise LLMConfigError(
                f"EPISTRACT_LLM_PROVIDER={forced} but {_MISSING_HINT[forced]} "
                "is not set"
            )
        return cfg

    if LOCAL_BASE_URL_WINS:
        cfg = _resolve_local()
        if cfg is not None:
            return cfg

    for resolver in (_resolve_foundry, _resolve_anthropic, _resolve_openrouter):
        cfg = resolver()
        if cfg is not None:
            return cfg

    if not LOCAL_BASE_URL_WINS:
        return _resolve_local()
    return None


def call_llm(
    system: str,
    user: str,
    *,
    config: LLMConfig | None = None,
    max_tokens: int | None = 4096,
    temperature: float = 0.3,
    effort: str | None = None,
    timeout: float = 120.0,
) -> str:
    """Make a single synchronous LLM call and return the assistant text.

    Args:
        system: System prompt (domain persona + graph context).
        user: User message (the narrator task).
        config: Optional pre-resolved config. If None, calls resolve_api_config().
        max_tokens: Output token cap; ``None`` (local provider only) omits the
            field so the server bounds the reply by its own context window. On current Anthropic models this budget is
            shared with thinking tokens, so leave headroom above the expected
            answer length or the response truncates mid-output.
        temperature: OpenRouter path only — see below. 0.0 = deterministic,
            0.3 = light variation (default).
        effort: Anthropic path only. One of "low" | "medium" | "high" | "xhigh"
            | "max", sent as output_config.effort. This is the current control
            for reasoning depth and token spend; it is the replacement for
            temperature on the Anthropic-native path.
        timeout: Request timeout in seconds.

    Note on `temperature`:
        Current Anthropic models (Opus 5, Sonnet 5, Opus 4.8, Opus 4.7) removed
        temperature/top_p/top_k and reject them with HTTP 400, so the
        Anthropic-native path does NOT send it. It is still honoured on the
        OpenRouter path, which is OpenAI-compatible and may route to non-Anthropic
        models where the parameter is meaningful. Callers wanting deterministic
        behaviour on Anthropic should pass effort="low" and tighten the prompt.

    Returns:
        Assistant-generated text (already stripped of markdown fences).

    Raises:
        LLMConfigError: credentials missing or incomplete.
        LLMQuotaError: daily/monthly quota exhausted (never retried).
        LLMFatalError: deterministic failure such as a bad model or auth (never retried).
        LLMTransientError: rate limit, 5xx, timeout or connection failure that
            persisted through the bounded retries.
        LLMCallError: any other failure, including a per-item context overflow.
    """
    if config is None:
        config = resolve_api_config()
    if config is None:
        raise LLMConfigError(
            "No API key found. Set one of: AZURE_FOUNDRY_API_KEY (with "
            "AZURE_FOUNDRY_BASE_URL or AZURE_FOUNDRY_RESOURCE); "
            "ANTHROPIC_API_KEY; OPENROUTER_API_KEY; "
            "EPISTRACT_LLM_BASE_URL (local OpenAI-compatible server)."
        )

    if config.provider == "local":
        return _call_local(config, system, user, max_tokens, temperature, timeout)
    if max_tokens is None:
        raise ValueError("max_tokens=None is only valid for the local provider")
    if config.provider == "anthropic":
        return _call_anthropic(config, system, user, max_tokens, effort, timeout)
    return _call_openrouter(config, system, user, max_tokens, temperature, timeout)


def _call_anthropic(
    config: LLMConfig,
    system: str,
    user: str,
    max_tokens: int,
    effort: str | None,
    timeout: float,
) -> str:
    """Call Anthropic-native endpoint (direct API or Foundry gateway) via httpx.

    Deliberately does NOT send `temperature`. Opus 5, Sonnet 5, Opus 4.8 and
    Opus 4.7 removed temperature/top_p/top_k and reject a non-default value with
    HTTP 400 — sending it would break every call on a current model. Omitting the
    parameter is accepted by older models too, so this is safe across the board.
    Reasoning depth is controlled by `effort` instead.
    """
    try:
        import httpx
    except ImportError as e:
        raise LLMCallError("httpx is required for anthropic provider") from e

    headers = {
        "x-api-key": config.api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    payload: dict = {
        "model": config.model,
        "max_tokens": max_tokens,
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }
    if effort:
        payload["output_config"] = {"effort": effort}
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(config.base_url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPError as e:
        raise LLMCallError(f"Anthropic API error: {e}") from e
    except ValueError as e:  # JSON decode
        raise LLMCallError(f"Anthropic API returned non-JSON: {e}") from e

    # Anthropic returns content as list of blocks
    blocks = data.get("content") or []
    parts = [b.get("text", "") for b in blocks if b.get("type") == "text"]
    return _strip_fences("".join(parts))


def _excerpt(body: str | None) -> str:
    return (body or "").strip().replace("\n", " ")[:_ERROR_EXCERPT_CHARS]


def _error_for_status(
    status: int,
    headers: Mapping[str, str] | None,
    body: str | None,
    label: str,
    base_url: str,
) -> LLMCallError:
    """Build the typed exception for a non-2xx response (no headers/keys leaked)."""
    kind = classify_error(status, headers, body)
    msg = f"{label} {base_url} returned HTTP {status}: {_excerpt(body)}"
    if kind == ERR_QUOTA:
        reset = _reset_at(headers)
        if reset is None:
            ra = _retry_after(headers)
            if ra is not None:
                reset = time.time() + ra
        if reset is not None:
            wait = max(0, int(reset - time.time()))
            msg += f" (rate limit resets in about {wait} s)"
        return LLMQuotaError(msg, reset_at=reset)
    if kind == ERR_FATAL:
        return LLMFatalError(msg, status=status)
    if kind == ERR_PER_ITEM:
        return LLMCallError(msg)
    if kind == ERR_RATE_LIMIT:
        return _RateLimited(msg, retry_after=_retry_after(headers))
    return LLMTransientError(msg)


def _with_retry(
    fn: Callable[[], str],
    *,
    sleep: Callable[[float], None] | None = None,
    provider: str = "local",
):
    """Run ``fn`` with the single bounded retry policy.

    Only LLMTransientError (including rate-limit 429s) is retried, up to
    RETRY_MAX_ATTEMPTS attempts; Retry-After is honoured but capped. Quota,
    fatal and per-item errors propagate immediately.
    """
    for attempt in range(RETRY_MAX_ATTEMPTS):
        try:
            return fn()
        except LLMTransientError as e:
            if attempt == RETRY_MAX_ATTEMPTS - 1 or not e.retryable:
                raise
            hint = e.retry_after if isinstance(e, _RateLimited) else None
            delay = min(hint if hint is not None else RETRY_BACKOFF_S[attempt],
                        RETRY_AFTER_CAP_S)
            delay = max(0.0, delay)
            if delay >= RETRY_ANNOUNCE_S:
                print(
                    f"llm: {provider} rate-limited/unavailable, retrying in "
                    f"{delay:.0f}s (attempt {attempt + 2}/{RETRY_MAX_ATTEMPTS})",
                    file=sys.stderr,
                    flush=True,
                )
            (sleep or _sleep)(delay)
    raise AssertionError("unreachable")  # pragma: no cover


def _call_local(
    config: LLMConfig,
    system: str,
    user: str,
    max_tokens: int | None,
    temperature: float,
    timeout: float,
) -> str:
    """Call a local OpenAI-compatible server (llama.cpp, Ollama, vLLM, LM Studio).

    No Authorization header is sent unless a real key was configured, and the
    ambient proxy environment is ignored so LAN prompts are not proxied.
    """
    try:
        import httpx
    except ImportError as e:
        raise LLMCallError("httpx is required for the local provider") from e

    headers = {"Content-Type": "application/json"}
    if config.api_key and config.api_key != LOCAL_PLACEHOLDER_KEY:
        headers["Authorization"] = f"Bearer {config.api_key}"
    payload: dict = {
        "model": config.model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": temperature,
        "stream": False,
    }
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens
    url = f"{config.base_url}/chat/completions"
    label = "local server"

    def attempt() -> str:
        try:
            with httpx.Client(timeout=timeout, proxy=None, trust_env=False) as client:
                resp = client.post(url, headers=headers, json=payload)
        except httpx.ConnectError as e:
            raise LLMTransientError(
                f"cannot connect to {label} {config.base_url}: {type(e).__name__}",
                connect=True,
            ) from e
        except httpx.TimeoutException as e:
            # Re-sending would queue a second generation behind the one the
            # server is still running; fail now instead of stalling 3x.
            raise LLMTransientError(
                f"{label} {config.base_url} timed out: {type(e).__name__}",
                retryable=False,
            ) from e
        except httpx.HTTPError as e:
            raise LLMTransientError(
                f"{label} {config.base_url} request failed: {type(e).__name__}"
            ) from e
        if not 200 <= resp.status_code < 300:
            raise _error_for_status(
                resp.status_code, resp.headers, resp.text, label, config.base_url
            )
        try:
            content = resp.json()["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as e:
            raise LLMCallError(
                f"{label} {config.base_url} returned an unexpected body: "
                f"{_excerpt(resp.text)}"
            ) from e
        return _strip_fences(content or "")

    return _with_retry(attempt)


def _call_openrouter(
    config: LLMConfig,
    system: str,
    user: str,
    max_tokens: int,
    temperature: float,
    timeout: float,
) -> str:
    """Call OpenRouter via the openai SDK (OpenAI-compatible)."""
    try:
        from openai import OpenAI
    except ImportError as e:
        raise LLMCallError(
            "openai SDK is required for openrouter provider. "
            "Install: uv pip install openai"
        ) from e

    import openai

    # max_retries=0: the SDK's hidden retries would stack on _with_retry.
    client = OpenAI(
        api_key=config.api_key,
        base_url=config.base_url,
        timeout=timeout,
        max_retries=0,
    )

    def attempt():
        try:
            return client.chat.completions.create(
                model=config.model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                max_tokens=max_tokens,
                temperature=temperature,
            )
        except openai.APIStatusError as e:
            raise _error_for_status(
                e.status_code, e.response.headers, e.response.text,
                "OpenRouter", config.base_url,
            ) from e
        except openai.APIConnectionError as e:
            raise LLMTransientError(
                f"OpenRouter connection error: {type(e).__name__}",
                connect=not isinstance(e, openai.APITimeoutError),
            ) from e
        except Exception as e:  # noqa: BLE001 - openai raises many shapes; all become LLMCallError
            raise LLMCallError(f"OpenRouter API error: {e}") from e

    resp = _with_retry(attempt)

    content = (resp.choices[0].message.content or "") if resp.choices else ""
    return _strip_fences(content)


def _strip_fences(text: str) -> str:
    """Strip leading/trailing ```markdown...``` fences if present."""
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```\s*$", "", text)
    return text.strip()


_THINK_RE = re.compile(r"<think>.*?</think>", re.S | re.I)
_THINK_UNCLOSED_RE = re.compile(r"<think>.*\Z", re.S | re.I)


def extract_json_object(text: str) -> dict:
    """Return the first JSON object in a model reply.

    Tolerates markdown fences, surrounding prose and ``<think>`` blocks. Uses
    ``raw_decode`` at each ``{`` so trailing text and later objects are ignored.
    Raises ValueError when no object is present (arrays do not count).
    """
    cleaned = _THINK_RE.sub("", _strip_fences(text or ""))
    cleaned = _THINK_UNCLOSED_RE.sub("", cleaned)
    decoder = json.JSONDecoder()
    idx = cleaned.find("{")
    while idx != -1:
        end = _balanced_end(cleaned, idx)
        if end is None:  # truncated outer object: never return an inner one
            break
        try:
            obj, _ = decoder.raw_decode(cleaned, idx)
        except ValueError:
            obj = None
        if isinstance(obj, dict):
            return obj
        idx = cleaned.find("{", end)  # skip the whole failed span
    raise ValueError("no JSON object in model output")


def _balanced_end(text: str, start: int) -> int | None:
    """Index just past the brace-balanced span opening at ``start`` (or None)."""
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        c = text[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return i + 1
    return None


def _lower_headers(headers: Mapping[str, str] | None) -> dict[str, str]:
    return {str(k).lower(): str(v) for k, v in (headers or {}).items()}


def _to_float(value: str | None) -> float | None:
    try:
        return float(value) if value is not None else None
    except ValueError:
        return None


def _reset_at(headers: Mapping[str, str] | None) -> float | None:
    """Epoch seconds at which the rate limit resets (ms values are normalised)."""
    value = _to_float(_lower_headers(headers).get("x-ratelimit-reset"))
    if value is None:
        return None
    return value / 1000.0 if value > 1e11 else value


def _retry_after(headers: Mapping[str, str] | None) -> float | None:
    v = _to_float(_lower_headers(headers).get("retry-after"))
    return v if v is not None and math.isfinite(v) and v >= 0 else None


def classify_error(
    status: int | None, headers: Mapping[str, str] | None, body: str | None
) -> str:
    """Map an HTTP failure to one of the ERR_* policy classes (pure)."""
    body = body or ""
    h = _lower_headers(headers)
    if status == 429:
        if _QUOTA_RE.search(body):
            return ERR_QUOTA
        reset = _reset_at(h)
        if (
            h.get("x-ratelimit-remaining", "").strip() == "0"
            and reset is not None
            and reset - time.time() > QUOTA_RESET_HORIZON_S
        ):
            return ERR_QUOTA
        retry_after = _retry_after(h)
        if retry_after is not None and retry_after > RETRY_AFTER_CAP_S:
            return ERR_QUOTA
        return ERR_RATE_LIMIT
    if status == 413:
        return ERR_PER_ITEM
    if status == 400 and _CONTEXT_RE.search(body):
        return ERR_PER_ITEM
    if status is None or status == 408 or status >= 500:
        return ERR_TRANSIENT
    return ERR_FATAL
