---
name: epistract-enhance
description: Run arXiv-backed quality passes over a project's knowledge graph — triple judging, entity resolution, and a bi-temporal epistemic layer
---

Improve the quality of a project's built knowledge graph with three research-backed
passes. Operates on `<project>/graph_data.json` in place and writes an
`enhancement_report.json`. Runs offline with lexical fallbacks; pass `--llm` to use the
configured LLM provider (a cloud provider or a local OpenAI-compatible server) for
calibrated judgments.

Requires a built graph — run `/epistract:build` first.

Passes (if none is named, all three run):
- `--judge` — **LLM-as-judge triple gate** (GraphJudge arXiv 2411.17388 / GraphEval
  arXiv 2407.10793): scores each relation against its evidence span, flags triples whose
  evidence does not support them.
- `--resolve` — **two-stage entity resolution** (ComEM arXiv 2405.16884): blocks by type,
  clusters by character/token/embedding similarity, merges duplicates (e.g. "GLP-1
  Receptor" and "GLP1 receptor").
- `--epistemic` — **bi-temporal contradiction layer** (Graphiti/Zep arXiv 2501.13956) with
  **graded hedge scoring** (arXiv 2405.13319): when a newer relation contradicts an older
  one, the older edge is marked `superseded` (not deleted) with provenance; every edge
  gets a graded `hedge_score` and epistemic status (asserted / hypothesized / speculative).

## Usage Guard

**If invoked with no arguments or with `--help`:** Display the following usage block verbatim and stop.

```
Usage: /epistract:enhance [--project <name>] [--judge] [--resolve] [--epistemic] [--llm] [--fresh]

Options:
  --project <name>   Target project (default: detected from cwd or $EPISTRACT_PROJECT)
  --judge            Only run the triple-judge gate
  --resolve          Only run entity resolution
  --epistemic        Only run the bi-temporal epistemic layer
  --llm              Use the configured LLM provider instead of the lexical fallback
                     (aborts instead of silently falling back; see below)
  --fresh            Ignore the judge checkpoint and re-judge every relation
  (no pass flag)     Run all three passes

Examples:
  /epistract:enhance --project glp1-research
  /epistract:enhance --project glp1-research --judge --llm
  EPISTRACT_LLM_BASE_URL=http://localhost:8080 /epistract:enhance --project glp1-research --judge --llm
  /epistract:enhance --project acme-contracts --epistemic
```

```bash
PYTHONPATH="${CLAUDE_PLUGIN_ROOT}" python3 -m core.cli enhance [--project NAME] [--judge] [--resolve] [--epistemic] [--llm] [--fresh]
```

## Judging with an LLM (`--llm`)

`--llm` uses the provider that `python -m core.cli llm check` reports. Set the variables
in your shell **before starting Claude Code**; a running session does not see later
exports.

```bash
export EPISTRACT_LLM_BASE_URL=http://localhost:8080   # host:port, with or without /v1
export EPISTRACT_LLM_MODEL=qwen2.5-7b-instruct         # optional: first chat model of /v1/models
export EPISTRACT_LLM_API_KEY=<your-key>                # optional: sent only when set
export EPISTRACT_LLM_PROVIDER=local                    # optional: local|anthropic|openrouter|foundry
export EPISTRACT_LLM_MAX_TOKENS=1024                   # optional: cap on the reply length
export EPISTRACT_LLM_CONTEXT_WINDOW=4096               # optional: override the probed window
```

- `EPISTRACT_LLM_BASE_URL` wins over `AZURE_FOUNDRY_API_KEY`, `ANTHROPIC_API_KEY` and
  `OPENROUTER_API_KEY`. Cloud keys are never sent to the local URL. To use a cloud
  provider while the base URL is set, force it with `EPISTRACT_LLM_PROVIDER`.
- `EPISTRACT_LLM_PROVIDER` is an explicit choice: it fails with an error when that
  provider's credentials are missing instead of falling through to another one.
- The reply length is derived from the server's context window (read from the server,
  or `EPISTRACT_LLM_CONTEXT_WINDOW`): `min(2048 or EPISTRACT_LLM_MAX_TOKENS, window -
  prompt estimate - 64)`. When a local server does not report its window, no
  `max_tokens` is sent and the server applies its own limit.
- Before judging, a one-token chat call checks the provider. With no provider
  configured, an unreachable server or a model that does not serve chat, the command
  exits 1 before anything is judged.
- Relations with no evidence text are not sent to the LLM. They keep the verdict
  `unsupported` (score 0.0, gated) and are counted as `skipped_no_evidence`.

### Fallbacks and abort rules

When one call fails (an unparseable reply, a read timeout on a local server), that
relation gets the lexical verdict and is counted in `fallback`. Read timeouts on a
local server are not retried. The run **aborts** instead of silently producing a mostly
lexical result when:

- the first 5 calls all fail, or 5 calls in a row fail;
- any call hits a quota, fatal or connection error;
- once at least 20 calls have been made, more than 20% of them fell back (checked during
  the run and again at the end);
- at the end of a run with fewer than 20 calls, more than 50% fell back.

Rate limits are retried up to 3 attempts. A `Retry-After` of 60 s or less is waited
out (announced on stderr when it is 5 s or more). A longer one, or a daily-limit
message, is a quota error that names the reset time.

On abort nothing is written: `graph_data.json` and `enhancement_report.json` stay as
they were. The exit code is **1** for a configuration error or an abort and **130**
for Ctrl-C.

### Progress, checkpoint and resume

Progress prints to stderr. Each relation that got a real LLM verdict is appended to
`<project>/.judge_checkpoint.jsonl` (relations that fell back to the lexical verdict are
not saved, so they are judged again on resume). After an abort or Ctrl-C, run the same command
again and the judge resumes from the checkpoint automatically (`resumed` in the report
counts the relations restored from it). `--fresh` ignores the checkpoint and re-judges
everything. The checkpoint is deleted after a successful run, and the graph and report
are written atomically.

### Report fields

The `judge` block of `enhancement_report.json` carries `mode` (`llm` or `lexical`;
for lexical runs `provider`, `model` and `base_url` are `null`), `provider`, `model`, `base_url`, `llm_judged`, `fallback`, `resumed`,
`skipped_no_evidence`, `aborted` (always `false` in a written report) and `errors`
(up to 5 sample messages).

Report the merge count, triple-verdict breakdown, and epistemic status counts (including
any superseded/contradicted edges). This complements `/epistract:epistemic`, which builds
the domain-specific Super Domain claims narrative.
