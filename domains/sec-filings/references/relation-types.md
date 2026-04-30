# Domain Relation Types

## FILES
Links a Filing to the Filer that submitted it. Source: Filing. Target: Filer.

## ISSUES_GUIDANCE
Links a Filer (or a specific Filing) to a Guidance entity it issues. Source: Filer or Filing. Target: Guidance.

## REPORTS
Links a Filer (or Filing) to an ActualResult it reports. Source: Filer or Filing. Target: ActualResult.

## DISCLOSES_RISK
Links a Filing to a Risk it discloses (typically Item 1A or MD&A risk-factor language). Source: Filing. Target: Risk.

## AMENDS
Links an amended filing (10-K/A, 10-Q/A) to the original Filing it amends. Source: amending Filing. Target: original Filing.

## RESTATES
Links a Restatement to the prior Filing(s) or ActualResult(s) whose figures it corrects. Source: Restatement. Target: Filing or ActualResult.

## CONTRADICTS
Links a later disclosure (Guidance, ActualResult, Restatement, or 8-K event) to an earlier Guidance or ActualResult that it materially reverses or invalidates. Drives epistemic 'contradicted' status.

## AUDITS
Links a Filer or Filing to the AuditFirm that issued the audit opinion. Source: Filer or Filing. Target: AuditFirm.

## CHANGES_AUDITOR
Links a Filer to a new AuditFirm following an auditor change (typically disclosed via 8-K Item 4.01). Captures the transition; pair with AUDITS edges to the prior and successor firms.

## HAS_SEGMENT
Links a Filer to a reportable Segment it discloses. Source: Filer. Target: Segment.

## OPERATES_IN
Links a Filer or Segment to a Geography in which it operates or generates revenue. Source: Filer or Segment. Target: Geography.

## HAS_MAJOR_CUSTOMER
Links a Filer to a Customer disclosed as material (typically 10%+ of revenue). Source: Filer. Target: Customer.

## COMMENTS_ON
Links an SEC staff comment-letter Filing (UPLOAD) to the underlying Filing it questions. Source: comment-letter Filing. Target: underlying Filing.

## RESPONDS_TO
Links an SEC staff comment letter to the Filer's response correspondence (CORRESP). Source: comment-letter Filing. Target: response Filing.

## HAS_SIGNATORY
Links a Filing to an Officer who signed or certified it (e.g., SOX 302/906 certifications). Source: Filing. Target: Officer.
