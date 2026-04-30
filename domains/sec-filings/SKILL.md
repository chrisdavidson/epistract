# sec-filings Domain

You are extracting a knowledge graph from SEC EDGAR filings (10-K, 10-Q, 8-K, S-1, DEF 14A, and SEC comment-letter exchanges) for forensic-accounting and equity-research analysis. Focus on narrative content: management discussion, risk factors, forward-looking statements, going-concern and material-weakness disclosures, auditor changes, restatements, comment-letter disputes, segment reporting, customer concentration, and officer signatures. Do NOT extract individual financial line items as Layer-1 facts unless they appear in narrative context (aggregators like FactSet handle structured-tabular extraction better). Capture epistemic status precisely: forward-looking statements are PROPHETIC, risk-factor 'may/could/might' language is HYPOTHESIZED, audited and restated figures are ASSERTED, comment-letter disputes and qualified opinions are CONTESTED, 8-K reversals and restatements are CONTRADICTED, explicit denials are NEGATIVE, aspirational claims without quantitative anchors are SPECULATIVE.

## Entity Types

| Type | Description |
|------|-------------|
| Filer | A public company or registrant that submits filings to the SEC. Identified by CIK (10-digit numeric) and ticker symbol when applicable. Examples: 'Acme Therapeutics, Inc. (CIK 0001234567, NASDAQ:ACME)'. |
| Filing | A specific document submitted to SEC EDGAR. Forms include 10-K (annual), 10-Q (quarterly), 8-K (current/material event), S-1 (IPO registration), DEF 14A (proxy), 10-K/A or 10-Q/A (amendments), and SEC comment-letter exchanges (UPLOAD/CORRESP). Capture form type, filing date, and period of report. |
| Segment | A reportable business segment or operating segment as disclosed in the filing (e.g., 'Oncology', 'Diagnostics', 'Consumer Health'). Tied to a Filer via HAS_SEGMENT. |
| Geography | A country, region, or geographic market in which the Filer or a Segment operates (e.g., 'United States', 'EMEA', 'Greater China'). Linked via OPERATES_IN. |
| AuditFirm | An independent registered public accounting firm that audits the Filer's financial statements (e.g., 'Deloitte & Touche LLP', 'PricewaterhouseCoopers LLP', 'BDO USA, LLP'). |
| Customer | A counterparty disclosed as a major customer, typically one accounting for 10%+ of revenue. May be a named entity or a generic descriptor ('Customer A') when redacted. |
| Risk | A risk factor disclosed in Item 1A (10-K) or comparable sections. Includes operational, regulatory, financial, market, and going-concern risks. Hedging language ('may', 'could', 'might') marks the risk as hypothesized. |
| Guidance | Forward-looking management guidance about future financial or operational performance (revenue ranges, EPS targets, margin expansion, product launch timelines). Always epistemically prophetic; safe-harbor language is the canonical signal. |
| ActualResult | An audited or reported actual financial or operational result that can be compared against prior Guidance (e.g., reported quarterly revenue, segment operating income, FDA approval status as reported). Epistemically asserted when audited. |
| Restatement | A formal correction or revision of previously issued financial statements, typically disclosed via 8-K Item 4.02 (non-reliance) or in a 10-K/A or 10-Q/A amendment. Identifies the periods restated and the nature of the error. |
| AdverseAction | A material adverse event affecting the Filer's reporting integrity or operations: SEC enforcement action, going-concern qualification, material weakness disclosure, qualified or adverse audit opinion, NT-10K late-filing notice, or delisting notification. |
| Officer | A named executive, director, or principal officer who signs filings or is referenced in proxy materials. Includes CEO, CFO, Chairman, audit-committee members, and certifying officers under SOX 302/906. |

## Relation Types

| Type | Description |
|------|-------------|
| FILES | Links a Filer to a Filing it submitted. Source: Filer. Target: Filing. |
| ISSUES_GUIDANCE | Links a Filer (or a specific Filing) to a Guidance entity it issues. Source: Filer or Filing. Target: Guidance. |
| REPORTS | Links a Filer (or Filing) to an ActualResult it reports. Source: Filer or Filing. Target: ActualResult. |
| DISCLOSES_RISK | Links a Filing to a Risk it discloses (typically Item 1A or MD&A risk-factor language). Source: Filing. Target: Risk. |
| AMENDS | Links an amended filing (10-K/A, 10-Q/A) to the original Filing it amends. Source: amending Filing. Target: original Filing. |
| RESTATES | Links a Restatement to the prior Filing(s) or ActualResult(s) whose figures it corrects. Source: Restatement. Target: Filing or ActualResult. |
| CONTRADICTS | Links a later disclosure (Guidance, ActualResult, Restatement, or 8-K event) to an earlier Guidance or ActualResult that it materially reverses or invalidates. Drives epistemic 'contradicted' status. |
| AUDITS | Links an AuditFirm to a Filer or Filing whose financial statements it audits. Source: AuditFirm. Target: Filer or Filing. |
| CHANGES_AUDITOR | Links a Filer to a new AuditFirm following an auditor change (typically disclosed via 8-K Item 4.01). Captures the transition; pair with AUDITS edges to the prior and successor firms. |
| HAS_SEGMENT | Links a Filer to a reportable Segment it discloses. Source: Filer. Target: Segment. |
| OPERATES_IN | Links a Filer or Segment to a Geography in which it operates or generates revenue. Source: Filer or Segment. Target: Geography. |
| HAS_MAJOR_CUSTOMER | Links a Filer to a Customer disclosed as material (typically 10%+ of revenue). Source: Filer. Target: Customer. |
| COMMENTS_ON | Links an SEC staff comment-letter Filing (UPLOAD) to the underlying Filing it questions. Source: comment-letter Filing. Target: underlying Filing. |
| RESPONDS_TO | Links a CORRESP response Filing to the SEC staff comment letter (UPLOAD) it answers. Source: CORRESP Filing. Target: UPLOAD Filing. |
| HAS_SIGNATORY | Links a Filing to an Officer who signed or certified it (e.g., SOX 302/906 certifications). Source: Filing. Target: Officer. |

## Extraction Guidelines

Extract Filer, Filing, Segment, Geography, AuditFirm, Customer, Risk, Guidance, ActualResult, Restatement, AdverseAction, and Officer entities, plus the 15 relation types (FILES, ISSUES_GUIDANCE, REPORTS, DISCLOSES_RISK, AMENDS, RESTATES, CONTRADICTS, AUDITS, CHANGES_AUDITOR, HAS_SEGMENT, OPERATES_IN, HAS_MAJOR_CUSTOMER, COMMENTS_ON, RESPONDS_TO, HAS_SIGNATORY). For each Filer, capture CIK (10-digit numeric) and ticker symbol when present. Tag every Guidance as prophetic; every Risk with hedging modal verbs as hypothesized; every Restatement as contradicted with a CONTRADICTS edge to the prior reported figure when identifiable. Treat SEC comment-letter exchanges as paired Filing entities linked via COMMENTS_ON / RESPONDS_TO, marking unresolved disputes as contested. Cite section and form item numbers in evidence (e.g., '10-K Item 1A', '8-K Item 4.02').

## Naming Standards (CRITICAL — required for cross-document dedup)

Cross-document entity resolution depends on byte-identical names. Follow these rules without exception.

### Filer (most important)
- Use the EXACT registered company name from the EDGAR cover page, including the legal-form suffix and any ampersand. Do NOT shorten, expand, or paraphrase.
- Examples (canonical → wrong forms to avoid):
  - `Organon & Co.` — NOT `Organon`, NOT `Organon, Inc.`, NOT `Organon and Co`, NOT `OGN`
  - `Eli Lilly and Company` — NOT `Eli Lilly`, NOT `Lilly`, NOT `Eli Lilly & Co.`, NOT `LLY`
  - `Merck & Co., Inc.` — NOT `Merck`, NOT `Merck Inc`, NOT `Merck and Co`
  - `Regeneron Pharmaceuticals, Inc.` — NOT `Regeneron`, NOT `Regeneron Pharma`
- The ticker (e.g., `OGN`, `LLY`) and CIK (e.g., `0001821825`) belong in `attributes`, not in the entity name.
- One Filer per filer per corpus. If you see the company name written multiple ways in a single document, emit ONE Filer entity using the cover-page form.

### Filing
- Use the form-type prefix + filing date + accession number as the canonical name: `10-K 2026-02-24 (acc 0001628280-26-011125)`. This is unique per filing and stable across documents that reference each other.
- The document_id field is for the file-on-disk; the entity name is the human-readable identifier above.

### AuditFirm
- Use the legal name as it appears in the Report of Independent Registered Public Accounting Firm: `PricewaterhouseCoopers LLP`, `Deloitte & Touche LLP`, `Ernst & Young LLP`, `KPMG LLP`, `BDO USA, LLP`. Do NOT use shortened forms (`PwC`, `Deloitte`, `EY`, `KPMG`).

### Officer
- Use `First Last` (no middle initials unless the document uniformly uses them; pick one form and stick to it across all chunks of the same document). Strip titles from the name itself; put the role in `attributes.role` (e.g., `attributes.role: "Chief Executive Officer"`).

### Restatement and AdverseAction (high-signal — never collapse into Risk)
- Material weaknesses, going-concern qualifications, audit-committee investigations, restatements, and SEC enforcement actions are FIRST-CLASS entities of type `AdverseAction` or `Restatement` — never embed them as Risk attributes. The narrator and downstream analytics depend on these being typed correctly.
- Tag the entity with `attributes.epistemic_status: "contradicted"` for restatements and `attributes.epistemic_status: "contested"` for unresolved comment-letter disputes.
