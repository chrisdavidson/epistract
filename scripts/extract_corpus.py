#!/usr/bin/env python3
"""Direct-call corpus extraction via an OpenAI-compatible endpoint (OpenRouter or a local server).

Reads ingested/<doc_id>.txt, chunks via core.chunk_document (exercises
FIDL-03 overlap), calls the configured model through an OpenAI-compatible
endpoint (OpenRouter by default, or a local server given --base-url), merges and dedupes entities/relations across chunks, persists via
core/build_extraction.py subprocess (same Pydantic validation path the agent
uses). Resume-safe: skips documents whose extraction JSON already exists.

Usage:
    python scripts/extract_corpus.py <output_dir> --domain drug-discovery
    python scripts/extract_corpus.py tests/corpora/06_glp1_landscape/output-v3 \\
        --domain drug-discovery \\
        --model anthropic/claude-sonnet-4.6
    python scripts/extract_corpus.py <output_dir> --base-url http://localhost:8080

Expects ingested/<doc_id>.txt to already exist under <output_dir>. Run
`python -m core.ingest_documents <corpus_dir> --output <output_dir>
--domain <domain>` first.

Env:
    OPENROUTER_API_KEY — required for OpenRouter (the default target).
    EPISTRACT_LLM_BASE_URL — local OpenAI-compatible server; selects the local
        target (--base-url overrides it). No API key is needed.
    EPISTRACT_LLM_MODEL — local model id (default: the server's first chat model).
    EPISTRACT_LLM_API_KEY — bearer key for a local server that requires one.
    EPISTRACT_LLM_PROVIDER — "local" or "openrouter"; forces the target when a
        base URL is also set.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from core.chunk_document import MAX_CHUNK_SIZE, chunk_document  # noqa: E402
from core.domain_resolver import resolve_domain  # noqa: E402
from core.llm_client import (  # noqa: E402
    ERR_FATAL,
    ERR_PER_ITEM,
    ERR_QUOTA,
    LOCAL_PLACEHOLDER_KEY,
    LLMConfigError,
    classify_error,
    extract_json_object,
    normalise_base_url,
)
from core.llm_local import list_models, pick_chat_model, probe_context  # noqa: E402

try:
    import openai
    from openai import OpenAI
except ImportError as e:
    raise SystemExit(
        "openai SDK is required. Install with: uv pip install openai"
    ) from e


USER_PROMPT_TEMPLATE = """Extract entities and relations from the following document chunk using the domain schema above.

Return ONLY a single JSON object with exactly two top-level fields: `entities` (array) and `relations` (array). No markdown fences, no commentary, no explanation — just the JSON.

Document chunk:
---
{chunk_text}
---
"""


DEFAULT_OPENROUTER_MODEL = "anthropic/claude-sonnet-4.6"
OPENROUTER_API_BASE = "https://openrouter.ai/api/v1"
DEFAULT_MAX_TOKENS = 8192
_MIN_USEFUL_OUTPUT_TOKENS = 256
_CTX_SAFETY_TOKENS = 64
_ERROR_EXCERPT_CHARS = 300

# Indirection so tests can run the retry loop without real waits.
_sleep = time.sleep


class ExtractStop(RuntimeError):
    """A quota or fatal provider error: no later call can succeed, so stop the run."""

    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind


def _estimate_tokens(text: str) -> int:
    """Rough token estimate (3 characters per token, deliberately pessimistic)."""
    return len(text) // 3


def _resolve_target(base_url_arg: str | None, model_arg: str | None) -> dict:
    """Decide provider, endpoint, key and model. Raises ValueError with a usable message."""
    provider_env = os.environ.get("EPISTRACT_LLM_PROVIDER", "").strip().lower()
    if provider_env and provider_env not in ("local", "openrouter"):
        raise ValueError(
            f"EPISTRACT_LLM_PROVIDER={provider_env!r} is not supported by "
            "extract_corpus; it supports local and openrouter"
        )
    base_url = (base_url_arg or "").strip() or os.environ.get(
        "EPISTRACT_LLM_BASE_URL", ""
    ).strip()
    if base_url_arg:
        provider = "local"
    elif provider_env:
        provider = provider_env
    else:
        provider = "local" if base_url else "openrouter"

    if provider == "local":
        if not base_url:
            raise ValueError(
                "EPISTRACT_LLM_PROVIDER=local needs --base-url or EPISTRACT_LLM_BASE_URL"
            )
        try:
            api_base = normalise_base_url(base_url)
        except LLMConfigError as e:
            raise ValueError(str(e)) from None
        real_key = os.environ.get("EPISTRACT_LLM_API_KEY", "").strip() or None
        model = (model_arg or "").strip() or os.environ.get(
            "EPISTRACT_LLM_MODEL", ""
        ).strip()
        if not model:
            try:
                ids = [m["id"] for m in list_models(api_base, real_key)]
            except Exception as e:  # noqa: BLE001 - LLMCallError; message has no key
                raise ValueError(
                    f"could not determine a chat model at {api_base}; set --model "
                    f"or EPISTRACT_LLM_MODEL ({e})"
                ) from None
            model = pick_chat_model(ids) or ""
            if not model:
                raise ValueError(
                    f"no chat-capable model is served at {api_base}; set --model "
                    "or EPISTRACT_LLM_MODEL"
                )
        return {
            "provider": "local",
            "api_base": api_base,
            "api_key": real_key or LOCAL_PLACEHOLDER_KEY,
            "real_key": real_key,
            "model": model,
        }

    api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        raise ValueError(
            "OPENROUTER_API_KEY not set (or pass --base-url / set "
            "EPISTRACT_LLM_BASE_URL to use a local server)"
        )
    return {
        "provider": "openrouter",
        "api_base": OPENROUTER_API_BASE,
        "api_key": api_key,
        "real_key": api_key,
        "model": (model_arg or "").strip() or DEFAULT_OPENROUTER_MODEL,
    }


def _context_fit_warning(
    system_prompt: str,
    n_ctx: int | None,
    model: str,
    max_tokens: int,
    chunk_chars: int,
) -> str | None:
    """Warning text when system prompt + one chunk + output budget exceed the window."""
    if not n_ctx:
        return None
    required = (
        _estimate_tokens(system_prompt) + chunk_chars // 3 + max_tokens
    )
    if required <= n_ctx:
        return None
    return (
        f"WARNING: model {model} has a context window of {n_ctx} tokens, but the "
        f"domain prompt ({_estimate_tokens(system_prompt)} tokens est.) plus one chunk "
        f"(~{chunk_chars // 3} tokens) plus an output budget of {max_tokens} tokens "
        f"needs about {required} tokens.\n"
        "This model cannot do extraction for this domain; every call is expected "
        f"to fail. Use a model with at least ~{required} tokens of context."
    )


def _request_budget(
    provider: str, n_ctx: int | None, system_prompt: str, user_prompt: str
) -> int | None:
    """Output-token budget for one call; None means omit max_tokens (local, window unknown).

    Raises RuntimeError when the window leaves no room for a useful answer.
    """
    if provider != "local":
        return DEFAULT_MAX_TOKENS
    if not n_ctx:
        return None
    room = (
        n_ctx
        - _estimate_tokens(system_prompt)
        - _estimate_tokens(user_prompt)
        - _CTX_SAFETY_TOKENS
    )
    if room < _MIN_USEFUL_OUTPUT_TOKENS:
        raise RuntimeError(
            f"chunk does not fit the model context window (n_ctx={n_ctx}); "
            "use a larger context"
        )
    return min(DEFAULT_MAX_TOKENS, room)


def call_llm(
    client: OpenAI,
    model: str,
    system_prompt: str,
    chunk_text: str,
    max_retries: int = 3,
    max_tokens: int | None = DEFAULT_MAX_TOKENS,
) -> tuple[list, list, float, int]:
    """Call the model once; return (entities, relations, cost_usd, total_tokens).

    Transient errors (5xx, short rate limits, connection failures) and
    unparseable replies retry up to max_retries with bounded backoff. Quota and
    other deterministic 4xx errors raise ExtractStop immediately; a request the
    server rejects for size fails the chunk without retrying.
    """
    kwargs: dict = {}
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens
    last_err: Exception | None = None
    for attempt in range(max_retries):
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": USER_PROMPT_TEMPLATE.format(chunk_text=chunk_text),
                    },
                ],
                temperature=0.0,
                **kwargs,
            )
            content = resp.choices[0].message.content or ""
            data = extract_json_object(content)

            usage = getattr(resp, "usage", None)
            total_tokens = getattr(usage, "total_tokens", 0) if usage else 0
            cost = getattr(usage, "cost", None) if usage is not None else None

            return (
                data.get("entities", []),
                data.get("relations", []),
                float(cost or 0.0),
                int(total_tokens or 0),
            )
        except ExtractStop:
            raise
        except openai.APIStatusError as e:
            last_err = e
            text = (getattr(e.response, "text", "") or "")[:_ERROR_EXCERPT_CHARS]
            kind = classify_error(e.status_code, e.response.headers, text)
            if kind in (ERR_QUOTA, ERR_FATAL):
                raise ExtractStop(kind, f"{kind}: HTTP {e.status_code}: {text}") from None
            if kind == ERR_PER_ITEM:
                raise RuntimeError(
                    f"server rejected the request (HTTP {e.status_code}): {text}"
                ) from None
        except openai.APIConnectionError as e:
            last_err = e
        except ValueError as e:  # unparseable reply
            last_err = e
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(f"LLM call failed: {type(e).__name__}: {e}") from None
        if attempt + 1 < max_retries:
            _sleep(min(2**attempt, 30))

    raise RuntimeError(f"LLM call failed after {max_retries} retries: {last_err}")


def _dedupe_entities(entities: list[dict]) -> list[dict]:
    """Dedupe by (name, entity_type); keep the first occurrence, merge attributes."""
    out: list[dict] = []
    index: dict[tuple[str, str], int] = {}
    for e in entities:
        key = (str(e.get("name", "")).strip(), str(e.get("entity_type") or e.get("type") or "").strip())
        if not key[0]:
            continue
        if key in index:
            # merge attributes (prefer existing values)
            existing = out[index[key]]
            for k, v in (e.get("attributes") or {}).items():
                existing.setdefault("attributes", {}).setdefault(k, v)
        else:
            index[key] = len(out)
            out.append(e)
    return out


def _normalize_relation(r: dict) -> dict:
    """Normalize source/target field name variants to source_entity/target_entity."""
    if "source_entity" not in r and "source" in r:
        r = {**r, "source_entity": r["source"]}
    if "target_entity" not in r and "target" in r:
        r = {**r, "target_entity": r["target"]}
    return r


def _dedupe_relations(relations: list[dict]) -> list[dict]:
    """Dedupe by (source, target, relation_type)."""
    seen: set[tuple[str, str, str]] = set()
    out: list[dict] = []
    for r in relations:
        r = _normalize_relation(r)
        key = (
            str(r.get("source_entity", "")).strip(),
            str(r.get("target_entity", "")).strip(),
            str(r.get("relation_type") or r.get("type") or "").strip(),
        )
        if key in seen or not all(key):
            continue
        seen.add(key)
        out.append(r)
    return out


def extract_document(
    doc_id: str,
    ingested_dir: Path,
    client: OpenAI,
    model: str,
    system_prompt: str,
    output_dir: Path,
    domain: str,
    provider: str = "openrouter",
    n_ctx: int | None = None,
) -> dict:
    """Extract one document end-to-end. Returns run metadata."""
    text_path = ingested_dir / f"{doc_id}.txt"
    if not text_path.exists():
        return {"doc_id": doc_id, "error": f"missing ingested text: {text_path}"}

    text = text_path.read_text(encoding="utf-8")
    chunks = chunk_document(text, doc_id)

    all_entities: list[dict] = []
    all_relations: list[dict] = []
    total_cost = 0.0
    total_tokens = 0

    for chunk in chunks:
        budget = _request_budget(
            provider,
            n_ctx,
            system_prompt,
            USER_PROMPT_TEMPLATE.format(chunk_text=chunk["text"]),
        )
        entities, relations, cost, tokens = call_llm(
            client, model, system_prompt, chunk["text"], max_tokens=budget
        )
        all_entities.extend(entities)
        all_relations.extend(relations)
        total_cost += cost
        total_tokens += tokens

    entities = _dedupe_entities(all_entities)
    relations = _dedupe_relations(all_relations)

    payload = json.dumps({"entities": entities, "relations": relations})
    cmd = [
        sys.executable,
        str(_PROJECT_ROOT / "core" / "build_extraction.py"),
        doc_id,
        str(output_dir),
        "--domain",
        domain,
        "--model",
        model,
        "--cost",
        f"{total_cost:.6f}",
        "--json",
        payload,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)

    return {
        "doc_id": doc_id,
        "chunks": len(chunks),
        "entities": len(entities),
        "relations": len(relations),
        "cost_usd": total_cost,
        "total_tokens": total_tokens,
        "build_extraction_rc": result.returncode,
        "build_extraction_stderr": result.stderr.strip() if result.stderr else "",
    }


def _write_summary(output_dir: Path, summary: dict) -> None:
    (output_dir / "extract_run.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "output_dir",
        help="Output directory containing ingested/ (from core.ingest_documents)",
    )
    parser.add_argument("--domain", default="drug-discovery")
    parser.add_argument(
        "--model",
        default=None,
        help=(
            f"Model id. Defaults to {DEFAULT_OPENROUTER_MODEL} on OpenRouter; on a "
            "local server, EPISTRACT_LLM_MODEL or the server's first chat model"
        ),
    )
    parser.add_argument(
        "--base-url",
        default=None,
        help=(
            "Local OpenAI-compatible server (e.g. http://localhost:8080). "
            "Overrides EPISTRACT_LLM_BASE_URL; no OPENROUTER_API_KEY needed"
        ),
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-extract even when output-dir/extractions/<doc_id>.json exists",
    )
    parser.add_argument(
        "--limit", type=int, default=0, help="Stop after N docs (0 = all)"
    )
    args = parser.parse_args()

    try:
        target = _resolve_target(args.base_url, args.model)
    except ValueError as e:
        print(
            f"ERROR: {e}\nSet OPENROUTER_API_KEY for OpenRouter, or "
            "EPISTRACT_LLM_BASE_URL / --base-url for a local server.",
            file=sys.stderr,
        )
        return 2
    provider = target["provider"]
    model = target["model"]

    domain_info = resolve_domain(args.domain)
    skill_path = Path(domain_info["skill_path"])
    system_prompt = skill_path.read_text(encoding="utf-8")

    output_dir = Path(args.output_dir).resolve()
    ingested_dir = output_dir / "ingested"
    extractions_dir = output_dir / "extractions"
    extractions_dir.mkdir(parents=True, exist_ok=True)

    doc_files = sorted(ingested_dir.glob("*.txt"))
    if not doc_files:
        print(f"ERROR: no ingested/*.txt under {output_dir}", file=sys.stderr)
        return 2

    client_kwargs: dict = {}
    if provider == "local":
        import httpx

        # Local servers must be reached directly, never through an env proxy.
        client_kwargs["http_client"] = httpx.Client(trust_env=False, timeout=600.0)
    client = OpenAI(
        api_key=target["api_key"],
        base_url=target["api_base"],
        max_retries=0,
        **client_kwargs,
    )
    print(
        f"extract_corpus: provider={provider} model={model} base_url={target['api_base']}",
        file=sys.stderr,
    )

    n_ctx: int | None = None
    if provider == "local":
        n_ctx = probe_context(target["api_base"], model, target["real_key"])
        warning = _context_fit_warning(
            system_prompt, n_ctx, model, DEFAULT_MAX_TOKENS, MAX_CHUNK_SIZE
        )
        if warning:
            print(warning, file=sys.stderr)

    total_cost = 0.0
    total_tokens = 0
    results: list[dict] = []
    skipped = 0
    failed = 0
    done = 0
    stopped: str | None = None
    stop_message = ""

    count = 0
    for doc_path in doc_files:
        doc_id = doc_path.stem
        extraction_file = extractions_dir / f"{doc_id}.json"
        count += 1
        if args.limit and count > args.limit:
            break
        if extraction_file.exists() and not args.force:
            print(f"[{count}/{len(doc_files)}] SKIP {doc_id}")
            skipped += 1
            continue

        print(
            f"[{count}/{len(doc_files)}] EXTRACT {doc_id} ...", end=" ", flush=True
        )
        start = time.time()
        try:
            r = extract_document(
                doc_id,
                ingested_dir,
                client,
                model,
                system_prompt,
                output_dir,
                args.domain,
                provider=provider,
                n_ctx=n_ctx,
            )
            elapsed = time.time() - start
            if "error" in r:
                print(f"FAIL: {r['error']} ({elapsed:.1f}s)")
                failed += 1
            else:
                cost_text = f"${r['cost_usd']:.4f}" if provider == "openrouter" else "cost n/a"
                print(
                    f"{r['entities']}E/{r['relations']}R "
                    f"tok={r['total_tokens']} {cost_text} "
                    f"rc={r['build_extraction_rc']} ({elapsed:.1f}s)"
                )
                total_cost += r["cost_usd"]
                total_tokens += r["total_tokens"]
                done += 1
            results.append(r)
        except ExtractStop as e:
            print(f"STOP: {e}")
            stopped = e.kind
            stop_message = str(e)
            failed += 1
            results.append({"doc_id": doc_id, "error": str(e)})
            break
        except Exception as e:
            elapsed = time.time() - start
            print(f"FAIL: {e} ({elapsed:.1f}s)")
            failed += 1
            results.append({"doc_id": doc_id, "error": str(e)})

    summary = {
        "docs_total": len(doc_files),
        "docs_done": done,
        "docs_skipped": skipped,
        "docs_failed": failed,
        "total_cost_usd": total_cost if provider == "openrouter" else None,
        "total_tokens": total_tokens,
        "provider": provider,
        "base_url": target["api_base"],
        "model": model,
        "domain": args.domain,
        "results": results,
    }
    if stopped:
        summary["stopped"] = stopped
    _write_summary(output_dir, summary)
    if stopped:
        print(
            f"ERROR: stopping extraction: {stop_message}",
            file=sys.stderr,
        )
        return 3
    cost_summary = f"${total_cost:.4f}" if provider == "openrouter" else "cost n/a"
    print(
        f"\n=== DONE: {done} new, {skipped} skipped, {failed} failed "
        f"| {cost_summary} | {total_tokens} tokens ==="
    )
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
