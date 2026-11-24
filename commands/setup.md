---
name: epistract-setup
description: Install and verify epistract dependencies (sift-kg, optional RDKit/Biopython)
---

Run the epistract setup script to check and install dependencies:

```bash
bash ${CLAUDE_PLUGIN_ROOT}/scripts/setup.sh
```

If any dependency is missing, install it:
- sift-kg: `uv pip install sift-kg`
- RDKit (SMILES validation): `uv pip install rdkit`
- Biopython (sequence validation): `uv pip install biopython`

Report the status of each dependency to the user after running.

## Optional: local LLM

The LLM-backed passes (`/epistract:enhance --llm`, the epistemic narrator, the
workbench chat) can use a local OpenAI-compatible server (llama.cpp `llama-server`,
Ollama, vLLM, LM Studio) instead of a cloud key. No API key is needed. Export the
variables in your shell **before starting Claude Code**:

```bash
export EPISTRACT_LLM_BASE_URL=http://localhost:8080   # host:port, with or without /v1
export EPISTRACT_LLM_MODEL=<model-id>                  # optional: first chat model is used
export EPISTRACT_LLM_API_KEY=<your-key>                # optional: only if the server needs one
```

Then verify it:

```bash
PYTHONPATH="${CLAUDE_PLUGIN_ROOT}" python3 -m core.cli llm check
```

The command prints the provider, base URL, model, context window and served models,
then makes a one-token chat call. It exits 0 on `chat: ok` and 1 otherwise. Add
`--json` for machine-readable output. Read a failure by its kind:

- `not_chat` - the model does not serve chat completions (an embedding or rerank
  model). Set `EPISTRACT_LLM_MODEL` to a chat model.
- `unreachable` - nothing answers at the base URL. Is the server running?
- `quota` - the provider's quota or daily limit is exhausted; the message names the
  reset time when the provider gave one.

`EPISTRACT_LLM_BASE_URL` takes priority over cloud keys. Force another provider with
`EPISTRACT_LLM_PROVIDER=anthropic|openrouter|foundry`. See `docs/known-limitations.md`
for what small local models can and cannot do.

## Usage Guard

```
Usage: /epistract:setup

Installs and verifies epistract dependencies:
  - sift-kg (required)          — knowledge graph engine
  - RDKit (optional)            — SMILES validation for drug-discovery domain
  - Biopython (optional)        — sequence validation for drug-discovery domain

Run with no arguments. No flags needed.
```

Run the epistract setup script to check and install dependencies:

```bash
bash ${CLAUDE_PLUGIN_ROOT}/scripts/setup.sh
```

If any dependency is missing, install it:
- sift-kg: `uv pip install sift-kg`
- RDKit (SMILES validation): `uv pip install rdkit`
- Biopython (sequence validation): `uv pip install biopython`

Report the status of each dependency to the user after running.

