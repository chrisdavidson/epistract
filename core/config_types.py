#!/usr/bin/env python3
"""Shared config-loading primitives for the crosswalk and cross-domain
config layers (core/crosswalk.py, core/crosswalk_normalize.py,
core/cross_domain.py).

This is a leaf module: it imports nothing from any other core module, and
it holds no domain vocabulary -- only the framework schema key names common
to every hand-authored config in this layer (axis names, entity-type
lists, relation lists, stopword lists, and so on).

Why this module exists: PyYAML implements YAML 1.1, where a bare
`on/off/yes/no` (any case) or `null`/`~` parses as a bool or None even
though it looks like an ordinary string in the source file. A hand-authored
config that writes one of these bare words in a string-typed field gets a
silently retyped value -- which several consumers then either fail on with
an interpreter-internal error, or worse, tolerate silently and produce a
clean-looking zero-finding run. The primitives here assert TYPE ONLY, never
truthiness -- an empty string is a valid string, an empty list or mapping
is a valid container -- so a call site can wire an assertion onto any
string-typed field without ever rejecting a legitimately empty or absent
one.
"""

from __future__ import annotations

__all__ = [
    "CrosswalkConfigError",
    "assert_str",
    "assert_str_list",
    "assert_str_mapping",
    "validate_rule_types",
]


class CrosswalkConfigError(Exception):
    """Raised when a crosswalk config (axis spec, rules spec, or a
    per-domain crosswalk.yaml) is malformed -- an unknown normalizer op, a
    missing required field, a config that references something another
    file does not declare, or -- the class this module exists to close --
    a string-typed field whose value was silently coerced to a bool or
    None by YAML 1.1's bare-keyword parsing (on/off/yes/no/null).
    """


def _remediation_hint(value: object) -> str:
    """Return a remediation sentence when `value`'s type is the signature
    of a YAML 1.1 bare-keyword coercion (bool or None); "" otherwise.

    Order matters: bool is a subclass of int, so the bool check must come
    first. A genuinely wrong type (an int or float where a string belongs)
    is a different mistake and gets no hint -- the hint would misdirect.
    """
    if isinstance(value, bool) or value is None:
        return (
            " This looks like a YAML 1.1 bare keyword (on/off/yes/no/null) "
            "parsed as a boolean or null instead of the string you wrote. "
            'Quote the value (e.g. "on") to keep it a string.'
        )
    return ""


def _located(source: str | None, key_path: str) -> str:
    return f"{source}: {key_path}" if source else key_path


def assert_str(value: object, *, source: str | None = None, key_path: str) -> str:
    """Assert `value` is a str; return it unchanged when valid."""
    if not isinstance(value, str):
        raise CrosswalkConfigError(
            f"{_located(source, key_path)}: expected a string, got "
            f"{value!r} ({type(value).__name__}).{_remediation_hint(value)}"
        )
    return value


def assert_str_list(value: object, *, source: str | None = None, key_path: str) -> list:
    """Assert `value` is a list whose entries are all str; return it
    unchanged when valid.

    Sweeps the whole list and raises ONE error naming every non-string
    entry with its own key path (including index), repr, and type name --
    a realistic multi-coercion case is a word list where one bare keyword
    plausibly has a sibling three lines down.
    """
    if not isinstance(value, list):
        raise CrosswalkConfigError(
            f"{_located(source, key_path)}: expected a list, got "
            f"{value!r} ({type(value).__name__})"
        )
    offenders = [
        f"{_located(source, f'{key_path}[{i}]')}={item!r} "
        f"({type(item).__name__}){_remediation_hint(item)}"
        for i, item in enumerate(value)
        if not isinstance(item, str)
    ]
    if offenders:
        raise CrosswalkConfigError(
            f"{_located(source, key_path)}: every entry must be a string; "
            "non-string entries:\n  " + "\n  ".join(offenders)
        )
    return value


def assert_str_mapping(value: object, *, source: str | None = None, key_path: str) -> dict:
    """Assert `value` is a mapping whose keys and values are all str;
    return it unchanged when valid.

    Sweeps the whole mapping and raises ONE error naming every non-string
    key and every non-string value, each with its own key path, repr, and
    type name.
    """
    if not isinstance(value, dict):
        raise CrosswalkConfigError(
            f"{_located(source, key_path)}: expected a mapping, got "
            f"{value!r} ({type(value).__name__})"
        )
    offenders = []
    for k, v in value.items():
        if not isinstance(k, str):
            offenders.append(
                f"{_located(source, f'{key_path} key')}={k!r} "
                f"({type(k).__name__}){_remediation_hint(k)}"
            )
        if not isinstance(v, str):
            offenders.append(
                f"{_located(source, f'{key_path}[{k!r}]')}={v!r} "
                f"({type(v).__name__}){_remediation_hint(v)}"
            )
    if offenders:
        raise CrosswalkConfigError(
            f"{_located(source, key_path)}: every key and value must be a "
            "string; offenders:\n  " + "\n  ".join(offenders)
        )
    return value


# ---------------------------------------------------------------------------
# Schema walkers
# ---------------------------------------------------------------------------


def validate_rule_types(raw_rule: dict, *, source: str | None, index: int) -> None:
    """Assert the string-typed fields of one rules-spec rule that are
    PRESENT. Never adds a required-key check -- presence of a required key
    remains the sole job of load_rules_spec's existing required-key gate.

    Only the tokenizer's stopword list is wired here. The remaining rule
    fields (the top-level string fields, the grade and description
    tables, the tokenizer pattern, and each grade band's grade word) are
    wired in a later pass -- see the plan's Task 3.
    """
    token_cfg = raw_rule.get("text_tokens")
    if isinstance(token_cfg, dict) and "stopwords" in token_cfg:
        assert_str_list(
            token_cfg["stopwords"],
            source=source,
            key_path=f"rules[{index}].text_tokens.stopwords",
        )
