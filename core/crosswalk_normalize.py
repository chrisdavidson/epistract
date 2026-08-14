#!/usr/bin/env python3
"""Generic, domain-blind normalizer primitives for crosswalk canonicalisation.

Every primitive here is a pure ``str -> str | None`` transform whose behaviour
is entirely controlled by the declarative step dict passed to it (an ``op``
name plus op-specific parameters such as ``pattern``, ``map``, or ``tokens``).
None of these functions know anything about a domain's vocabulary -- that
vocabulary is supplied by the caller's config, never hardcoded here.

Usage:

    >>> run_chain("  Widget W-1234  ", [
    ...     {"op": "collapse_whitespace"},
    ...     {"op": "regex_extract", "pattern": r"W-\\d{4}"},
    ...     {"op": "uppercase"},
    ... ])
    'W-1234'

A chain is a list of step dicts. ``run_chain`` builds (compiles) the chain
and runs it in one call -- convenient for tests and one-off use. Callers that
apply the same chain to many values (the crosswalk key-extraction hot path)
should call ``build_chain`` once per axis and reuse the compiled result via
``run_compiled_chain`` for every candidate value, so regex patterns are
compiled once rather than re-compiled per value.
"""

from __future__ import annotations

import re
from collections.abc import Callable

from .config_types import CrosswalkConfigError

__all__ = [
    "CrosswalkConfigError",
    "Primitive",
    "build_chain",
    "run_chain",
    "run_compiled_chain",
]

Primitive = Callable[[str], "str | None"]


def _op_lowercase(step: dict) -> Primitive:
    def _apply(value: str) -> str | None:
        return value.lower()

    return _apply


def _op_uppercase(step: dict) -> Primitive:
    def _apply(value: str) -> str | None:
        return value.upper()

    return _apply


def _op_collapse_whitespace(step: dict) -> Primitive:
    _WS = re.compile(r"\s+")

    def _apply(value: str) -> str | None:
        return _WS.sub(" ", value.strip())

    return _apply


def _op_regex_extract(step: dict) -> Primitive:
    pattern = step.get("pattern")
    if pattern is None:
        raise CrosswalkConfigError("regex_extract step is missing required 'pattern'")
    compiled = re.compile(pattern)

    def _apply(value: str) -> str | None:
        match = compiled.search(value)
        return match.group(0) if match else None

    return _apply


def _op_replace_map(step: dict) -> Primitive:
    mapping = step.get("map") or {}
    # Freeze the ordered substitution list once, at build time.
    substitutions = list(mapping.items())

    def _apply(value: str) -> str | None:
        for old, new in substitutions:
            value = value.replace(old, new)
        return value

    return _apply


def _op_strip_trailing_tokens(step: dict) -> Primitive:
    tokens = frozenset(t.lower() for t in (step.get("tokens") or []))

    def _apply(value: str) -> str | None:
        parts = value.split()
        while len(parts) > 1 and parts[-1].lower() in tokens:
            parts.pop()
        return " ".join(parts)

    return _apply


_PRIMITIVE_FACTORIES: dict[str, Callable[[dict], Primitive]] = {
    "lowercase": _op_lowercase,
    "uppercase": _op_uppercase,
    "collapse_whitespace": _op_collapse_whitespace,
    "regex_extract": _op_regex_extract,
    "replace_map": _op_replace_map,
    "strip_trailing_tokens": _op_strip_trailing_tokens,
}


def build_chain(chain: list[dict]) -> list[Primitive]:
    """Compile a declarative normalizer chain into a list of callables.

    Regex patterns and token sets are compiled/frozen once here, not per
    value. Raises CrosswalkConfigError naming the offending op if any step's
    ``op`` is not a known primitive.
    """
    compiled: list[Primitive] = []
    for step in chain:
        op = step.get("op")
        factory = _PRIMITIVE_FACTORIES.get(op)
        if factory is None:
            raise CrosswalkConfigError(
                f"Unknown normalizer op {op!r}. Known ops: "
                f"{', '.join(sorted(_PRIMITIVE_FACTORIES))}"
            )
        compiled.append(factory(step))
    return compiled


def run_compiled_chain(value: str, compiled: list[Primitive]) -> str | None:
    """Run a pre-built chain (from build_chain) over one value."""
    current: str | None = value
    for fn in compiled:
        if current is None:
            return None
        current = fn(current)
    return current


def run_chain(value: str, chain: list[dict]) -> str | None:
    """Build and run a declarative chain over one value in a single call.

    For hot paths applying the same chain to many values, prefer calling
    ``build_chain`` once and reusing the result via ``run_compiled_chain``.
    """
    return run_compiled_chain(value, build_chain(chain))
