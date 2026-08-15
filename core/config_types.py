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
    "validate_domain_crosswalk_types",
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
            f"{_located(source, key_path)}: expected a list, got {value!r} ({type(value).__name__})"
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

# The eight top-level string fields of a rule. Driven from this tuple
# rather than eight repeated call sites -- see validate_rule_types.
_RULE_STRING_FIELDS = (
    "name",
    "type",
    "probe",
    "reference",
    "subject_axis",
    "object_axis",
    "compare",
    "caveat",
)


def _validate_tokenizer_block(token_cfg: dict, *, source: str | None, index: int) -> None:
    """Assert only the string-typed tokenizer fields that are present: the
    token pattern, the stopword list, and each grade band's grade word.

    Assert nothing else here. The advisory flag, the minimum token length,
    the reporting threshold, and every grade band bound are legitimately
    non-string and must never be touched -- this is the invariant the
    negative control from Task 1 defends.
    """
    prefix = f"rules[{index}].text_tokens"
    if "token_pattern" in token_cfg:
        assert_str(token_cfg["token_pattern"], source=source, key_path=f"{prefix}.token_pattern")
    if "stopwords" in token_cfg:
        assert_str_list(token_cfg["stopwords"], source=source, key_path=f"{prefix}.stopwords")
    for i, band in enumerate(token_cfg.get("severity_bands") or []):
        if isinstance(band, dict) and "severity" in band:
            assert_str(
                band["severity"],
                source=source,
                key_path=f"{prefix}.severity_bands[{i}].severity",
            )


def validate_rule_types(raw_rule: dict, *, source: str | None, index: int) -> None:
    """Assert the string-typed fields of one rules-spec rule that are
    PRESENT: the eight top-level string fields, the grade table (keys and
    values), the description table (keys and values), and -- inside the
    tokenizer block, when present -- the token pattern, the stopword
    list, and each grade band's grade word.

    Never adds a required-key check -- presence of a required key remains
    the sole job of load_rules_spec's existing required-key gate.
    """
    for field in _RULE_STRING_FIELDS:
        if field in raw_rule:
            assert_str(raw_rule[field], source=source, key_path=f"rules[{index}].{field}")

    if "severity" in raw_rule:
        assert_str_mapping(raw_rule["severity"], source=source, key_path=f"rules[{index}].severity")
    if "descriptions" in raw_rule:
        assert_str_mapping(
            raw_rule["descriptions"], source=source, key_path=f"rules[{index}].descriptions"
        )

    token_cfg = raw_rule.get("text_tokens")
    if isinstance(token_cfg, dict):
        _validate_tokenizer_block(token_cfg, source=source, index=index)


def _validate_value_source(source_cfg: object, *, source: str | None, key_path: str) -> None:
    """Assert one value-source mapping's kind ('from') and optional
    attribute key ('key') are strings, when present. Shared by axis
    sources, axis identifier sources, and edge text_sources -- three call
    sites, which is why this is factored out rather than inlined."""
    if not isinstance(source_cfg, dict):
        return
    if "from" in source_cfg:
        assert_str(source_cfg["from"], source=source, key_path=f"{key_path}.from")
    if "key" in source_cfg:
        assert_str(source_cfg["key"], source=source, key_path=f"{key_path}.key")


def validate_domain_crosswalk_types(config: dict, source: str | None) -> None:
    """Assert the string-typed fields of one per-domain crosswalk config
    that are PRESENT: each key of the axes mapping, each axis's
    participating-type list, each value source's kind and optional
    attribute key, each identifier label and its source, and each edge's
    subject, object, relation list, and text sources.

    Assert type only, never truthiness -- an absent optional field is not
    an error, an empty list is not an error, and an empty string value is
    not an error (the shipped axis spec maps a marker to "").
    """
    for axis_name, axis_cfg in (config.get("axes") or {}).items():
        assert_str(axis_name, source=source, key_path="axes key")
        axis_cfg = axis_cfg or {}
        axis_path = f"axes.{axis_name}"

        if "entity_types" in axis_cfg:
            assert_str_list(
                axis_cfg["entity_types"], source=source, key_path=f"{axis_path}.entity_types"
            )
        for i, src in enumerate(axis_cfg.get("sources") or []):
            _validate_value_source(src, source=source, key_path=f"{axis_path}.sources[{i}]")
        for label, id_source in (axis_cfg.get("identifiers") or {}).items():
            assert_str(label, source=source, key_path=f"{axis_path}.identifiers key")
            _validate_value_source(
                id_source, source=source, key_path=f"{axis_path}.identifiers.{label}"
            )

    for i, edge in enumerate(config.get("edges") or []):
        edge = edge or {}
        edge_path = f"edges[{i}]"
        if "subject" in edge:
            assert_str(edge["subject"], source=source, key_path=f"{edge_path}.subject")
        if "object" in edge:
            assert_str(edge["object"], source=source, key_path=f"{edge_path}.object")
        if "relations" in edge:
            assert_str_list(edge["relations"], source=source, key_path=f"{edge_path}.relations")
        for j, src in enumerate(edge.get("text_sources") or []):
            _validate_value_source(src, source=source, key_path=f"{edge_path}.text_sources[{j}]")
