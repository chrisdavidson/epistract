"""Judge accounting, abort rules, strict parsing, token budget, progress, checkpoint.

Covers LOCAL-04 (honest judge), LOCAL-06 (tolerant parsing) and LOCAL-08
(observable, resumable runs).
"""
from __future__ import annotations

import io
import json

import pytest

from core import triple_judge
from core.llm_client import (
    LLMCallError,
    LLMConfig,
    LLMConfigError,
    LLMFatalError,
    LLMQuotaError,
    LLMTransientError,
)
from core.triple_judge import (
    JUDGE_PROMPT_VERSION,
    JudgeAbort,
    graph_hash,
    judge_graph,
    judge_max_tokens,
    link_key,
    make_llm_judge,
)

FENCE = "`" * 3
TRIPLE = {"source": "a:x", "target": "b:y", "relation_type": "R"}
GOOD = '{"verdict": "supported", "score": 0.8, "reason": "ok"}'


def _local_cfg(ctx):
    return LLMConfig("k", "http://h/v1", "m", "local", ctx)


def _seq(replies):
    """call_fn returning/raising successive items."""
    it = iter(replies)

    def fn(system, user, **kw):
        item = next(it)
        if isinstance(item, Exception):
            raise item
        return item

    return fn


# -- construction -----------------------------------------------------------
def test_make_llm_judge_without_credentials_raises(monkeypatch):
    for v in ("AZURE_FOUNDRY_API_KEY", "ANTHROPIC_FOUNDRY_API_KEY",
              "ANTHROPIC_API_KEY", "OPENROUTER_API_KEY"):
        monkeypatch.delenv(v, raising=False)
    with pytest.raises(LLMConfigError):
        make_llm_judge()


def test_injected_call_fn_needs_no_config_and_starts_clean():
    judge = make_llm_judge(call_fn=lambda s, u, **k: GOOD)
    assert judge.stats == {"calls": 0, "llm_judged": 0, "fallback": 0,
                           "consecutive_failures": 0, "errors": []}
    assert judge.config is None and judge.model == "custom"


# -- parsing ----------------------------------------------------------------
def test_fenced_reply_with_string_score_and_mixed_case_verdict():
    reply = f'{FENCE}json\n{{"verdict": "Supported", "score": "0.8", "reason": "ok"}}\n{FENCE}'
    judge = make_llm_judge(call_fn=lambda s, u, **k: reply)
    assert judge(TRIPLE, "ev") == {"verdict": "supported", "score": 0.8, "reason": "ok"}
    assert judge.stats["llm_judged"] == 1


@pytest.mark.parametrize("verdict,score", [("supported", 0.9), ("partial", 0.5), ("unsupported", 0.1)])
def test_missing_score_is_derived(verdict, score):
    judge = make_llm_judge(call_fn=lambda s, u, **k: json.dumps({"verdict": verdict}))
    assert judge(TRIPLE, "ev")["score"] == score


def test_score_clamped():
    judge = make_llm_judge(call_fn=lambda s, u, **k: '{"verdict":"supported","score":7}')
    assert judge(TRIPLE, "ev")["score"] == 1.0


def test_unknown_verdict_is_fallback():
    judge = make_llm_judge(call_fn=lambda s, u, **k: '{"verdict": "maybe"}')
    v = judge(TRIPLE, "X relates to Y")
    assert set(v) == {"verdict", "score", "reason"}
    assert judge.stats["fallback"] == 1
    assert "verdict" in judge.stats["errors"][0]


def test_unparseable_reply_returns_three_key_lexical_verdict():
    judge = make_llm_judge(call_fn=lambda s, u, **k: "not json")
    assert set(judge(TRIPLE, "X relates to Y.")) == {"verdict", "score", "reason"}
    assert judge.stats["fallback"] == 1


# -- abort rules ------------------------------------------------------------
@pytest.mark.parametrize("exc", [
    LLMQuotaError("daily quota"), LLMFatalError("bad model", status=404),
    LLMConfigError("no key"),
])
def test_quota_fatal_config_abort(exc):
    judge = make_llm_judge(call_fn=_seq([exc]))
    with pytest.raises(JudgeAbort) as ei:
        judge(TRIPLE, "ev")
    assert type(exc).__name__ in str(ei.value)
    assert ei.value.stats is judge.stats


def test_connect_error_before_success_aborts():
    judge = make_llm_judge(call_fn=_seq([LLMTransientError("down", connect=True)]))
    with pytest.raises(JudgeAbort):
        judge(TRIPLE, "ev")


def test_connect_error_after_success_is_fallback():
    judge = make_llm_judge(call_fn=_seq([GOOD, LLMTransientError("blip", connect=True)]))
    judge(TRIPLE, "ev")
    judge(TRIPLE, "ev")
    assert judge.stats["fallback"] == 1 and judge.stats["llm_judged"] == 1


def test_local_read_timeout_is_per_item_fallback_not_abort():
    err = LLMTransientError("read timeout", connect=False, retryable=False)
    judge = make_llm_judge(call_fn=_seq([err, GOOD]))
    judge(TRIPLE, "ev")
    assert judge.stats["fallback"] == 1
    assert judge(TRIPLE, "ev")["verdict"] == "supported"


def test_read_timeouts_count_toward_first_n_abort():
    err = LLMTransientError("read timeout", retryable=False)
    judge = make_llm_judge(call_fn=_seq([err] * 5))
    for _ in range(4):
        judge(TRIPLE, "ev")
    with pytest.raises(JudgeAbort):
        judge(TRIPLE, "ev")


def test_first_five_failures_abort_on_fifth():
    judge = make_llm_judge(call_fn=lambda s, u, **k: "not json")
    for _ in range(4):
        judge(TRIPLE, "ev")
    with pytest.raises(JudgeAbort):
        judge(TRIPLE, "ev")


def _run(pattern):
    """pattern: list of bool (True = bad reply)."""
    replies = ["not json" if bad else GOOD for bad in pattern]
    judge = make_llm_judge(call_fn=_seq(replies))
    for i in range(len(pattern)):
        judge(TRIPLE, "ev")
    return judge


def test_fallback_rate_over_20_percent_aborts():
    pattern = [False] * 25
    for i in (3, 7, 11, 15, 19, 22):  # 6 failures; 24% at 25 calls
        pattern[i] = True
    with pytest.raises(JudgeAbort):
        _run(pattern)


def test_fallback_rate_under_threshold_does_not_abort():
    pattern = [False] * 25
    for i in (3, 9, 15, 21):  # 4 of 25
        pattern[i] = True
    assert _run(pattern).stats["fallback"] == 4


def test_other_call_errors_are_fallbacks():
    judge = make_llm_judge(call_fn=_seq([GOOD, LLMCallError("context overflow")]))
    judge(TRIPLE, "ev")
    judge(TRIPLE, "ev")
    assert judge.stats["fallback"] == 1


def test_errors_capped_and_truncated():
    judge = make_llm_judge(call_fn=_seq([GOOD] + [LLMCallError("x" * 500)] * 5))
    for _ in range(6):
        judge(TRIPLE, "ev")
    assert len(judge.stats["errors"]) == 5
    assert all(len(e) <= 200 for e in judge.stats["errors"])


# -- max_tokens policy ------------------------------------------------------
def test_judge_max_tokens_known_window():
    assert judge_max_tokens(_local_cfg(4096), 300) == 2048
    assert judge_max_tokens(_local_cfg(2048), 300) == 1684


def test_judge_max_tokens_unknown_window():
    assert judge_max_tokens(_local_cfg(None), 300) is None
    for provider in ("anthropic", "openrouter", "foundry"):
        assert judge_max_tokens(LLMConfig("k", "u", "m", provider), 300) == 2048


def test_judge_max_tokens_env_cap(monkeypatch):
    monkeypatch.setenv("EPISTRACT_LLM_MAX_TOKENS", "512")
    assert judge_max_tokens(_local_cfg(4096), 300) == 512
    assert judge_max_tokens(_local_cfg(None), 300) == 512
    assert judge_max_tokens(LLMConfig("k", "u", "m", "anthropic"), 300) == 512
    assert judge_max_tokens(_local_cfg(600), 300) == 236  # window is tighter


@pytest.mark.parametrize("bad", ["abc", "0", "-3", ""])
def test_judge_max_tokens_ignores_invalid_env(monkeypatch, bad):
    monkeypatch.setenv("EPISTRACT_LLM_MAX_TOKENS", bad)
    assert judge_max_tokens(_local_cfg(4096), 300) == 2048
    assert judge_max_tokens(_local_cfg(None), 300) is None


def test_small_window_truncates_evidence_to_keep_output_budget():
    seen = {}

    def fn(system, user, **kw):
        seen.update(kw, user=user)
        return GOOD

    judge = make_llm_judge(call_fn=fn, config=_local_cfg(1024))
    judge(TRIPLE, "word " * 2000)
    assert seen["max_tokens"] >= triple_judge.JUDGE_MIN_OUTPUT_TOKENS
    assert len(json.loads(seen["user"])["evidence"]) < 10000


def test_local_injected_config_unknown_window_passes_none_and_no_effort():
    seen = {}

    def fn(system, user, **kw):
        seen.update(kw)
        return GOOD

    make_llm_judge(call_fn=fn, config=_local_cfg(None))(TRIPLE, "ev")
    assert seen["max_tokens"] is None and "effort" not in seen


def test_no_hard_coded_local_budget_constant():
    src = open(triple_judge.__file__, encoding="utf-8").read()
    assert "256" not in src


def test_stub_server_max_tokens_derived_from_context(fake_openai_server, monkeypatch):
    monkeypatch.setenv("EPISTRACT_LLM_BASE_URL", fake_openai_server.base_url)
    fake_openai_server.queue_content(GOOD)
    judge = make_llm_judge()
    assert judge.config.context_window == 4096
    ev = "Sema activates GLP1."
    assert judge(TRIPLE, ev)["verdict"] == "supported"
    reqs = [r for r in fake_openai_server.requests if r["path"].endswith("/chat/completions")]
    body = reqs[-1]["json"]
    user = json.dumps({"subject": "x", "relation": "R", "object": "y", "evidence": ev})
    est = triple_judge._estimate_tokens(triple_judge._JUDGE_SYSTEM + user)
    assert body["max_tokens"] == judge_max_tokens(judge.config, est)
    assert "effort" not in body


def test_stub_server_unknown_window_omits_max_tokens(fake_openai_server, monkeypatch):
    fake_openai_server.n_ctx = None
    fake_openai_server.props_n_ctx = None
    monkeypatch.setenv("EPISTRACT_LLM_BASE_URL", fake_openai_server.base_url)
    fake_openai_server.queue_content(GOOD)
    judge = make_llm_judge()
    assert judge.config.context_window is None
    judge(TRIPLE, "ev")
    reqs = [r for r in fake_openai_server.requests if r["path"].endswith("/chat/completions")]
    assert "max_tokens" not in reqs[-1]["json"]


# -- judge_graph: no-evidence, accounting ----------------------------------
def _graph(n=4, evidence=True):
    return {"links": [
        {"source": f"a:s{i}", "target": f"b:t{i}", "relation_type": "R",
         "relation_id": f"r{i}", "evidence": f"s{i} relates to t{i}." if evidence else ""}
        for i in range(n)
    ]}


def test_no_evidence_links_skip_judge_and_stay_unsupported():
    calls = []
    g = _graph(3)
    g["links"][1]["evidence"] = "   "
    g["links"][2].pop("evidence")

    def judge(t, e):
        calls.append(t["relation_id"])
        return {"verdict": "supported", "score": 0.9, "reason": "r"}

    summary = judge_graph(g, judge_fn=judge)
    assert calls == ["r0"]
    assert summary["skipped_no_evidence"] == 2
    for lk in g["links"][1:]:
        assert (lk["judge_verdict"], lk["judge_score"], lk["gated"]) == ("unsupported", 0.0, True)
        assert lk["judge_reason"] == "no evidence text"
    assert summary["verdict_counts"]["unsupported"] == 2


def test_plain_callable_still_works_and_summary_has_additive_keys():
    summary = judge_graph(_graph(2), judge_fn=lambda t, e: {"verdict": "partial", "score": 0.5, "reason": ""})
    assert summary["verdict_counts"]["partial"] == 2
    assert (summary["llm_judged"], summary["fallback"], summary["resumed"], summary["errors"]) == (0, 0, 0, [])


def test_summary_reports_judge_stats():
    judge = make_llm_judge(call_fn=_seq([GOOD, "not json", GOOD]))
    summary = judge_graph(_graph(3), judge_fn=judge)
    assert summary["llm_judged"] == 2 and summary["fallback"] == 1 and len(summary["errors"]) == 1


# -- keys / hash ------------------------------------------------------------
def test_link_key():
    assert link_key({"relation_id": "R9", "source": "a"}) == "R9"
    assert link_key({"source": "a", "relation_type": "R", "target": "b"}) == "a|R|b"


def test_graph_hash_properties(monkeypatch):
    links = _graph(3)["links"]
    h = graph_hash(links, "m")
    assert graph_hash(list(reversed(links)), "m") == h
    assert graph_hash(links, "other") != h
    changed = [dict(lk) for lk in links]
    changed[0]["evidence"] = "different"
    assert graph_hash(changed, "m") != h
    monkeypatch.setattr(triple_judge, "JUDGE_PROMPT_VERSION", JUDGE_PROMPT_VERSION + "x")
    assert graph_hash(links, "m") != h


# -- checkpoint -------------------------------------------------------------
def _counting_judge(fail_on=None):
    """Judge with stats; replies GOOD, 'not json' at call index fail_on."""
    calls = {"n": 0}

    def fn(system, user, **kw):
        calls["n"] += 1
        return "not json" if calls["n"] == fail_on else GOOD

    return make_llm_judge(call_fn=fn), calls


def test_checkpoint_written_without_fallbacks(tmp_path):
    p = tmp_path / "ck.jsonl"
    judge, _ = _counting_judge(fail_on=2)
    judge_graph(_graph(3), judge_fn=judge, checkpoint_path=p)
    lines = [json.loads(x) for x in p.read_text().splitlines()]
    assert lines[0]["type"] == "header" and lines[0]["prompt_version"] == JUDGE_PROMPT_VERSION
    assert [x["id"] for x in lines[1:]] == ["r0", "r2"]
    assert set(lines[1]["v"]) == {"verdict", "score", "reason"}


def test_resume_reuses_verdicts_and_makes_no_calls(tmp_path):
    p = tmp_path / "ck.jsonl"
    judge, calls = _counting_judge()
    judge_graph(_graph(3), judge_fn=judge, checkpoint_path=p)
    judge2, calls2 = _counting_judge()
    g = _graph(3)
    summary = judge_graph(g, judge_fn=judge2, checkpoint_path=p)
    assert calls2["n"] == 0 and summary["resumed"] == 3
    assert all(lk["judge_verdict"] == "supported" for lk in g["links"])


def test_fresh_run_truncates_checkpoint(tmp_path):
    p = tmp_path / "ck.jsonl"
    judge, _ = _counting_judge()
    judge_graph(_graph(2), judge_fn=judge, checkpoint_path=p)
    judge2, calls2 = _counting_judge()
    summary = judge_graph(_graph(2), judge_fn=judge2, checkpoint_path=p, resume=False)
    assert calls2["n"] == 2 and summary["resumed"] == 0
    assert len(p.read_text().splitlines()) == 3


def test_different_graph_hash_is_ignored(tmp_path):
    p = tmp_path / "ck.jsonl"
    judge, _ = _counting_judge()
    judge_graph(_graph(2), judge_fn=judge, checkpoint_path=p)
    g = _graph(2)
    g["links"][0]["evidence"] = "new evidence about s0 and t0"
    judge2, calls2 = _counting_judge()
    summary = judge_graph(g, judge_fn=judge2, checkpoint_path=p)
    assert summary["resumed"] == 0 and calls2["n"] == 2


def test_malformed_and_invalid_checkpoint_lines_are_skipped(tmp_path):
    p = tmp_path / "ck.jsonl"
    judge, _ = _counting_judge()
    judge_graph(_graph(3), judge_fn=judge, checkpoint_path=p)
    with p.open("a") as fh:
        fh.write("{broken\n")
        fh.write(json.dumps({"id": "r1", "v": {"verdict": "bogus", "score": 0.5}}) + "\n")
    lines = p.read_text().splitlines()
    # drop the genuine r1 record so only the invalid one remains for r1
    keep = [ln for ln in lines if '"id": "r1"' not in ln or "bogus" in ln]
    p.write_text("\n".join(keep) + "\n")
    judge2, calls2 = _counting_judge()
    summary = judge_graph(_graph(3), judge_fn=judge2, checkpoint_path=p)
    assert summary["resumed"] == 2 and calls2["n"] == 1


def test_abort_keeps_checkpointed_verdicts_and_propagates(tmp_path):
    p = tmp_path / "ck.jsonl"
    judge = make_llm_judge(call_fn=_seq([GOOD, GOOD, LLMQuotaError("daily quota")]))
    g = _graph(5)
    with pytest.raises(JudgeAbort):
        judge_graph(g, judge_fn=judge, checkpoint_path=p)
    assert len(p.read_text().splitlines()) == 3  # header + 2 verdicts
    assert g["links"][0]["judge_verdict"] == "supported"
    assert "judge_verdict" not in g["links"][2]


# -- progress ---------------------------------------------------------------
def test_progress_goes_to_stream_only(capsys):
    buf = io.StringIO()
    judge, _ = _counting_judge()
    judge_graph(_graph(4), judge_fn=judge, progress=True, progress_every=2, stream=buf)
    out = buf.getvalue()
    assert out.count("judge:") == 2
    assert "4/4" in out and "/min" in out and "ETA" in out
    assert capsys.readouterr().out == ""


def test_progress_defaults_to_stderr(capsys):
    judge, _ = _counting_judge()
    judge_graph(_graph(2), judge_fn=judge, progress=True, progress_every=1)
    cap = capsys.readouterr()
    assert "judge:" in cap.err and cap.out == ""


def test_progress_off_by_default(capsys):
    judge, _ = _counting_judge()
    judge_graph(_graph(3), judge_fn=judge)
    cap = capsys.readouterr()
    assert cap.err == "" and cap.out == ""
