"""Probes for local OpenAI-compatible model servers (llama.cpp, Ollama, vLLM, LM Studio).

Used by `core.llm_client` to auto-pick a chat model and learn the context window,
and by the setup/check tooling to verify that a model really serves chat.
Every probe is short (3 s), memoised per base URL, and never echoes credentials.
"""
from __future__ import annotations

import os
import re
import time
from urllib.parse import quote

from .llm_client import LLMCallError, LLMConfig, LLMConfigError, call_llm

NON_CHAT_MODEL_RE = re.compile(r"embed|rerank|bge|e5-|nomic", re.IGNORECASE)
_NOT_CHAT_RE = re.compile(
    r"\b(?:rerank|embedding) model\b|does not support chat"
    r"|cannot be used with the chat|does not support logits",
    re.IGNORECASE,
)

# Memo keyed by api_base (model lists) and (api_base, model) (context windows).
_MODELS_CACHE: dict = {}
_CTX_CACHE: dict = {}
# Short-lived memo of failed list_models calls: api_base -> (monotonic ts, message),
# so a dead server does not cost a full timeout on every call.
_MODELS_FAIL_CACHE: dict = {}
_FAIL_TTL_S = 30.0
# Sentinel from _get_json: transport error or transient HTTP status (not memoised).
_TRANSIENT = object()


def clear_cache() -> None:
    """Forget every memoised probe result (tests reuse ephemeral ports)."""
    _MODELS_CACHE.clear()
    _CTX_CACHE.clear()
    _MODELS_FAIL_CACHE.clear()
    from . import llm_client

    llm_client._ANNOUNCED_MODELS.clear()
    llm_client._JSON_MODE_UNSUPPORTED.clear()


def _root(api_base: str) -> str:
    base = api_base.rstrip("/")
    return base[: -len("/v1")] if base.endswith("/v1") else base


def _headers(api_key: str | None) -> dict:
    return {"Authorization": f"Bearer {api_key}"} if api_key else {}


def _positive_int(value) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value > 0:
        return value
    return None


def list_models(
    api_base: str, api_key: str | None = None, timeout: float = 3.0
) -> list[dict]:
    """Return ``[{"id": str, "n_ctx": int | None}]`` served at ``{api_base}/models``.

    Raises LLMCallError (naming the base URL, never the key) on any failure.
    """
    if api_base in _MODELS_CACHE:
        return _MODELS_CACHE[api_base]
    failed = _MODELS_FAIL_CACHE.get(api_base)
    if failed is not None:
        if time.monotonic() - failed[0] < _FAIL_TTL_S:
            raise LLMCallError(failed[1])
        del _MODELS_FAIL_CACHE[api_base]
    try:
        return _list_models_uncached(api_base, api_key, timeout)
    except LLMCallError as e:
        _MODELS_FAIL_CACHE[api_base] = (time.monotonic(), str(e))
        raise


def _list_models_uncached(
    api_base: str, api_key: str | None, timeout: float
) -> list[dict]:
    try:
        import httpx

        with httpx.Client(timeout=timeout, proxy=None, trust_env=False) as client:
            resp = client.get(f"{api_base}/models", headers=_headers(api_key))
        if resp.status_code != 200:
            raise LLMCallError(
                f"could not list models at {api_base}: HTTP {resp.status_code}"
            )
        data = resp.json()
    except LLMCallError:
        raise
    except Exception as e:  # noqa: BLE001 - network/JSON failures all become LLMCallError
        raise LLMCallError(
            f"could not list models at {api_base}: {type(e).__name__}"
        ) from None

    entries = data.get("data") if isinstance(data, dict) else None
    if not isinstance(entries, list):
        raise LLMCallError(f"could not list models at {api_base}: unexpected response")
    models: list[dict] = []
    for item in entries:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            continue
        meta = item.get("meta")
        n_ctx = _positive_int(meta.get("n_ctx")) if isinstance(meta, dict) else None
        if n_ctx is None:
            n_ctx = _positive_int(item.get("max_model_len"))
        models.append({"id": item["id"], "n_ctx": n_ctx})
    _MODELS_CACHE[api_base] = models
    return models


def pick_chat_model(ids: list[str]) -> str | None:
    """First model id that is not an embedding/reranker model, else None."""
    for model_id in ids:
        if not NON_CHAT_MODEL_RE.search(model_id):
            return model_id
    return None


def _get_json(url: str, api_key: str | None, *, post: dict | None = None):
    try:
        import httpx

        with httpx.Client(timeout=3.0, proxy=None, trust_env=False) as client:
            if post is None:
                resp = client.get(url, headers=_headers(api_key))
            else:
                resp = client.post(url, headers=_headers(api_key), json=post)
        if resp.status_code in (408, 425, 429) or resp.status_code >= 500:
            return _TRANSIENT
        if resp.status_code != 200:
            return None  # definitive: endpoint absent or refused
        return resp.json()
    except Exception:  # noqa: BLE001 - probes never raise
        return _TRANSIENT


def probe_context(api_base: str, model: str, api_key: str | None = None) -> int | None:
    """Usable context window (tokens) for ``model``, or None when unknown.

    Order: EPISTRACT_LLM_CONTEXT_WINDOW override; llama.cpp (smaller of
    /v1/models meta.n_ctx and /props n_ctx, the per-slot window under
    --parallel); vLLM max_model_len; LM Studio loaded_context_length; Ollama
    num_ctx. Ollama's trained context_length is deliberately ignored.
    """
    override = os.environ.get("EPISTRACT_LLM_CONTEXT_WINDOW", "").strip()
    if override:
        try:
            value = int(override)
        except ValueError:
            value = 0
        if value > 0:
            return value

    key = (api_base, model)
    if key in _CTX_CACHE:
        return _CTX_CACHE[key]
    result, definitive = _probe_context_uncached(api_base, model, api_key)
    # Never memoise an unknown that came from a transport/HTTP failure: the server
    # may still be loading and a later call should be able to learn the window.
    if result is not None or definitive:
        _CTX_CACHE[key] = result
    return result


def _probe_context_uncached(
    api_base: str, model: str, api_key: str | None
) -> tuple[int | None, bool]:
    """Return ``(window, definitive)``; ``definitive`` is False if any probe failed transiently."""
    root = _root(api_base)
    definitive = True
    try:
        entry = next((m for m in list_models(api_base, api_key) if m["id"] == model), None)
    except LLMCallError:
        entry = None
        definitive = False
    models_ctx = entry["n_ctx"] if entry else None

    props = _get_json(f"{root}/props", api_key)
    if props is _TRANSIENT:
        definitive = False
    props_ctx = None
    if isinstance(props, dict):
        settings = props.get("default_generation_settings")
        if isinstance(settings, dict):
            props_ctx = _positive_int(settings.get("n_ctx"))

    found = [v for v in (models_ctx, props_ctx) if v]
    if found:
        return min(found), True

    # LM Studio: only the loaded window counts; max_context_length is the trained
    # limit (like Ollama's context_length, deliberately ignored).
    lm = _get_json(f"{root}/api/v0/models/{quote(model, safe='')}", api_key)
    if lm is _TRANSIENT:
        definitive = False
    elif isinstance(lm, dict):
        ctx = _positive_int(lm.get("loaded_context_length"))
        if ctx:
            return ctx, True

    show = _get_json(f"{root}/api/show", api_key, post={"model": model})
    if show is _TRANSIENT:
        definitive = False
    elif isinstance(show, dict) and isinstance(show.get("parameters"), str):
        m = re.search(r"^\s*num_ctx\s+(\d+)", show["parameters"], re.MULTILINE)
        if m:
            return _positive_int(int(m.group(1))), True
    return None, definitive


def _kind_for(exc: Exception) -> str:
    text = str(exc)
    if _NOT_CHAT_RE.search(text):
        return "not_chat"
    name = type(exc).__name__
    if "Quota" in name:
        return "quota"
    if "Fatal" in name:
        return "fatal"
    if re.search(r"connect|refused|unreachable", text, re.I):
        return "unreachable"
    return "error"


def check_chat(config: LLMConfig) -> dict:
    """Run a tiny completion and report whether the model serves chat."""
    result = {
        "ok": False,
        "provider": config.provider,
        "model": config.model,
        "error": None,
        "kind": "error",
    }
    try:
        call_llm(
            "You are a connectivity check.",
            "Reply with the word ok.",
            config=config,
            max_tokens=16,
            temperature=0.0,
        )
    except (LLMCallError, LLMConfigError) as e:
        msg = str(e)
        if config.api_key:
            msg = msg.replace(config.api_key, "***")
        result["error"] = msg
        result["kind"] = _kind_for(e)
        return result
    result["ok"] = True
    result["kind"] = "ok"
    return result
