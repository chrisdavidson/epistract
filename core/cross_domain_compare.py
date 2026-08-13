#!/usr/bin/env python3
"""cross_domain_compare -- domain-blind comparison primitives for
core/cross_domain.py.

Two comparison modes live here:

1. Canonical-key set difference (``classify_miss``) -- given a probe object
   key that is NOT already covered by the reference graph's own key set for
   the same subject, classify the miss into one of three subtypes:
   granularity variant, attributed elsewhere, or absent. Used by the
   ``spine_keys`` compare mode (safety-signal and exposure rules).

2. Configurable token coverage (``tokenize`` / ``coverage_ratio`` /
   ``resolve_band``) -- what fraction of a probe key's tokens appear in a
   block of reference text. Used by the ``text_tokens`` compare mode (the
   coverage rule), whose reference side holds no comparably-typed entities
   to key-difference against.

Every primitive here is parameterised entirely by its caller: word lists,
regex patterns, minimum lengths, thresholds and band tables all arrive as
arguments from the rules spec (crosswalks/pharma-rules.yaml). None of these
functions contain a domain's vocabulary -- no molecule names, no clinical
terms, no entity or relation type names.
"""

from __future__ import annotations

import re

SUBTYPE_GRANULARITY_VARIANT = "granularity_variant"
SUBTYPE_ATTRIBUTED_ELSEWHERE = "attributed_elsewhere"
SUBTYPE_ABSENT = "absent"

__all__ = [
    "SUBTYPE_ABSENT",
    "SUBTYPE_ATTRIBUTED_ELSEWHERE",
    "SUBTYPE_GRANULARITY_VARIANT",
    "classify_miss",
    "coverage_ratio",
    "resolve_band",
    "tokenize",
]


# ---------------------------------------------------------------------------
# Canonical-key set difference (spine_keys compare mode)
# ---------------------------------------------------------------------------


def classify_miss(
    probe_key: str, subject_reference_keys: set[str], all_reference_keys: set[str]
) -> dict:
    """Classify one probe object key that the caller has already determined
    is a miss for this subject (i.e. ``probe_key`` is NOT already an element
    of ``subject_reference_keys`` -- that is coverage, not a miss, and is
    never passed in here).

    Returns ``{"subtype": ..., "reference_variants": [...]}``.
    ``reference_variants`` is non-empty only for the granularity subtype,
    naming the same-subject reference key(s) the probe key collided with.

    Classification order is LOAD-BEARING and deliberately not commutative:
    the granularity test runs first, against the reference keys already
    attached to this SAME subject; only if that finds nothing does the
    "present anywhere in the reference graph" test run, against every
    object key the reference graph holds for the axis pair, regardless of
    subject. A key that would satisfy both tests comes back as the
    granularity variant. Reordering these two checks reclassifies real
    misses: a class-effect signal (attributed_elsewhere, the more clinically
    interesting question) would be swallowed by a same-subject vocabulary
    artifact, or vice versa.
    """
    variants = sorted(
        ref_key
        for ref_key in subject_reference_keys
        if ref_key != probe_key and (probe_key in ref_key or ref_key in probe_key)
    )
    if variants:
        return {"subtype": SUBTYPE_GRANULARITY_VARIANT, "reference_variants": variants}
    if probe_key in all_reference_keys:
        return {"subtype": SUBTYPE_ATTRIBUTED_ELSEWHERE, "reference_variants": []}
    return {"subtype": SUBTYPE_ABSENT, "reference_variants": []}


# ---------------------------------------------------------------------------
# Token coverage (text_tokens compare mode)
# ---------------------------------------------------------------------------


def tokenize(text: str | None, pattern: str, min_token_length: int, stopwords: set[str]) -> set[str]:
    """Tokenize ``text`` per the rule's own config: a regex pattern, a
    minimum token length, and a stopword list. Every parameter is supplied
    by the caller -- this function holds no vocabulary of its own. Matching
    is case-insensitive (the pattern runs against the lowercased text)."""
    if not text:
        return set()
    compiled = re.compile(pattern)
    candidates = compiled.findall(text.lower())
    return {tok for tok in candidates if len(tok) >= min_token_length and tok not in stopwords}


def coverage_ratio(probe_tokens: set[str], reference_tokens: set[str]) -> float:
    """Fraction of ``probe_tokens`` also present in ``reference_tokens``.

    A probe side with no tokens left after tokenization (e.g. every
    candidate token was a stopword) has nothing to fail coverage on, so it
    scores a vacuous 1.0 rather than raising a division error.
    """
    if not probe_tokens:
        return 1.0
    return len(probe_tokens & reference_tokens) / len(probe_tokens)


def resolve_band(ratio: float, bands: list[dict]) -> str | None:
    """Return the configured severity for a ratio falling in one of
    ``bands`` (each ``{"below": float, "severity": str}``, tried in the
    order given -- the rules spec declares them ascending). The upper edge
    of each band is EXCLUSIVE: a ratio exactly equal to a band's ``below``
    value falls through to the next band, not this one. Returns None if no
    band's bound exceeds the ratio (the caller's reporting threshold should
    already have excluded any ratio that would reach this)."""
    for band in bands:
        if ratio < band["below"]:
            return band["severity"]
    return None
