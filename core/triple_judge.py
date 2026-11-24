#!/usr/bin/env python3
"""LLM-as-judge triple gate: score each relation against its evidence span.

Implements the GraphJudge (arXiv 2411.17388) / GraphEval (arXiv 2407.10793)
quality pattern: after extraction, each candidate triple is judged for whether
its evidence actually entails it. Verdicts convert the epistemic layer from
regex heuristics into per-edge, evidence-grounded scores.

Design: a dependency-free *lexical* judge runs by default (checks whether the
subject, object, and a relation cue appear in the evidence span) so the gate
works offline and is fully testable. Pass `judge_fn(triple, evidence) -> dict`
to defer to an LLM (via core/llm_client.call_llm) for calibrated judgments.

The LLM judge is honest about failure: it counts every fallback to the lexical
verdict, and raises JudgeAbort on quota/fatal errors, an unreachable server, or
when too many replies are unusable, so a run can never "succeed" with lexical
verdicts masquerading as LLM verdicts.

Verdict schema: {"verdict": "supported"|"unsupported"|"partial",
"score": float in [0,1], "reason": str}.
"""

from __future__ import annotations

import functools
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

from .hedging import hedge_score
from .llm_client import (
    LLMCallError,
    LLMConfigError,
    LLMFatalError,
    LLMQuotaError,
    LLMTransientError,
    extract_json_object,
)

JUDGE_PROMPT_VERSION = "2"
ABORT_FIRST_N = 5  # abort when this many calls in a row all failed from the start
ABORT_MIN_SAMPLE = 20  # fallback-rate check starts at this many calls
ABORT_MAX_FALLBACK_RATE = 0.2
ABORT_CONSECUTIVE = 5  # abort after this many failures in a row, at any point
DEFAULT_JUDGE_MAX_TOKENS = 2048
CTX_MARGIN_TOKENS = 64
JUDGE_MIN_OUTPUT_TOKENS = 64
_VALID_VERDICTS = ("supported", "partial", "unsupported")
_VERDICT_DEFAULT_SCORE = {"supported": 0.9, "partial": 0.5, "unsupported": 0.1}
_MAX_ERRORS = 5
_ERROR_CHARS = 200


class JudgeAbort(RuntimeError):
    """The judge run cannot produce trustworthy LLM verdicts and was stopped."""

    def __init__(self, message: str, stats: dict | None = None):
        super().__init__(message)
        self.stats = stats or {}

_JUDGE_SYSTEM = (
    "You are a knowledge-graph triple validator. Given a (subject, relation, "
    "object) triple and the evidence sentence it was extracted from, decide "
    "whether the evidence entails the triple. Respond with ONLY a JSON object: "
    '{"verdict": "supported"|"unsupported"|"partial", "score": 0.0-1.0, '
    '"reason": "<= 15 words"}. "supported" = evidence clearly states the '
    'relation; "partial" = related but hedged/indirect; "unsupported" = '
    "evidence does not back the triple."
)


def _tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", (text or "").lower()) if len(t) > 2}


def _name_of(node_id: str) -> str:
    """Strip a 'type:slug' node id down to human words for matching."""
    slug = node_id.split(":", 1)[-1] if ":" in node_id else node_id
    return slug.replace("_", " ").replace("-", " ")


def lexical_judge(triple: dict, evidence: str) -> dict:
    """Offline judge: score by subject/object token overlap with evidence.

    A triple is "supported" when both endpoints are grounded in the evidence;
    "partial" when only one is (or the evidence is hedged); "unsupported"
    when neither endpoint appears.
    """
    ev_tokens = _tokens(evidence)
    if not ev_tokens:
        return {"verdict": "unsupported", "score": 0.0, "reason": "no evidence text"}

    subj = _tokens(_name_of(triple.get("source", "")))
    obj = _tokens(_name_of(triple.get("target", "")))
    subj_hit = bool(subj & ev_tokens)
    obj_hit = bool(obj & ev_tokens)

    hedged = hedge_score(evidence)
    if subj_hit and obj_hit:
        score = max(0.5, 1.0 - hedged)
        verdict = "supported" if hedged < 0.25 else "partial"
        reason = "both endpoints grounded in evidence"
    elif subj_hit or obj_hit:
        score = 0.4 * (1.0 - hedged)
        verdict = "partial"
        reason = "one endpoint grounded in evidence"
    else:
        score = 0.0
        verdict = "unsupported"
        reason = "endpoints absent from evidence"
    return {"verdict": verdict, "score": round(score, 4), "reason": reason}


def _estimate_tokens(text: str) -> int:
    """Conservative token estimate (small-vocabulary models tokenise densely)."""
    return len(text) // 3 + 1


def _env_max_tokens() -> int | None:
    raw = os.environ.get("EPISTRACT_LLM_MAX_TOKENS", "").strip()
    try:
        value = int(raw)
    except ValueError:
        return None
    return value if value > 0 else None


def judge_max_tokens(config, prompt_tokens: int) -> int | None:
    """Output budget for one judge call, derived from the context window.

    Known window: min(cap, window - prompt - margin), where cap is
    EPISTRACT_LLM_MAX_TOKENS when set, else DEFAULT_JUDGE_MAX_TOKENS. Unknown
    window on the local provider: the env cap if set, else None (the server
    applies its own limit). Other providers: cap.
    """
    env_cap = _env_max_tokens()
    cap = env_cap or DEFAULT_JUDGE_MAX_TOKENS
    ctx = getattr(config, "context_window", None)
    if ctx:
        return min(cap, ctx - prompt_tokens - CTX_MARGIN_TOKENS)
    if getattr(config, "provider", None) == "local":
        return env_cap
    return cap


def _new_stats() -> dict:
    return {
        "calls": 0,
        "llm_judged": 0,
        "fallback": 0,
        "consecutive_failures": 0,
        "errors": [],
    }


def _check_abort(stats: dict) -> None:
    calls = stats["calls"]
    if calls >= ABORT_FIRST_N and stats["llm_judged"] == 0:
        raise JudgeAbort(
            f"the first {calls} judge calls all failed; last error: "
            f"{(stats['errors'] or ['unknown'])[-1]}",
            stats,
        )
    if stats["consecutive_failures"] >= ABORT_CONSECUTIVE:
        raise JudgeAbort(
            f"{stats['consecutive_failures']} judge calls in a row failed; last error: "
            f"{(stats['errors'] or ['unknown'])[-1]}",
            stats,
        )
    if calls >= ABORT_MIN_SAMPLE and stats["fallback"] / calls > ABORT_MAX_FALLBACK_RATE:
        raise JudgeAbort(
            f"{stats['fallback']} of {calls} judge calls fell back to the lexical "
            f"verdict (more than {ABORT_MAX_FALLBACK_RATE:.0%}); last error: "
            f"{(stats['errors'] or ['unknown'])[-1]}",
            stats,
        )


def _final_check(stats: dict) -> None:
    """End-of-run abort check with no minimum sample size."""
    calls = stats["calls"]
    if calls <= 0:
        return
    last = (stats["errors"] or ["unknown"])[-1]
    if stats["llm_judged"] == 0:
        raise JudgeAbort(f"none of {calls} judge calls produced an LLM verdict; last error: {last}", stats)
    if stats["fallback"] / calls > ABORT_MAX_FALLBACK_RATE:
        raise JudgeAbort(
            f"{stats['fallback']} of {calls} judge calls fell back to the lexical "
            f"verdict (more than {ABORT_MAX_FALLBACK_RATE:.0%}); last error: {last}",
            stats,
        )


def _parse_reply(raw: str) -> dict:
    """Validate a judge reply into a 3-key verdict; ValueError when unusable."""
    parsed = extract_json_object(raw)
    verdict = str(parsed.get("verdict", "")).strip().lower()
    if verdict not in _VALID_VERDICTS:
        raise ValueError(f"unknown verdict {parsed.get('verdict')!r}")
    if parsed.get("score") is None:
        score = _VERDICT_DEFAULT_SCORE[verdict]
    else:
        score = float(parsed["score"])
        if score != score:  # NaN
            raise ValueError("score is NaN")
    return {
        "verdict": verdict,
        "score": max(0.0, min(1.0, score)),
        "reason": str(parsed.get("reason", ""))[:120],
    }


def make_llm_judge(call_fn=None, *, config=None):
    """Build a judge_fn backed by an LLM; ``call_fn`` defaults to ``call_llm``.

    With no ``call_fn`` the provider config is resolved eagerly and
    LLMConfigError is raised when no credentials exist. The returned callable
    exposes ``stats`` (calls, llm_judged, fallback, consecutive_failures,
    errors), ``config``, ``model`` and ``finalize()`` (the end-of-run abort
    check, called by judge_graph). A single unusable reply degrades to the
    lexical verdict and is counted as a fallback. Quota, fatal and config
    errors, any connection failure (after transport retries), consecutive
    failures and too many fallbacks raise JudgeAbort.
    """
    if call_fn is None:
        from .llm_client import call_llm, resolve_api_config  # noqa: PLC0415

        config = config or resolve_api_config()
        if config is None:
            raise LLMConfigError(
                "No API key found. Set one of: AZURE_FOUNDRY_API_KEY (with "
                "AZURE_FOUNDRY_BASE_URL or AZURE_FOUNDRY_RESOURCE); "
                "ANTHROPIC_API_KEY; OPENROUTER_API_KEY; "
                "EPISTRACT_LLM_BASE_URL (local OpenAI-compatible server)."
            )
        call_fn = functools.partial(call_llm, config=config)

    provider = getattr(config, "provider", None)
    send_effort = provider not in ("local", "openrouter")
    stats = _new_stats()

    def _build(triple: dict, evidence: str) -> tuple[str, int | None]:
        ev = evidence or ""
        while True:
            user = json.dumps(
                {
                    "subject": _name_of(triple.get("source", "")),
                    "relation": triple.get("relation_type", ""),
                    "object": _name_of(triple.get("target", "")),
                    "evidence": ev,
                }
            )
            if config is None:
                return user, DEFAULT_JUDGE_MAX_TOKENS
            max_tokens = judge_max_tokens(config, _estimate_tokens(_JUDGE_SYSTEM + user))
            if max_tokens is None or max_tokens >= JUDGE_MIN_OUTPUT_TOKENS or not ev:
                if max_tokens is not None:
                    max_tokens = max(max_tokens, JUDGE_MIN_OUTPUT_TOKENS)
                return user, max_tokens
            ev = ev[: len(ev) // 2]

    def _fail(triple: dict, evidence: str, exc: Exception) -> dict:
        stats["fallback"] += 1
        stats["consecutive_failures"] += 1
        if len(stats["errors"]) < _MAX_ERRORS:
            stats["errors"].append(f"{type(exc).__name__}: {exc}"[:_ERROR_CHARS])
        _check_abort(stats)
        return lexical_judge(triple, evidence)

    def _judge(triple: dict, evidence: str) -> dict:
        stats["calls"] += 1
        user, max_tokens = _build(triple, evidence)
        kwargs = {"max_tokens": max_tokens, "temperature": 0.0}
        if send_effort:
            kwargs["effort"] = "low"
        try:
            raw = call_fn(_JUDGE_SYSTEM, user, **kwargs)
            verdict = _parse_reply(raw)
        except (LLMQuotaError, LLMFatalError, LLMConfigError) as e:
            raise JudgeAbort(f"{type(e).__name__}: {e}"[:_ERROR_CHARS], stats) from e
        except LLMTransientError as e:
            if e.connect:
                raise JudgeAbort(f"cannot reach the LLM server: {e}"[:_ERROR_CHARS], stats) from e
            return _fail(triple, evidence, e)
        except (LLMCallError, ValueError, TypeError, KeyError) as e:
            return _fail(triple, evidence, e)
        stats["consecutive_failures"] = 0
        stats["llm_judged"] += 1
        return verdict

    _judge.stats = stats
    _judge.finalize = lambda: _final_check(stats)
    _judge.config = config
    _judge.model = getattr(config, "model", None) or "custom"
    return _judge


def link_key(link: dict) -> str:
    """Stable id for a link: its relation_id, else source|relation_type|target."""
    rid = link.get("relation_id")
    if rid:
        return str(rid)
    return f"{link.get('source')}|{link.get('relation_type')}|{link.get('target')}"


def record_key(link: dict) -> str:
    """Checkpoint record key: link_key plus a short hash of the evidence text."""
    digest = hashlib.blake2b((link.get("evidence") or "").encode("utf-8"), digest_size=8)
    return f"{link_key(link)}#{digest.hexdigest()}"


def graph_hash(links: list[dict], model: str) -> str:
    """Hash binding a checkpoint to the links' evidence, the model and the prompt."""
    payload = json.dumps(
        sorted((link_key(lk), lk.get("evidence") or "") for lk in links)
    )
    digest = hashlib.blake2b()
    digest.update(payload.encode("utf-8"))
    digest.update(str(model).encode("utf-8"))
    digest.update(JUDGE_PROMPT_VERSION.encode("utf-8"))
    return digest.hexdigest()


def _valid_cached(v) -> bool:
    if not isinstance(v, dict) or v.get("verdict") not in _VALID_VERDICTS:
        return False
    score = v.get("score")
    return isinstance(score, (int, float)) and not isinstance(score, bool) and 0.0 <= score <= 1.0


def _load_checkpoint(path: Path, ghash: str) -> dict | None:
    """Cached verdicts when the header hash matches, else None (start fresh)."""
    try:
        with path.open(encoding="utf-8") as fh:
            header = json.loads(fh.readline())
            if not isinstance(header, dict) or header.get("graph_hash") != ghash:
                return None
            cached: dict = {}
            for line in fh:
                try:
                    rec = json.loads(line)
                    key, v = rec["id"], rec["v"]
                    origin = rec.get("origin", "llm")
                except (ValueError, KeyError, TypeError):
                    continue
                if _valid_cached(v):
                    cached[str(key)] = {
                        "verdict": v["verdict"],
                        "score": float(v["score"]),
                        "reason": str(v.get("reason", ""))[:120],
                        "origin": str(origin),
                    }
            return cached
    except (OSError, ValueError):
        return None


def judge_graph(
    graph_data: dict,
    judge_fn=None,
    min_score: float = 0.35,
    *,
    checkpoint_path: Path | None = None,
    resume: bool = True,
    progress: bool = False,
    progress_every: int = 10,
    stream=None,
) -> dict:
    """Judge every relation in a graph and annotate edges with the verdict.

    Mutates each link with judge_verdict / judge_score / judge_reason and a
    boolean `gated` (True when score < min_score → the triple is a
    filtering candidate). Links without evidence text keep the lexical
    verdict (unsupported, 0.0) and never reach the judge. With
    ``checkpoint_path`` each real LLM verdict is appended to a JSONL file and
    reused on the next run when the graph hash matches. JudgeAbort propagates;
    verdicts written so far stay in the checkpoint.
    """
    judge = judge_fn or lexical_judge
    stats = getattr(judge, "stats", None)
    links = graph_data.get("links", graph_data.get("edges", []))
    counts = {"supported": 0, "partial": 0, "unsupported": 0}
    flagged: list[dict] = []
    resumed = 0
    resumed_llm = 0
    skipped_no_evidence = 0
    live = 0
    total = len(links)
    out = stream or sys.stderr
    started = time.monotonic()

    cached: dict = {}
    ckpt = None
    # Only an LLM judge (one exposing live stats) may own a checkpoint; a
    # lexical/plain judge must never truncate or rewrite an LLM checkpoint.
    llm_judge = stats is not None
    if checkpoint_path is not None and llm_judge:
        checkpoint_path = Path(checkpoint_path)
        ghash = graph_hash(links, getattr(judge, "model", "custom"))
        loaded = _load_checkpoint(checkpoint_path, ghash) if resume else None
        if loaded is None:
            ckpt = checkpoint_path.open("w", encoding="utf-8")
            ckpt.write(
                json.dumps(
                    {
                        "type": "header",
                        "graph_hash": ghash,
                        "model": getattr(judge, "model", "custom"),
                        "prompt_version": JUDGE_PROMPT_VERSION,
                    }
                )
                + "\n"
            )
            ckpt.flush()
        else:
            cached = loaded
            needs_nl = False
            try:
                with checkpoint_path.open("rb") as raw:
                    raw.seek(0, 2)
                    if raw.tell() > 0:
                        raw.seek(-1, 2)
                        needs_nl = raw.read(1) != b"\n"
            except OSError:
                pass
            ckpt = checkpoint_path.open("a", encoding="utf-8")
            if needs_nl:  # torn last line from a crash: terminate it
                ckpt.write("\n")

    def _report(i: int) -> None:
        elapsed = max(time.monotonic() - started, 1e-9)
        rate = live / elapsed * 60.0
        eta = int((total - i) / (live / elapsed)) if live else 0
        mm, ss = divmod(eta, 60)
        done = stats or {}
        print(
            f"  judge: {i}/{total} ({rate:.1f}/min, ETA {mm}:{ss:02d}) "
            f"llm={done.get('llm_judged', 0)} fallback={done.get('fallback', 0)} "
            f"resumed={resumed}",
            file=out,
            flush=True,
        )

    try:
        for i, link in enumerate(links, 1):
            evidence = link.get("evidence", "")
            key = record_key(link)
            if not (evidence or "").strip():
                verdict = lexical_judge(link, "")
                skipped_no_evidence += 1
            elif key in cached:
                verdict = cached[key]
                resumed += 1
                if verdict.get("origin") == "llm":
                    resumed_llm += 1
            else:
                before = stats["llm_judged"] if stats is not None else 0
                live += 1
                verdict = judge(link, evidence)
                if ckpt is not None and stats is not None and stats["llm_judged"] > before:
                    ckpt.write(json.dumps({"id": key, "v": verdict, "origin": "llm"}) + "\n")
                    ckpt.flush()
            link["judge_verdict"] = verdict["verdict"]
            link["judge_score"] = verdict["score"]
            link["judge_reason"] = verdict["reason"]
            link["gated"] = verdict["score"] < min_score
            counts[verdict["verdict"]] = counts.get(verdict["verdict"], 0) + 1
            if link["gated"]:
                flagged.append(
                    {
                        "source": link.get("source"),
                        "target": link.get("target"),
                        "relation_type": link.get("relation_type"),
                        "score": verdict["score"],
                        "reason": verdict["reason"],
                    }
                )
            if progress and (i % max(1, progress_every) == 0 or i == total):
                _report(i)
        if stats is not None and hasattr(judge, "finalize"):
            judge.finalize()
    finally:
        if ckpt is not None:
            ckpt.close()

    return {
        "total": total,
        "verdict_counts": counts,
        "gated_count": len(flagged),
        "min_score": min_score,
        "flagged": flagged,
        "llm_judged": (stats["llm_judged"] if stats else 0) + resumed_llm,
        "fallback": stats["fallback"] if stats else 0,
        "resumed": resumed,
        "skipped_no_evidence": skipped_no_evidence,
        "errors": list(stats["errors"]) if stats else [],
    }
