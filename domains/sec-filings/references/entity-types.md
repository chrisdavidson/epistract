# Domain Entity Types

## Filer
A public company or registrant that submits filings to the SEC. Identified by CIK (10-digit numeric) and ticker symbol when applicable. Examples: 'Acme Therapeutics, Inc. (CIK 0001234567, NASDAQ:ACME)'.

## Filing
A specific document submitted to SEC EDGAR. Forms include 10-K (annual), 10-Q (quarterly), 8-K (current/material event), S-1 (IPO registration), DEF 14A (proxy), 10-K/A or 10-Q/A (amendments), and SEC comment-letter exchanges (UPLOAD/CORRESP). Capture form type, filing date, and period of report.

## Segment
A reportable business segment or operating segment as disclosed in the filing (e.g., 'Oncology', 'Diagnostics', 'Consumer Health'). Tied to a Filer via HAS_SEGMENT.

## Geography
A country, region, or geographic market in which the Filer or a Segment operates (e.g., 'United States', 'EMEA', 'Greater China'). Linked via OPERATES_IN.

## AuditFirm
An independent registered public accounting firm that audits the Filer's financial statements (e.g., 'Deloitte & Touche LLP', 'PricewaterhouseCoopers LLP', 'BDO USA, LLP').

## Customer
A counterparty disclosed as a major customer, typically one accounting for 10%+ of revenue. May be a named entity or a generic descriptor ('Customer A') when redacted.

## Risk
A risk factor disclosed in Item 1A (10-K) or comparable sections. Includes operational, regulatory, financial, market, and going-concern risks. Hedging language ('may', 'could', 'might') marks the risk as hypothesized.

## Guidance
Forward-looking management guidance about future financial or operational performance (revenue ranges, EPS targets, margin expansion, product launch timelines). Always epistemically prophetic; safe-harbor language is the canonical signal.

## ActualResult
An audited or reported actual financial or operational result that can be compared against prior Guidance (e.g., reported quarterly revenue, segment operating income, FDA approval status as reported). Epistemically asserted when audited.

## Restatement
A formal correction or revision of previously issued financial statements, typically disclosed via 8-K Item 4.02 (non-reliance) or in a 10-K/A or 10-Q/A amendment. Identifies the periods restated and the nature of the error.

## AdverseAction
A material adverse event affecting the Filer's reporting integrity or operations: SEC enforcement action, going-concern qualification, material weakness disclosure, qualified or adverse audit opinion, NT-10K late-filing notice, or delisting notification.

## Officer
A named executive, director, or principal officer who signs filings or is referenced in proxy materials. Includes CEO, CFO, Chairman, audit-committee members, and certifying officers under SOX 302/906.
