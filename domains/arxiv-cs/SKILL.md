# arxiv-cs Domain

You are analyzing arXiv Computer Science preprints — non-peer-reviewed research papers submitted directly by authors to arXiv. Each document contains metadata (arXiv ID, title, authors, subject categories) and an abstract describing the paper's contributions. Extract structured entities and relationships that reveal algorithmic contributions, empirical evaluations, benchmark comparisons, and cross-paper connections in the CS research landscape. Focus on the abstract text and metadata fields; do not attempt to read or cite figures, tables, or proofs not summarized in the abstract.

## Entity Types

| Type | Description |
|------|-------------|
| PAPER | An arXiv preprint identified by arXiv ID (e.g., "1706.03762"). Primary document node. |
| AUTHOR | A named researcher contributing to the paper. Use full name as canonical form. |
| INSTITUTION | A university, lab, or company authoring the work (e.g., "Google Brain", "Stanford University"). |
| ALGORITHM | A named ML/AI algorithm, model architecture, or method (e.g., "Transformer", "ResNet-50", "BERT"). |
| DATASET | A named training or evaluation dataset (e.g., "ImageNet", "SQuAD 1.1", "WMT14 EN-DE"). |
| BENCHMARK | A named evaluation benchmark or challenge with a standardized comparison (e.g., "GLUE", "SuperGLUE", "MMLU"). |
| METRIC | A named evaluation metric (e.g., "BLEU score", "top-1 accuracy", "F1", "perplexity"). |
| TASK | A defined NLP/CV/ML task (e.g., "machine translation", "object detection", "text classification"). |
| FRAMEWORK | A software framework or library used in implementation (e.g., "PyTorch", "JAX", "TensorFlow"). |
| VENUE | A conference, journal, or workshop (e.g., "NeurIPS 2017", "ICLR 2021"). |
| RESULT | A specific quantitative performance claim (e.g., "28.4 BLEU on WMT14 EN-DE"). Extract for primary benchmark results only. |
| ARXIV_CATEGORY | An arXiv subject category (e.g., "cs.CL", "cs.CV"). Anchor for community detection. |

## Relation Types

| Type | Description |
|------|-------------|
| AUTHORED_BY | Paper was authored by an Author |
| AFFILIATED_WITH | Author is affiliated with an Institution |
| PROPOSES | Paper proposes or introduces an Algorithm or Method |
| EVALUATES_ON | Paper evaluates an Algorithm on a Benchmark or Dataset |
| OUTPERFORMS | An Algorithm outperforms another Algorithm on a Benchmark |
| TRAINED_ON | An Algorithm was trained on a Dataset |
| IMPLEMENTED_IN | An Algorithm or Paper uses a Framework |
| PUBLISHED_AT | Paper was published or submitted to a Venue |
| CITES | Paper cites another Paper (abstract-only; extract only when explicitly named in text) |
| ACHIEVES | Paper or Algorithm achieves a Result on a Benchmark or Task |

## Extraction Guidelines

1. Extract PAPER using the arXiv ID as the canonical entity name (e.g., "1706.03762"). Record the paper title as a context attribute. Use the arXiv ID from the `=== ARXIV ID ===` field, not the abstract text.
2. Extract AUTHOR from the `=== AUTHORS ===` field. Create one entity per named author. Use the full name as given (e.g., "Ashish Vaswani", not "Vaswani"). Do not create AUTHOR entities for authors mentioned only in the abstract body without a full name.
3. Extract INSTITUTION when the abstract or author metadata explicitly names a lab, university, or company (e.g., "Google Brain", "MIT CSAIL", "Stanford University"). Treat INSTITUTION extraction as best-effort — the arXiv Atom API does not reliably provide affiliation fields, so extract from text patterns like "We at [Institution]" or "researchers from [Institution]".
4. Extract ALGORITHM for each distinctly named model, architecture, or method proposed or evaluated in the abstract. Include version numbers when stated (e.g., "GPT-3", not "the 175B model"). Use the author-given name, not informal descriptions.
5. Extract DATASET for each named training or evaluation dataset explicitly mentioned. Include version or split when stated (e.g., "SQuAD 1.1", "WMT14 EN-DE"). Do not extract dataset size or training cost as DATASET entities.
6. Extract BENCHMARK for named evaluation setups with standardized leaderboard comparisons (e.g., "GLUE", "SuperGLUE", "ImageNet", "MMLU"). A benchmark differs from a dataset in that it defines a comparative evaluation protocol, not just data.
7. Extract METRIC for each named evaluation metric used to report results (e.g., "BLEU", "F1", "top-1 accuracy", "perplexity"). Do not create METRIC entities for training metrics such as loss, learning rate, or wall-clock time.
8. Extract TASK for defined ML/NLP/CV tasks named in the abstract (e.g., "machine translation", "image classification", "question answering", "named entity recognition"). Use the standard task name, not a paraphrase.
9. Extract FRAMEWORK for software frameworks or libraries explicitly mentioned as implementation tools (e.g., "PyTorch", "JAX", "TensorFlow", "Hugging Face Transformers"). Do not extract programming languages (Python, C++) as FRAMEWORK entities.
10. Extract VENUE from the `=== JOURNAL / VENUE ===` field or from explicit venue mentions in the abstract (e.g., "published at NeurIPS 2017", "ICLR 2021"). Include the year when stated.
11. Extract RESULT only for primary reported performance claims on the main benchmark — omit training cost, dataset size, and architectural parameter counts (Pitfall: RESULT overextraction). Use the format "value metric on benchmark" (e.g., "28.4 BLEU on WMT14 EN-DE").
12. Extract ARXIV_CATEGORY from the `=== PRIMARY CATEGORY ===` and `=== CATEGORIES ===` fields. Use the arXiv category code (e.g., "cs.CL", "cs.CV", "cs.LG"). Create one entity per distinct category code listed.

Extract CITES only when the abstract explicitly names another paper, author name, or arXiv ID. Do not infer citations from context.

## Nomenclature Standards

1. **Papers**: Use the arXiv ID as the canonical PAPER entity name (e.g., "1706.03762").
   Record the paper title as an attribute.

2. **Algorithms**: Use the author-given model/algorithm name as canonical
   (e.g., "Transformer", "BERT", "ResNet-50", "GPT-3"). Include version numbers
   when meaningful. Do NOT normalize to acronyms unless that is the paper's terminology.

3. **Datasets**: Use canonical dataset names (e.g., "ImageNet", "SQuAD 1.1",
   "WMT14 EN-DE"). Include version or split when stated.

4. **Benchmarks**: Distinct from datasets — a benchmark is an evaluation setup
   with a leaderboard or standardized comparison (GLUE, SuperGLUE, MMLU).

5. **Metrics**: Use standard shorthand (BLEU, F1, top-1 accuracy, perplexity,
   ROUGE-L). Do not create METRIC entities for training metrics (loss, learning rate).

6. **Institutions**: Use the lab or group name when available
   (e.g., "Google Brain" not "Google"; "FAIR" for Meta AI Research).

7. **Venues**: Include year when stated (e.g., "NeurIPS 2017", "ICLR 2021").
