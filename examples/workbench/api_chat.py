"""Chat API endpoint with LLM SSE streaming."""

from __future__ import annotations

import json
import os
import time
from typing import AsyncGenerator

import httpx
from fastapi import APIRouter, Request
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from examples.workbench.system_prompt import (
    build_system_prompt,
    get_matched_source_chunks,
)

router = APIRouter(prefix="/api", tags=["chat"])

PROVIDER_MODELS: dict[str, list[dict[str, str]]] = {
    "anthropic": [
        {"id": "claude-sonnet-4-20250514", "label": "Claude Sonnet 4"},
        {"id": "claude-opus-4-20250514", "label": "Claude Opus 4"},
        {"id": "claude-haiku-3-5-20241022", "label": "Claude Haiku 3.5"},
    ],
    "openrouter": [
        {"id": "anthropic/claude-sonnet-4", "label": "Claude Sonnet 4"},
        {"id": "anthropic/claude-opus-4", "label": "Claude Opus 4"},
        {"id": "anthropic/claude-haiku-4", "label": "Claude Haiku 4"},
        {"id": "anthropic/claude-sonnet-4-5", "label": "Claude Sonnet 4.5"},
        {"id": "anthropic/claude-haiku-3-5", "label": "Claude Haiku 3.5"},
    ],
}

# OpenRouter live-model TTL cache (5 min). Populated by GET /api/models.
_OPENROUTER_MODELS_CACHE: dict[str, object] = {"data": None, "fetched_at": 0.0}
_OPENROUTER_CACHE_TTL_SECONDS = 300.0


# ---------------------------------------------------------------------------
# Request model
# ---------------------------------------------------------------------------


class ChatRequest(BaseModel):
    """Chat request body."""

    question: str
    history: list[dict] = []  # [{"role": "user"|"assistant", "content": "..."}]
    model: str | None = None  # None = use provider default (curated via /api/models)


VALID_ROLES: frozenset[str] = frozenset({"user", "assistant"})


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


def _resolve_api_config(
    model_override: str | None = None,
) -> tuple[str | None, str, str, str]:
    """Return (api_key, base_url, model, provider) from available env vars.

    Priority:
    1. AZURE_FOUNDRY_API_KEY (or ANTHROPIC_FOUNDRY_API_KEY as alias)
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

    2. ANTHROPIC_API_KEY -> direct Anthropic API (native format)
    3. OPENROUTER_API_KEY -> OpenRouter (OpenAI-compatible format)

    All Foundry paths reuse the native-format _stream_anthropic() streamer
    verbatim — only the URL and model string change. Some enterprise
    environments standardize env vars around the provider name
    (ANTHROPIC_FOUNDRY_*) rather than the cloud (AZURE_FOUNDRY_*); both
    prefixes are accepted as synonyms throughout the Foundry block.
    """
    effective_model = (model_override or "").strip() or None

    # --- Foundry block ---
    # Accept either AZURE_FOUNDRY_* or ANTHROPIC_FOUNDRY_* naming. We look
    # up both for every field and prefer AZURE_* when both are set (the
    # original naming from the initial Foundry integration).
    foundry_key = os.environ.get("AZURE_FOUNDRY_API_KEY") or os.environ.get(
        "ANTHROPIC_FOUNDRY_API_KEY"
    )
    if foundry_key:
        custom_base = (
            os.environ.get("AZURE_FOUNDRY_BASE_URL")
            or os.environ.get("ANTHROPIC_FOUNDRY_BASE_URL")
            or ""
        ).strip()
        resource = os.environ.get("AZURE_FOUNDRY_RESOURCE", "").strip()
        deployment = (
            os.environ.get("AZURE_FOUNDRY_DEPLOYMENT")
            or os.environ.get("ANTHROPIC_FOUNDRY_DEPLOYMENT")
            or "claude-sonnet-4-6"
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
        # Foundry deployment is fixed by AZURE_FOUNDRY_DEPLOYMENT;
        # model_override is intentionally ignored here.
        return foundry_key, base_url, deployment, "anthropic"

    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
    if anthropic_key:
        return (
            anthropic_key,
            "https://api.anthropic.com/v1/messages",
            effective_model or "claude-sonnet-4-20250514",
            "anthropic",
        )

    openrouter_key = os.environ.get("OPENROUTER_API_KEY")
    if openrouter_key:
        return (
            openrouter_key,
            "https://openrouter.ai/api/v1/chat/completions",
            effective_model or "anthropic/claude-sonnet-4",
            "openrouter",
        )

    return None, "", "", ""


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.post("/chat")
async def chat(request: Request, body: ChatRequest):
    """Stream an LLM response as SSE events."""
    try:
        api_key, base_url, model, provider = _resolve_api_config(model_override=body.model)
    except RuntimeError as exc:
        return EventSourceResponse(_error_stream(str(exc)))
    if not api_key:
        return EventSourceResponse(
            _error_stream(
                "No API key found. Set one of: "
                "AZURE_FOUNDRY_API_KEY (or ANTHROPIC_FOUNDRY_API_KEY) with either "
                "AZURE_FOUNDRY_BASE_URL or AZURE_FOUNDRY_RESOURCE; "
                "ANTHROPIC_API_KEY; or OPENROUTER_API_KEY."
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
    messages = []
    recent_history = body.history[-10:] if len(body.history) > 10 else body.history
    for msg in recent_history:
        role = msg.get("role", "")
        content = msg.get("content", "")
        if role not in VALID_ROLES or not isinstance(content, str):
            continue
        messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": user_content})

    if provider == "anthropic":
        return EventSourceResponse(
            _stream_anthropic(api_key, base_url, model, system, messages),
            media_type="text/event-stream",
        )
    else:
        return EventSourceResponse(
            _stream_openai_compat(api_key, base_url, model, system, messages),
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
        "max_tokens": 1024,
        "system": system,
        "messages": messages,
        "stream": True,
    }

    try:
        async with httpx.AsyncClient(timeout=120.0, proxy=None) as client:
            async with client.stream(
                "POST", base_url, json=payload, headers=headers
            ) as resp:
                if resp.status_code != 200:
                    raw_error = await resp.aread()
                    yield {
                        "data": json.dumps(
                            {
                                "type": "error",
                                "content": f"API error {resp.status_code}: {raw_error.decode()[:500]}",
                            }
                        )
                    }
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
                        if event.get("type") == "content_block_delta":
                            delta = event.get("delta", {})
                            text = delta.get("text", "")
                            if text:
                                yield {
                                    "data": json.dumps(
                                        {"type": "text", "content": text}
                                    )
                                }
                    except json.JSONDecodeError:
                        continue
    except Exception as e:
        yield {"data": json.dumps({"type": "error", "content": str(e)})}

    yield {"data": json.dumps({"type": "done"})}


async def _stream_openai_compat(
    api_key: str, base_url: str, model: str, system: str, messages: list[dict]
) -> AsyncGenerator[dict, None]:
    """Stream via OpenAI-compatible API (OpenRouter) using httpx."""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/epistract",
        "X-Title": "Epistract Workbench",
    }
    # OpenAI format: system message goes in messages array
    oai_messages = [{"role": "system", "content": system}] + messages
    payload = {
        "model": model,
        "max_tokens": 1024,
        "messages": oai_messages,
        "stream": True,
    }

    try:
        async with httpx.AsyncClient(timeout=120.0, proxy=None) as client:
            async with client.stream(
                "POST", base_url, json=payload, headers=headers
            ) as resp:
                if resp.status_code != 200:
                    raw_error = await resp.aread()
                    yield {
                        "data": json.dumps(
                            {
                                "type": "error",
                                "content": f"API error {resp.status_code}: {raw_error.decode()[:500]}",
                            }
                        )
                    }
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
                        choices = event.get("choices", [])
                        if choices:
                            delta = choices[0].get("delta", {})
                            text = delta.get("content", "")
                            if text:
                                yield {
                                    "data": json.dumps(
                                        {"type": "text", "content": text}
                                    )
                                }
                    except json.JSONDecodeError:
                        continue
    except Exception as e:
        yield {"data": json.dumps({"type": "error", "content": str(e)})}

    yield {"data": json.dumps({"type": "done"})}


async def _error_stream(message: str) -> AsyncGenerator[dict, None]:
    """Stream an error message."""
    yield {"data": json.dumps({"type": "error", "content": message})}
    yield {"data": json.dumps({"type": "done"})}


# ---------------------------------------------------------------------------
# Model catalog endpoint
# ---------------------------------------------------------------------------


def _detect_provider_inline() -> str:
    """Detect provider from env vars without invoking _resolve_api_config.

    Mirrors the priority order in _resolve_api_config but stays inline to avoid
    raising RuntimeError for incomplete Foundry config (the catalog endpoint
    must still return a sensible response when keys are partially set).
    """
    if os.environ.get("AZURE_FOUNDRY_API_KEY") or os.environ.get(
        "ANTHROPIC_FOUNDRY_API_KEY"
    ):
        return "foundry"
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"
    if os.environ.get("OPENROUTER_API_KEY"):
        return "openrouter"
    return "none"


def _foundry_deployment_name() -> str:
    return (
        os.environ.get("AZURE_FOUNDRY_DEPLOYMENT")
        or os.environ.get("ANTHROPIC_FOUNDRY_DEPLOYMENT")
        or "claude-sonnet-4-6"
    )


_OPENROUTER_GROUP_KEYWORDS: list[tuple[str, str]] = [
    ("anthropic/", "Claude (Anthropic)"),
    ("claude", "Claude (Anthropic)"),
    ("openai/", "GPT / O-series (OpenAI)"),
    ("gpt-", "GPT / O-series (OpenAI)"),
    ("o1", "GPT / O-series (OpenAI)"),
    ("o3", "GPT / O-series (OpenAI)"),
    ("qwen", "Qwen (Alibaba)"),
    ("google/", "Gemini / Gemma (Google)"),
    ("gemini", "Gemini / Gemma (Google)"),
    ("gemma", "Gemini / Gemma (Google)"),
    ("mistral", "Mistral"),
    ("meta-llama", "Llama (Meta)"),
    ("llama", "Llama (Meta)"),
    ("deepseek", "DeepSeek"),
    ("x-ai/", "Grok (xAI)"),
    ("grok", "Grok (xAI)"),
    ("nvidia", "Nvidia"),
    ("amazon", "Amazon"),
    ("perplexity", "Perplexity"),
    ("cohere", "Cohere"),
]


def _classify_openrouter_group(model_id: str) -> str:
    lid = model_id.lower()
    for needle, label in _OPENROUTER_GROUP_KEYWORDS:
        if needle in lid:
            return label
    return "Other"


async def _fetch_openrouter_models(api_key: str) -> list[dict] | None:
    """Fetch live OpenRouter model list with TTL cache. Returns None on error."""
    now = time.time()
    cached = _OPENROUTER_MODELS_CACHE.get("data")
    fetched_at = float(_OPENROUTER_MODELS_CACHE.get("fetched_at") or 0.0)
    if cached and (now - fetched_at) < _OPENROUTER_CACHE_TTL_SECONDS:
        return cached  # type: ignore[return-value]

    headers = {
        "Authorization": f"Bearer {api_key}",
        "HTTP-Referer": "https://github.com/epistract",
        "X-Title": "Epistract Workbench",
    }
    try:
        async with httpx.AsyncClient(timeout=10.0, proxy=None) as client:
            resp = await client.get(
                "https://openrouter.ai/api/v1/models", headers=headers
            )
            if resp.status_code != 200:
                return None
            payload = resp.json()
            raw_models = payload.get("data") or []
            shaped: list[dict] = []
            for m in raw_models:
                model_id = m.get("id")
                if not model_id:
                    continue
                label = m.get("name") or model_id
                pricing = m.get("pricing") or {}
                # OpenRouter returns prompt cost as USD-per-token strings.
                try:
                    prompt_cost = float(pricing.get("prompt") or 0.0)
                except (TypeError, ValueError):
                    prompt_cost = 0.0
                shaped.append(
                    {
                        "id": model_id,
                        "label": label,
                        "group": _classify_openrouter_group(model_id),
                        "prompt_cost": prompt_cost,
                    }
                )
            _OPENROUTER_MODELS_CACHE["data"] = shaped
            _OPENROUTER_MODELS_CACHE["fetched_at"] = now
            return shaped
    except Exception:
        return None


@router.get("/models")
async def list_models() -> dict:
    """Return the curated model catalog for the active provider.

    Response shape: {"provider": str, "models": list[dict]}.
    Frontend hides the selector when len(models) <= 1.
    """
    provider = _detect_provider_inline()
    if provider == "foundry":
        deployment = _foundry_deployment_name()
        return {
            "provider": "foundry",
            "models": [{"id": deployment, "label": deployment}],
        }
    if provider == "anthropic":
        return {"provider": "anthropic", "models": PROVIDER_MODELS["anthropic"]}
    if provider == "openrouter":
        api_key = os.environ.get("OPENROUTER_API_KEY") or ""
        live = await _fetch_openrouter_models(api_key)
        if live:
            return {"provider": "openrouter", "models": live}
        # Fallback to curated static list if live fetch fails.
        return {"provider": "openrouter", "models": PROVIDER_MODELS["openrouter"]}
    return {"provider": "none", "models": []}
