"""Chat API endpoint with LLM SSE streaming."""

from __future__ import annotations

import json
import os
import re
import time
from typing import AsyncGenerator, Literal
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, Request
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from examples.workbench.chat_errors import (
    describe_exception,
    describe_provider_error,
    error_event,
    provider_label,
)
from examples.workbench.system_prompt import (
    build_system_prompt,
    get_matched_source_chunks,
)

router = APIRouter(prefix="/api", tags=["chat"])


# ---------------------------------------------------------------------------
# Curated model catalog (per-provider)
# ---------------------------------------------------------------------------
# The workbench exposes this list via GET /api/models so the frontend can
# render a model-selection dropdown. Foundry is intentionally absent — its
# deployment name is determined by AZURE_FOUNDRY_DEPLOYMENT and is built at
# request time inside /api/models (single-entry list, selector hidden).
#
# Update this dict when provider model catalogs change. Invalid IDs are
# rejected at LLM-API time (HTTP 400) and surface to the user as an SSE
# error event — no server-side allowlist enforcement needed.
#
# ORDER IS SIGNIFICANT for the "anthropic" list: server.get_models() returns
# `default_model = models[0]["id"]`, so the first entry becomes the selector's
# default. Keep it aligned with DEFAULT_ANTHROPIC_MODEL below, or the UI default
# and the no-model-specified API default will disagree.
#
# The "openrouter" list is only a degraded-mode fallback: server._fetch_or_models()
# fetches OpenRouter's live catalog and health-checks it, falling back here only
# when that request fails. These IDs could not be verified against OpenRouter's
# live catalog offline — re-check them when convenient.
PROVIDER_MODELS: dict[str, list[dict[str, str]]] = {
    "anthropic": [
        {"id": "claude-sonnet-5", "label": "Claude Sonnet 5"},
        {"id": "claude-opus-5", "label": "Claude Opus 5"},
        {"id": "claude-haiku-4-5", "label": "Claude Haiku 4.5"},
    ],
    "openrouter": [
        {"id": "anthropic/claude-sonnet-4.6", "label": "Claude Sonnet 4.6"},
        {"id": "anthropic/claude-sonnet-4.5", "label": "Claude Sonnet 4.5"},
    ],
}

# Default model for the Anthropic-native path when the request body specifies
# none. Must match PROVIDER_MODELS["anthropic"][0]["id"] (see note above).
#
# Also duplicated as core.llm_client.DEFAULT_ANTHROPIC_MODEL — the consumer layer
# does not import from core (CLAUDE.md §Layers), so these are kept in sync by
# convention. Grep DEFAULT_ANTHROPIC_MODEL to find both.
DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-5"

# Foundry is an Azure AI Studio deployment NAME, not an Anthropic model id.
# Left at the historical value deliberately: changing it would break installs
# whose Azure deployment is literally named "claude-sonnet-4-6". Operators
# override with AZURE_FOUNDRY_DEPLOYMENT.
DEFAULT_FOUNDRY_DEPLOYMENT = "claude-sonnet-4-6"


# ---------------------------------------------------------------------------
# Request model
# ---------------------------------------------------------------------------


class ChatMessage(BaseModel):
    """A single conversational turn.

    The role allowlist is enforced by Pydantic at deserialization — any value
    other than "user" or "assistant" raises ValidationError before the handler
    runs (VUL-05 / SEC-03 mitigation).
    """

    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    """Chat request body."""

    question: str
    history: list[ChatMessage] = []
    model: str | None = None  # None = use provider default (curated via /api/models)


# ---------------------------------------------------------------------------
# API key resolution
# ---------------------------------------------------------------------------


def _ensure_messages_suffix(url: str) -> str:
    """Normalize a Foundry base URL so it ends in /v1/messages.

    Users paste base URLs in several shapes depending on which docs they
    followed:

      - https://my-gw.acme.internal/anthropic
      - https://my-gw.acme.internal/anthropic/v1
      - https://my-gw.acme.internal/anthropic/v1/messages

    We only want one canonical form for httpx.post(), so strip any trailing
    slash and append /v1/messages when it isn't already present.
    """
    url = url.rstrip("/")
    if url.endswith("/v1/messages"):
        return url
    if url.endswith("/v1"):
        return url + "/messages"
    return url + "/v1/messages"


# ---------------------------------------------------------------------------
# Local OpenAI-compatible server (EPISTRACT_LLM_BASE_URL)
# ---------------------------------------------------------------------------
# The workbench is a consumer layer and does not import core/ (CLAUDE.md
# §Layers), so the local-server contract below is a hand-kept twin of
# core.llm_client / core.llm_local. Keep these in sync with them.

# Sent as the bearer value internally when no EPISTRACT_LLM_API_KEY is set; it is
# never put on the wire (see _stream_openai_compat).
LOCAL_PLACEHOLDER_KEY = "local-no-key"
# Same switch as core.llm_client.LOCAL_BASE_URL_WINS (D-02): True means a set
# EPISTRACT_LLM_BASE_URL outranks cloud keys.
LOCAL_BASE_URL_WINS = True
LOCAL_MODELS_TTL_S = 30.0
LOCAL_PROBE_TIMEOUT_S = 3.0
_NON_CHAT_MODEL_RE = re.compile(r"embed|rerank|bge|e5-|nomic", re.IGNORECASE)
_VALID_PROVIDERS = ("local", "anthropic", "openrouter", "foundry")

# root -> (monotonic timestamp, models)
_local_models_cache: dict[str, tuple[float, list[dict]]] = {}


def _clear_local_models_cache() -> None:
    _local_models_cache.clear()


def _normalise_local_root(url: str) -> str:
    """Return the server root (no ``/v1``) for a user-supplied base URL.

    Twin of core.llm_client.normalise_base_url, minus the trailing ``/v1``.
    """
    raw = (url or "").strip()
    if not raw:
        raise RuntimeError("EPISTRACT_LLM_BASE_URL is empty")
    if "://" not in raw:
        raw = "http://" + raw
    try:
        parts = urlsplit(raw)
    except ValueError:
        raise RuntimeError("EPISTRACT_LLM_BASE_URL is not a valid URL") from None
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise RuntimeError(
            "EPISTRACT_LLM_BASE_URL must be an http(s) URL, got scheme "
            f"{parts.scheme!r}"
        )
    host = parts.hostname
    if ":" in host:  # IPv6 literal
        host = f"[{host}]"
    try:
        port = parts.port
    except ValueError:
        raise RuntimeError(
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
    return f"{parts.scheme}://{host}{path}"


def _local_api_key() -> str:
    return os.environ.get("EPISTRACT_LLM_API_KEY", "").strip()


def _resolve_local(model_override: str | None) -> tuple[str, str, str, str] | None:
    raw_url = os.environ.get("EPISTRACT_LLM_BASE_URL", "").strip()
    if not raw_url:
        return None
    root = _normalise_local_root(raw_url)
    model = (
        model_override
        or os.environ.get("EPISTRACT_LLM_MODEL", "").strip()
        or ""
    )
    return (
        _local_api_key() or LOCAL_PLACEHOLDER_KEY,
        f"{root}/v1/chat/completions",
        model,
        "local",
    )


def _resolve_foundry() -> tuple[str, str, str, str] | None:
    # Accept either AZURE_FOUNDRY_* or ANTHROPIC_FOUNDRY_* naming. We look
    # up both for every field and prefer AZURE_* when both are set (the
    # original naming from the initial Foundry integration).
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
        # Direct gateway URL — bypass the Azure hostname convention.
        base_url = _ensure_messages_suffix(custom_base)
    elif resource:
        # Standard Azure AI Foundry endpoint.
        base_url = f"https://{resource}.services.ai.azure.com/anthropic/v1/messages"
    else:
        # Fail loud: key set but neither a custom base URL nor a
        # resource name is available. This is a config error, not a
        # silent fall-through to another provider.
        raise RuntimeError(
            "Foundry API key is set but neither AZURE_FOUNDRY_BASE_URL "
            "(or ANTHROPIC_FOUNDRY_BASE_URL) nor AZURE_FOUNDRY_RESOURCE "
            "is configured. Set one of:\n"
            "  AZURE_FOUNDRY_BASE_URL=https://<gateway>/anthropic\n"
            "  AZURE_FOUNDRY_RESOURCE=<azure-resource-name>\n"
            "Or unset the API key to fall back to ANTHROPIC_API_KEY / OPENROUTER_API_KEY."
        )
    # model_override intentionally NOT applied here — Foundry deployment
    # name is determined by Azure AI Studio registration + the
    # AZURE_FOUNDRY_DEPLOYMENT env var, not by the request body.
    return foundry_key, base_url, deployment, "anthropic"


def _resolve_anthropic(effective_model: str | None) -> tuple[str, str, str, str] | None:
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
    if not anthropic_key:
        return None
    return (
        anthropic_key,
        "https://api.anthropic.com/v1/messages",
        effective_model or DEFAULT_ANTHROPIC_MODEL,
        "anthropic",
    )


def _resolve_openrouter(effective_model: str | None) -> tuple[str, str, str, str] | None:
    openrouter_key = os.environ.get("OPENROUTER_API_KEY")
    if not openrouter_key:
        return None
    return (
        openrouter_key,
        "https://openrouter.ai/api/v1/chat/completions",
        effective_model or PROVIDER_MODELS["openrouter"][0]["id"],
        "openrouter",
    )


_MISSING_HINT = {
    "local": "EPISTRACT_LLM_BASE_URL",
    "anthropic": "ANTHROPIC_API_KEY (or AZURE_FOUNDRY_API_KEY for a gateway)",
    "openrouter": "OPENROUTER_API_KEY",
    "foundry": "AZURE_FOUNDRY_API_KEY with AZURE_FOUNDRY_BASE_URL or AZURE_FOUNDRY_RESOURCE",
}


def _resolve_api_config(
    model_override: str | None = None,
) -> tuple[str | None, str, str, str]:
    """Return (api_key, base_url, model, provider) from available env vars.

    If model_override is non-None and non-empty after stripping, it replaces
    the default model for the Anthropic direct, OpenRouter and local providers.
    The Azure Foundry provider ignores model_override — the deployment name is
    determined by the Azure AI Studio registration and the
    AZURE_FOUNDRY_DEPLOYMENT env var.

    Priority:
    0. EPISTRACT_LLM_PROVIDER (local|anthropic|openrouter|foundry) forces one
       provider and raises RuntimeError when its credentials are missing.
    1. EPISTRACT_LLM_BASE_URL -> local OpenAI-compatible server (when
       LOCAL_BASE_URL_WINS; the key comes only from EPISTRACT_LLM_API_KEY, the
       model from the request, EPISTRACT_LLM_MODEL, or auto-detection)
    2. AZURE_FOUNDRY_API_KEY (or ANTHROPIC_FOUNDRY_API_KEY as alias)
       -> Azure AI Foundry / custom Anthropic gateway (Anthropic-native format)

       Endpoint resolution inside the Foundry block:
         a. If AZURE_FOUNDRY_BASE_URL (or ANTHROPIC_FOUNDRY_BASE_URL) is set,
            use it directly — supports custom API gateways, private
            endpoints, and non-standard hostnames. /v1/messages is
            auto-appended when missing.
         b. Otherwise, build the standard Azure URL from
            AZURE_FOUNDRY_RESOURCE:
            https://<resource>.services.ai.azure.com/anthropic/v1/messages

       Either AZURE_FOUNDRY_BASE_URL OR AZURE_FOUNDRY_RESOURCE is
       required when the API key is set — otherwise we raise RuntimeError
       instead of silently falling through to a different provider.

       Optional: AZURE_FOUNDRY_DEPLOYMENT (or ANTHROPIC_FOUNDRY_DEPLOYMENT)
       — defaults to claude-sonnet-4-6.

    3. ANTHROPIC_API_KEY -> direct Anthropic API (native format)
    4. OPENROUTER_API_KEY -> OpenRouter (OpenAI-compatible format)
    5. EPISTRACT_LLM_BASE_URL when LOCAL_BASE_URL_WINS is False.

    All Foundry paths reuse the native-format _stream_anthropic() streamer
    verbatim — only the URL and model string change. Some enterprise
    environments standardize env vars around the provider name
    (ANTHROPIC_FOUNDRY_*) rather than the cloud (AZURE_FOUNDRY_*); both
    prefixes are accepted as synonyms throughout the Foundry block.
    """
    # Coerce empty/whitespace override to None so the caller's empty-string
    # default (from a hidden or unpopulated <select>) falls back to the
    # provider's baked-in model. See RESEARCH Pitfall 2.
    effective_model = (model_override or "").strip() or None

    forced = os.environ.get("EPISTRACT_LLM_PROVIDER", "").strip().lower()
    if forced:
        if forced not in _VALID_PROVIDERS:
            raise RuntimeError(
                f"EPISTRACT_LLM_PROVIDER={forced!r} is not one of "
                f"{', '.join(_VALID_PROVIDERS)}"
            )
        cfg = {
            "local": lambda: _resolve_local(effective_model),
            "anthropic": lambda: _resolve_anthropic(effective_model)
            or _resolve_foundry(),
            "openrouter": lambda: _resolve_openrouter(effective_model),
            "foundry": _resolve_foundry,
        }[forced]()
        if cfg is None:
            raise RuntimeError(
                f"EPISTRACT_LLM_PROVIDER={forced} but {_MISSING_HINT[forced]} "
                "is not set"
            )
        return cfg

    if LOCAL_BASE_URL_WINS:
        cfg = _resolve_local(effective_model)
        if cfg is not None:
            return cfg

    for cfg in (
        _resolve_foundry(),
        _resolve_anthropic(effective_model),
        _resolve_openrouter(effective_model),
    ):
        if cfg is not None:
            return cfg

    if not LOCAL_BASE_URL_WINS:
        cfg = _resolve_local(effective_model)
        if cfg is not None:
            return cfg

    return None, "", "", ""


def active_provider() -> str | None:
    """Which provider the chat panel will use on the next request. Never raises.

    Returns "local" | "azure-foundry-custom" | "azure-foundry" | "anthropic" |
    "openrouter" | None. A bad Foundry configuration still reports the Foundry
    label (the chat endpoint then surfaces the misconfiguration); any other
    configuration error reports None.
    """

    def foundry_label() -> str:
        has_custom_base = bool(
            os.environ.get("AZURE_FOUNDRY_BASE_URL")
            or os.environ.get("ANTHROPIC_FOUNDRY_BASE_URL")
        )
        return "azure-foundry-custom" if has_custom_base else "azure-foundry"

    has_foundry = bool(
        os.environ.get("AZURE_FOUNDRY_API_KEY")
        or os.environ.get("ANTHROPIC_FOUNDRY_API_KEY")
    )
    try:
        _, base_url, _, provider = _resolve_api_config()
    except RuntimeError:
        forced = os.environ.get("EPISTRACT_LLM_PROVIDER", "").strip().lower()
        if has_foundry and forced in ("", "foundry", "anthropic"):
            return foundry_label()
        return None
    if provider == "local":
        return "local"
    if provider == "openrouter":
        return "openrouter"
    if provider == "anthropic":
        return "anthropic" if "api.anthropic.com" in base_url else foundry_label()
    return None


async def list_local_models(base_url: str) -> list[dict]:
    """List models served at ``base_url`` as ``[{"id", "label"}]`` (30 s cache).

    Raises httpx.HTTPError or ValueError when the server cannot be read;
    callers degrade rather than fail.
    """
    root = _normalise_local_root(base_url)
    now = time.monotonic()
    cached = _local_models_cache.get(root)
    if cached is not None and now - cached[0] < LOCAL_MODELS_TTL_S:
        return cached[1]
    headers = {}
    key = _local_api_key()
    if key:
        headers["Authorization"] = f"Bearer {key}"
    # trust_env=False: a local server must never be reached through an
    # ambient HTTP(S)_PROXY.
    async with httpx.AsyncClient(
        timeout=LOCAL_PROBE_TIMEOUT_S, proxy=None, trust_env=False
    ) as client:
        resp = await client.get(f"{root}/v1/models", headers=headers)
        resp.raise_for_status()
        payload = resp.json()
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list):
        raise ValueError("unexpected /v1/models response")
    models = [
        {"id": m["id"], "label": m["id"]}
        for m in data
        if isinstance(m, dict) and isinstance(m.get("id"), str) and m["id"]
    ]
    _local_models_cache[root] = (now, models)
    return models


async def _autodetect_local_model(base_url: str) -> str:
    """First served model that is not an embedding/rerank model; "" on failure."""
    try:
        models = await list_local_models(base_url)
    except (httpx.HTTPError, ValueError, RuntimeError):
        return ""
    for m in models:
        if not _NON_CHAT_MODEL_RE.search(m["id"]):
            return m["id"]
    return ""


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.post("/chat")
async def chat(request: Request, body: ChatRequest):
    """Stream an LLM response as SSE events."""
    try:
        api_key, base_url, model, provider = _resolve_api_config(
            model_override=body.model,
        )
    except RuntimeError as exc:
        return EventSourceResponse(
            _error_stream(
                str(exc),
                title="Model provider misconfigured",
                hint="Fix the settings described above and restart the workbench.",
            )
        )
    if not api_key:
        return EventSourceResponse(
            _error_stream(
                "No API key found. Set one of: "
                "AZURE_FOUNDRY_API_KEY (or ANTHROPIC_FOUNDRY_API_KEY) with either "
                "AZURE_FOUNDRY_BASE_URL or AZURE_FOUNDRY_RESOURCE; "
                "ANTHROPIC_API_KEY; OPENROUTER_API_KEY; or EPISTRACT_LLM_BASE_URL "
                "(local OpenAI-compatible server)."
            )
        )

    if provider == "local" and not model:
        model = await _autodetect_local_model(base_url)
        if not model:
            return EventSourceResponse(
                _error_stream(
                    "Could not determine a chat model at the local server; "
                    "set EPISTRACT_LLM_MODEL.",
                    title="No local model available",
                    hint="Set EPISTRACT_LLM_MODEL and restart the workbench.",
                )
            )

    data = request.app.state.data

    # Build system prompt with full KG context
    system = build_system_prompt(data, request.app.state.template)

    # Add matched source chunks to the user's question context
    source_context = get_matched_source_chunks(data, body.question)
    user_content = body.question
    if source_context:
        user_content = f"{body.question}\n\n---\n{source_context}"

    # Build messages array with history (D-08: session only, last 10 turns max)
    messages: list[dict] = []
    recent_history = body.history[-10:] if len(body.history) > 10 else body.history
    for msg in recent_history:
        # msg is a ChatMessage — attribute access only; role allowlist already
        # enforced by Pydantic at request deserialization.
        messages.append({"role": msg.role, "content": msg.content})
    messages.append({"role": "user", "content": user_content})

    if provider == "anthropic":
        return EventSourceResponse(
            _stream_anthropic(api_key, base_url, model, system, messages),
            media_type="text/event-stream",
        )
    else:
        return EventSourceResponse(
            _stream_openai_compat(
                api_key, base_url, model, system, messages, provider
            ),
            media_type="text/event-stream",
        )


async def _stream_anthropic(
    api_key: str, base_url: str, model: str, system: str, messages: list[dict]
) -> AsyncGenerator[dict, None]:
    """Stream via Anthropic's native API using httpx."""
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    payload = {
        "model": model,
        "max_tokens": 4096,
        # System prompt as a cacheable block rather than a bare string.
        #
        # build_system_prompt() emits the full KG summary, claims layer,
        # communities, and up to ~50k tokens of entity JSON — and it is
        # byte-identical on every turn of a session: app.state.data and
        # app.state.template are assigned once at startup (server.py, "Load data
        # at startup"), never per request, and the prompt builder iterates
        # deterministically (sorted(by_type.items()), file-order nodes).
        #
        # Without cache_control every turn re-pays full input price for that
        # unchanged prefix. Cache reads bill at ~0.1x and writes at ~1.25x, so
        # break-even is the second turn of any session.
        #
        # The per-turn volatile part (matched source chunks) is deliberately in
        # the USER message, not here — it must stay after the cached prefix or
        # it would invalidate the cache on every request.
        "system": [
            {
                "type": "text",
                "text": system,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        "messages": messages,
        "stream": True,
    }

    label = provider_label("anthropic", base_url)
    try:
        async with httpx.AsyncClient(timeout=120.0, proxy=None) as client:
            async with client.stream("POST", base_url, json=payload, headers=headers) as resp:
                if resp.status_code != 200:
                    error_body = await resp.aread()
                    yield error_event(
                        describe_provider_error(
                            resp.status_code,
                            error_body.decode(errors="replace"),
                            provider_label=label,
                            model=model,
                        )
                    )
                    yield {"data": json.dumps({"type": "done"})}
                    return

                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data_str = line[6:]
                    if data_str == "[DONE]":
                        break
                    try:
                        event = json.loads(data_str)
                        if event.get("type") == "error":
                            yield error_event(
                                describe_provider_error(
                                    None,
                                    json.dumps(event),
                                    provider_label=label,
                                    model=model,
                                )
                            )
                            yield {"data": json.dumps({"type": "done"})}
                            return
                        if event.get("type") == "content_block_delta":
                            delta = event.get("delta", {})
                            text = delta.get("text", "")
                            if text:
                                yield {"data": json.dumps({"type": "text", "content": text})}
                    except json.JSONDecodeError:
                        continue
    except Exception as e:
        yield error_event(describe_exception(e, provider_label=label, model=model))

    yield {"data": json.dumps({"type": "done"})}


def _local_max_tokens() -> int | None:
    """Optional output cap for a local server (EPISTRACT_LLM_MAX_TOKENS)."""
    raw = os.environ.get("EPISTRACT_LLM_MAX_TOKENS", "").strip()
    try:
        value = int(raw)
    except ValueError:
        return None
    return value if value > 0 else None


async def _stream_openai_compat(
    api_key: str,
    base_url: str,
    model: str,
    system: str,
    messages: list[dict],
    provider: str = "openrouter",
) -> AsyncGenerator[dict, None]:
    """Stream via an OpenAI-compatible API (OpenRouter or a local server)."""
    is_local = provider == "local"
    headers = {"Content-Type": "application/json"}
    if is_local:
        # Only an explicitly configured EPISTRACT_LLM_API_KEY goes on the wire;
        # OpenRouter attribution headers are never sent to a local server.
        if api_key != LOCAL_PLACEHOLDER_KEY:
            headers["Authorization"] = f"Bearer {api_key}"
    else:
        headers["Authorization"] = f"Bearer {api_key}"
        headers["HTTP-Referer"] = "https://github.com/epistract"
        headers["X-Title"] = "Epistract Workbench"
    # OpenAI format: system message goes in messages array
    oai_messages = [{"role": "system", "content": system}] + messages
    payload: dict = {
        "model": model,
        "messages": oai_messages,
        "stream": True,
    }
    if is_local:
        # No fixed budget: a hard-coded 4096 can exceed a small model's context
        # window. The server bounds generation by its own window unless the
        # operator sets an explicit cap.
        cap = _local_max_tokens()
        if cap is not None:
            payload["max_tokens"] = cap
    else:
        payload["max_tokens"] = 4096

    label = provider_label(provider, base_url)
    try:
        # A local server is never reached through an ambient HTTP(S)_PROXY.
        async with httpx.AsyncClient(
            timeout=120.0, proxy=None, trust_env=not is_local
        ) as client:
            async with client.stream("POST", base_url, json=payload, headers=headers) as resp:
                if resp.status_code != 200:
                    error_body = await resp.aread()
                    yield error_event(
                        describe_provider_error(
                            resp.status_code,
                            error_body.decode(errors="replace"),
                            provider_label=label,
                            model=model,
                            headers=getattr(resp, "headers", None),
                        )
                    )
                    yield {"data": json.dumps({"type": "done"})}
                    return

                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data_str = line[6:]
                    if data_str == "[DONE]":
                        break
                    try:
                        event = json.loads(data_str)
                        # OpenRouter can embed errors inside the SSE stream
                        # (not just as HTTP error codes) — surface them explicitly.
                        error_obj = event.get("error")
                        if error_obj:
                            if not isinstance(error_obj, dict):
                                error_obj = {"message": str(error_obj)}
                            code = error_obj.get("code")
                            yield error_event(
                                describe_provider_error(
                                    code if isinstance(code, int) else None,
                                    json.dumps({"error": error_obj}),
                                    provider_label=label,
                                    model=model,
                                )
                            )
                            yield {"data": json.dumps({"type": "done"})}
                            return
                        choices = event.get("choices", [])
                        if choices:
                            delta = choices[0].get("delta", {})
                            text = delta.get("content", "")
                            if text:
                                yield {"data": json.dumps({"type": "text", "content": text})}
                    except json.JSONDecodeError:
                        continue
    except Exception as e:
        yield error_event(describe_exception(
                e, provider_label=label, model=model, base_url=base_url
            ))

    yield {"data": json.dumps({"type": "done"})}


async def _error_stream(
    message: str,
    title: str = "No API key configured",
    hint: str = "Set one of the env vars above and restart the workbench.",
) -> AsyncGenerator[dict, None]:
    """Stream a structured configuration error followed by done."""
    yield error_event(
        {
            "title": title,
            "message": message,
            "hint": hint,
            "detail": "",
            "status": None,
        }
    )
    yield {"data": json.dumps({"type": "done"})}
