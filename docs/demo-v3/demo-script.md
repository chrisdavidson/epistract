# Epistract v3.1 — Knowledge Graph Conference 2026 Demo Script

**Conference:** Knowledge Graph Conference 2026 — Tools & Demonstrations Track
**Track date:** 2026-05-08, 10 AM – Noon ET (virtual)
**Video slot:** 10–15 minutes + 10–15 min live QnA
**Host:** Umesh Bhatt (umesh@8thcross.com)
**Epistract version:** v3.1.0 (shipped 2026-04-23)
**Prior video:** [v2.0 demo, 2026-03-27, YouTube](https://youtu.be/7mHbdb0nn3Y) — superseded by this one

---

## What changed since the v2.0 video

| Aspect | v2.0 video (Mar 2026) | v3.1 video (this one) |
|---|---|---|
| Domains | drug-discovery only | drug-discovery + contracts + clinicaltrials |
| Epistemic layer | Rule-based classification only | Rules + automatic LLM analyst narrator |
| Workbench persona | Generic "knowledge graph analyst" | Domain-specific senior-analyst persona, dual-use for chat + narrator |
| Clinicaltrials domain | absent | new; includes optional CT.gov v2 + PubChem helper module (domain-specific, not a framework feature) |
| Showcases | S1 PICALM + S6 GLP-1 literature | S6 GLP-1 literature + S7 GLP-1 Phase 3 trials (paired) |
| Scenarios | 6 | 7 |
| Narrator output | none | auto-generated `epistemic_narrative.md` per run |
| Fidelity story | "we extract entities" | "we tell you what the graph doesn't know" |

---

## Story arc — tuned for KG specialists

**Audience:** Knowledge Graph Conference attendees. Know what communities are. Know Louvain. Know the difference between an RDF triple and a labeled property graph. Care about ontology grounding, provenance, and epistemic treatment of KG contents. Have heard of Super Domains.

**Three beats, in this order:**

1. **Graph first** (Acts 1–2). What's different about an epistract knowledge graph vs. a flat KG. Two-layer architecture: brute facts grounded to a domain ontology, plus a Super Domain layer classifying every relation by epistemic status. Demonstrate on a real graph — entity-type distribution, Louvain communities, claims-layer breakdown.

2. **Life-sciences illustration** (Acts 3–5). One worked corpus (S6 — GLP-1 drug discovery) kept approachable for a general audience. Show what the Super Domain layer surfaces that a flat graph can't: prophetic patent claims, contested indications with temporal stratification, coverage gaps. Read the auto-generated analyst briefing verbatim. Show that different kinds of knowledge need different analysts (S6 literature ↔ S7 trial protocols).

3. **For the tech geeks** (Act 6). How it's built. Persona single-source-of-truth pattern driving both reactive chat and proactive narrator. A domain package is four files. Core is domain-agnostic. Wizard to build your own from sample documents.

---

## Target duration: ~12 minutes

Fits comfortably in the 10–15 min window. Narration ~1,600 words at 140 wpm.

| # | Act | Duration | Main surface | Audience lens |
|---|---|---:|---|---|
| 1 | The KG problem we're addressing | 75s | Title card / slide | KG specialists |
| 2 | A two-layer knowledge graph in action | 150s | Browser :8000 + terminal | KG specialists |
| 3 | S6 life-sciences illustration — what the Super Domain surfaces | 120s | Browser :8000 | General audience |
| 4 | The automatic analyst briefing | 90s | Terminal | General audience |
| 5 | Different analysts for different kinds of knowledge | 120s | Split browser :8000 + :8001 | General audience |
| 6 | For the tech geeks — how it's built | 120s | Terminal + `tree` | Tech implementers |
| 7 | Closing | 45s | GitHub releases page | Everyone |

---

## Act 1 — The KG problem we're addressing (75s)

**Surface:** Title card, then a slide or screenshot showing a flat KG (entity+edge) with an overlay icon indicating "what kind of knowledge is this edge?"

**Title card:**
```
EPISTRACT v3.1.0
Knowledge graphs that know what they don't know.
github.com/usathyan/epistract
```

**Narration:**

> "A knowledge graph has two kinds of content that most toolchains flatten together.
>
> First, there are the **brute facts** — nodes and typed edges grounded to a domain ontology, each edge with a confidence score and a source-document citation. This is what virtually every KG tool produces.
>
> Second, there's the **epistemic content** — *how* each fact was stated. Was it asserted with quantitative evidence? Was it prophetic patent language — 'is expected to,' 'may be prepared by'? Was it hedged research wording — 'suggests,' 'appears to'? Does the same edge appear across sources with conflicting confidence, making it contested? Or do two sources outright contradict each other?
>
> Epistract treats that epistemic content as a first-class Super Domain layer on top of the brute facts KG. Every edge gets tagged. An analyst persona — different for each domain — reads the classified graph and writes a briefing. That's the framework."

---

## Act 2 — A two-layer knowledge graph in action (150s)

**Surface:** Browser at `http://127.0.0.1:8000`, pre-launched with the S6 graph already loaded. Then cut to terminal.

> "Here's what that looks like. This is a knowledge graph built from thirty-four documents on a single drug class — we'll come back to the drug-discovery specifics in a minute. For now, focus on the graph structure."

**In browser, click the Graph panel.** *Show 278 nodes, 855 edges, community-colored layout.*

> "Two hundred seventy-eight entities across thirteen types. Eight hundred fifty-five typed relations. Ten Louvain communities. So far, this is a standard labeled property graph — you could reproduce the structure in Neo4j or NetworkX."

*Click a community cluster to highlight it.*

> "The community structure tells you *where* in the graph to look — which nodes are densely interconnected. Useful for navigation. It tells you nothing about *what kind of knowledge* you're looking at — a patent prophetic claim and a Phase 3 trial result sit in the same community, topologically indistinguishable."

**Cut to terminal.**

```bash
cat tests/corpora/06_glp1_landscape/output-v3/claims_layer.json | jq '.summary.epistemic_status_counts'
```

**Shows:**
```json
{
  "asserted": 758,
  "prophetic": 61,
  "hypothesized": 31,
  "contested": 33,
  "contradictions": 2,
  "speculative": 2,
  "negative": 1
}
```

> "This is the Super Domain layer. The same eight hundred fifty-five relations, but now each one is tagged with an epistemic status. Seven categories. Sixty-one relations are prophetic — patent language claiming effects that haven't been demonstrated. Thirty-three are contested — same entity pair, same relation type, but different sources give different confidence. Two are outright contradictions. The rest are cleanly asserted."

> "This is what the Super Domain adds to the graph. You can now query by epistemic status. You can render contested edges in amber. You can write a policy that says 'never treat a prophetic relation the same as an asserted one.' The graph becomes a reasoning substrate, not just a lookup table."

---

## Act 3 — S6 life-sciences illustration (120s)

**Surface:** Stay in browser :8000. Click Chat panel.

> "Now let me make this concrete with the corpus we just saw. It's a drug-discovery corpus — thirty-four documents on a class of medications called GLP-1 receptor agonists. You've probably heard of semaglutide, sold as Ozempic and Wegovy, and tirzepatide, sold as Mounjaro and Zepbound. They're used for type-2 diabetes and obesity. The corpus is ten patent filings from Novo Nordisk, Pfizer, and Eli Lilly, plus twenty-four PubMed abstracts about mechanism, safety, and emerging indications."

> "The chat panel is grounded in the graph data and runs on a senior drug-discovery analyst persona. The persona commits to citing every claim by source document and to using the epistemic-status vocabulary we just saw. Let me ask it the question the research analyst would ask."

**Type into chat:** `Which patents make prophetic claims about new indications, and where are the biggest gaps between prophetic breadth and asserted evidence?`

*Stream the response. Let the table render.*

> "This is cross-document synthesis. The chat is grouping prophetic claims by patent family, flagging the ones most likely to be boilerplate, and naming the asserted clinical evidence that would close each gap. Every specific claim cites the source by document ID. This is not retrieval. You couldn't do this with chunk-level RAG because the synthesis is happening at the graph level — the contested edges, the temporal stratification of confidence scores, the cross-patent clustering all live in the claims layer, not in the source text."

---

## Act 4 — The automatic analyst briefing (90s)

**Surface:** Terminal.

```bash
bat tests/corpora/06_glp1_landscape/output-v3/epistemic_narrative.md | head -80
```

> "The chat just answered reactively — I asked, it responded. The same machinery runs proactively. After the epistemic classification writes the claims layer, the pipeline calls the same analyst persona with the full classified graph and asks for a structured briefing. File committed alongside the graph. Regenerated on every run."

**Walk the narrative on screen, reading each excerpt verbatim (the narrator actually wrote these):**

*Executive summary:*

> "Sixty-one prophetic claims inflate the apparent indication breadth of these compounds. Cardiovascular risk reduction, neurodegeneration, and metabolic sub-disorders are largely patent-forward-looking, not empirically established."

*Contested claim with temporal stratification:*

> "semaglutide INDICATED_FOR obesity — confidence range 0.55 to 0.97 across sources. The 0.55 instance likely reflects pre-STEP-trial patent language; the 0.97 instance reflects post-approval asserted status. These should be temporally stratified, not treated as equivalent evidence."

*Recommended follow-up:*

> "Integrate SURPASS-2 trial data — add a clinical_trial:surpass_2 node with direct tirzepatide-vs-semaglutide efficacy relations to close the head-to-head gap. Source: NEJM 2021, Frías et al."

> "This is an analyst reading the graph and telling you what it's missing. The persona that produced this briefing is the same string that powered the chat you just saw — one YAML field used as the system prompt in two places. Upgrade the persona, both surfaces improve together. That's the domain's expert voice, stored exactly once."

---

## Act 5 — Different analysts for different kinds of knowledge (120s)

**Surface:** Split browser, two workbenches side by side.

```bash
# Pre-launched before recording:
python scripts/launch_workbench.py tests/corpora/06_glp1_landscape/output-v3 --domain drug-discovery --port 8000
python scripts/launch_workbench.py tests/corpora/07_glp1_phase3_trials/output --domain clinicaltrials --port 8001
```

> "Up to this point we've looked at one graph. But the framework claim is that the same pipeline works for any domain — the only thing that changes is the domain config. Let me show that as a graph-level claim."

> "On the right is a completely different knowledge graph. Same molecular space — GLP-1 agonists — but the source is ten ClinicalTrials.gov trial protocols. SURPASS-2, SURMOUNT-1, STEP-1 through three, the PIONEER cardiovascular trials, SUSTAIN-6, ACHIEVE-1. And the domain here is `clinicaltrials`, not `drug-discovery`. Twelve entity types including Trial, Intervention, Cohort, TrialPhase, Outcome. Ten relation types. Phase-based evidence grading baked into the epistemic layer."

*Switch attention to the right-side graph.*

> "One hundred forty-two entities, three hundred ninety-five relations, eight communities. Different graph from a different domain, built by the same core pipeline."

> "Now the test. Same question, both chats."

**Type into BOTH chats simultaneously:** `What's the evidence for tirzepatide in obesity?`

*Both stream in parallel.*

> "Left side — the drug-discovery analyst persona reading the literature graph. Cites patents and PubMed abstracts. Talks about prophetic claims, hedged research wording, what the trials should show. Right side — the clinical trials analyst persona reading the protocol graph. Cites NCT identifiers. Names enrollment counts, primary endpoints, phase-tier evidence grades."

> "Neither graph alone is a competitive-intelligence brief. Together they are. And this is the graph-level claim: the same epistemic machinery, same persona-dual-use pattern, different ontology commitments, produces two knowledge graphs that are complementary by construction."

---

## Act 6 — For the tech geeks — how it's built (120s)

**Surface:** Terminal.

> "For the implementers in the room. A quick look under the hood."

```bash
tree domains/clinicaltrials/ -L 2
```

*Shows:*
```
domains/clinicaltrials/
├── domain.yaml              # 12 entity types, 10 relation types
├── SKILL.md                 # 529-line extraction prompt
├── epistemic.py             # phase-based evidence grading
├── enrich.py                # optional: CT.gov + PubChem helper (clinicaltrials-specific)
└── workbench/
    └── template.yaml        # persona + entity colors + starter questions
```

> "A whole domain is four required files. Schema in YAML. Extraction prompt in Markdown. Epistemic rules in Python. Workbench config — including the analyst persona — in YAML. No core-code changes. The clinicaltrials package also ships an optional helper module to pull live metadata from its natural authoritative source, ClinicalTrials.gov. That's a package-level convenience, not a framework feature — any domain with a canonical external data source can include its own helper the same way."

```bash
cat domains/clinicaltrials/workbench/template.yaml | grep -A 3 "^persona"
```

> "This is the single string that drives both the reactive workbench chat and the proactive narrator. One source of truth per domain. Change it once, both surfaces pick up the change."

```bash
ls core/
```

*Shows `domain_resolver.py`, `ingest_documents.py`, `build_extraction.py`, `chunk_document.py`, `label_epistemic.py`, `label_communities.py`, `llm_client.py`, etc.*

> "The core pipeline is domain-agnostic — no clinicaltrials or drug-discovery code anywhere in it. It resolves a domain package at runtime, applies the schema, runs the epistemic classifier, calls the narrator. LLM credential priority is Azure AI Foundry first, then Anthropic direct, then OpenRouter — your choice. Claude Sonnet at the time of this recording."

```
/epistract:domain --input ./my-sample-docs/ --name my-domain
```

> "And if you don't want to hand-write any of it, the domain wizard runs multi-pass LLM analysis on three to five sample documents, proposes a schema, and emits all four required files. You have a working custom domain in about fifteen minutes."

> "Open source, MIT license, runs as a Claude Code plugin."

---

## Act 7 — Closing (45s)

**Surface:** GitHub releases page.

```
https://github.com/usathyan/epistract/releases
```

> "Epistract version three-point-one shipped last week. Three pre-built domains — drug discovery, contracts, clinical trials — each demonstrating the two-layer architecture. Each with an analyst persona in the domain package. Each producing an auto-generated epistemic narrative on every run.
>
> The framework's one-line summary: communities tell you where in the graph to look. Super Domains tell you what kind of knowledge you're looking at. Analyst personas tell you what to do with it.
>
> Happy to take questions now. Thank you."

**Cut to title card:**
```
EPISTRACT v3.1.0
github.com/usathyan/epistract
umesh@8thcross.com
```

---

## Production checklist

- [ ] **Recording environment**: Ghostty terminal (1920×1080, dark theme, 16pt font). Browser: Safari or Chrome, bookmark bar hidden, DnD on.
- [ ] **Pre-built output**: `tests/corpora/06_glp1_landscape/output-v3/` and `tests/corpora/07_glp1_phase3_trials/output/` both present on disk and committed.
- [ ] **Enrichment artifacts**: verify `_enrichment_report.json` exists under `output/extractions/` (clinicaltrials corpus only; referenced only if asked in QnA).
- [ ] **Workbench pre-launch**: launch both (`--port 8000` S6, `--port 8001` S7) in separate terminals before record to let physics settle.
- [ ] **Workbench credentials**: verify `ANTHROPIC_API_KEY` or `OPENROUTER_API_KEY` is set (otherwise chat will 402). Top up credits if running low.
- [ ] **Terminal state**: `cd ~/code/epistract && clear` between cuts.
- [ ] **Capture method**: QuickTime File → New Screen Recording (or OBS with mic track disabled; add voiceover in post). Separate record per act — cleaner editing.
- [ ] **Voiceover**: Either record live or do in post with ElevenLabs (Roger voice, eleven_multilingual_v2 model per the v2.0 pipeline). Phonetic spellings for TTS: sem-ah-glue-tide, teer-zeh-pa-tide, or-for-GLI-pron, GLP-one, epi-stem-ick.
- [ ] **Narration length check**: script is ~1,600 words; at 140 wpm that's ~11–12 minutes. Leaves buffer inside the 10–15 min Tools Track slot.
- [ ] **Post-production**: ffmpeg merge, EBU R128 loudness normalization (same pipeline as v2.0 video), crossfade between acts.

## Act runbook for Day-of QnA prep

Likely audience questions + answers (tuned for KG-specialist audience):

- **"How is the epistemic layer different from a confidence score?"** — A confidence score tells you how strongly a single extraction is supported. Epistemic status tells you *what kind* of support exists — asserted evidence vs. patent forward-looking language vs. hedged research suggestion vs. disputed across sources. It's categorical, not scalar. Same 0.95 confidence can be asserted or prophetic depending on the source language.
- **"How do you decide the epistemic status of an edge?"** — Two-stage. Rule-based first: a dozen regex patterns over evidence text plus document-type inference (patent vs. paper vs. preprint vs. structural-biology). Then per-domain `CUSTOM_RULES` that can refine or override, and a cross-source aggregation step for contested / contradiction detection. The LLM narrator is downstream; it reads the rule output, doesn't generate it.
- **"What's the persona file actually doing?"** — It's one string used as the system prompt in two places: the workbench chat request, and the `/epistract:epistemic` narrator LLM call. Both see the same "You are a senior drug-discovery analyst…" preamble. Upgrade once, both improve.
- **"Does this relate to Eric Little's Super Domain work?"** — Yes, directly. The epistemic classification + hypothesis grouping + contradiction detection maps onto the Super Domain concept — graph-level knowledge about the brute-facts graph. The framework wasn't named after that work but the design converged on the same vocabulary.
- **"Can I bring my own LLM?"** — Credential resolver priority is Azure AI Foundry → Anthropic direct → OpenRouter. All three speak the Anthropic-native message format (or the OpenAI-compat format on OpenRouter). Bring-your-own-model is a config change, not a code change.
- **"How do you handle the cold-start problem for a brand new domain?"** — `/epistract:domain --input ./samples/` runs a three-pass LLM analysis on three to five sample documents. Produces a full domain package. Wizard limits schemas to 15 entity types and 20 relation types by default to keep extraction tight.
- **"What about hallucinations in the narrator?"** — The narrator's input is the classified graph (JSON) plus the persona. It doesn't see the source documents directly. Its claims must reference graph nodes and relations. When it does speculate (we've seen cases where it infers patent-like language from a non-patent corpus), the mitigation is source-type hinting in the prompt — candidate v3.2 fix.
- **"Is this just RAG?"** — No. RAG retrieves chunks at query time. Epistract extracts a structured graph once, then the workbench chat answers questions grounded in that graph. The epistemic layer and narrator are graph-level, not chunk-level. This gives you cross-document synthesis, contradiction detection, and named hypotheses — which retrieval alone can't surface.
- **"Why a labeled property graph instead of RDF?"** — Pragmatic: sift-kg uses NetworkX as the underlying structure, and the claims layer is a JSON overlay with edge-level attributes. An RDF export (GraphML / Turtle) is a command-line flag away via `/epistract:export`. The epistemic model is format-agnostic.

---

*Script prepared 2026-04-23 for the KGC 2026 Tools & Demonstrations track, 2026-05-08. Superseded prior v2.0 script at `archive/docs/demo/demo-script.md`.*
