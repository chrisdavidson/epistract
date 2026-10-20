#!/usr/bin/env python3
"""Graph display resolution: one color, shape and family per entity type.

Reads the optional ``display`` block of each entity type and the optional
``category`` of each relation type in a domain schema, validates them, and
fills every gap with deterministic defaults so that no two entity types in a
graph share a color. The result is computed once in Python and served to the
browser, so every surface (canvas, filter legend, nav legend, sidebar) reads
the same values.

This is the one ``core`` module the workbench consumer layer imports (the
resolution logic must be reusable by the static graph view as well as the
workbench). It must stay import-light: stdlib and PyYAML only, with no imports
from sibling ``core`` modules or from ``examples``.

Usage:
    display = graph_display.resolve_display(schema, observed_types, overrides)
    display["types"]["COMPOUND"]["color"]
"""

from __future__ import annotations

import colorsys
import copy
import re
from collections.abc import Iterable

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# 24 colors in farthest-first order: any prefix is the best-spread subset of
# that size. Every entry holds >= 3:1 contrast on white and on the dark nav.
PALETTE: list[str] = [
    "#5f66ed", "#249e02", "#ed4b43", "#059eb1", "#cc54c5", "#926a0c",
    "#a35472", "#158561", "#937dc7", "#9344c8", "#3875af", "#889541",
    "#1690ed", "#c1774b", "#bf420d", "#db3d7e", "#bd6f98", "#a665ee",
    "#7f60a6", "#5d7f00", "#1da56c", "#a8439b", "#cb234a", "#c95b63",
]  # fmt: skip

NEUTRAL_COLOR = "#6b7280"

# Shapes whose label is drawn below the node, so node ``size`` keeps working.
ALLOWED_SHAPES: tuple[str, ...] = (
    "dot",
    "square",
    "diamond",
    "triangle",
    "triangleDown",
    "star",
    "hexagon",
)

FAMILY_SHAPES: dict[str, str] = {
    "interventions": "hexagon",
    "molecular": "triangle",
    "conditions": "square",
    "evidence": "star",
    "actors": "diamond",
    "concepts": "triangleDown",
    "sources": "dot",
}

# Other and Sources intentionally share ``dot``: both are neutral catch-all
# families (Sources nodes are also grey and drawn smaller), so the pair is not
# reported as a shape collision. Any other shared shape produces a warning.
SHARED_DOT_FAMILIES: frozenset[str] = frozenset({"other", "sources"})

# Order in which shapes are handed to families that have no default shape.
CUSTOM_SHAPE_ORDER: tuple[str, ...] = (
    "dot",
    "square",
    "diamond",
    "triangle",
    "hexagon",
    "triangleDown",
    "star",
)

# Types the pipeline itself creates; they never appear in a domain schema.
PIPELINE_TYPES: dict[str, dict] = {
    "DOCUMENT": {"family": "Sources", "shape": "dot", "color": "#6b7280"},
    "PUBLICATION": {"family": "Sources", "shape": "dot", "color": "#a8a29e"},
}
PIPELINE_RELATIONS: dict[str, str] = {
    "MENTIONED_IN": "provenance",
    "PUBLISHED_IN": "provenance",
}
# Relations that only link an entity to its source document; they are hidden
# together with the Sources nodes.
SOURCE_EDGE_RELATIONS: frozenset[str] = frozenset({"MENTIONED_IN"})

RELATION_CATEGORIES: tuple[str, ...] = (
    "mechanism",
    "therapeutic",
    "causal",
    "association",
    "provenance",
    "structural",
    "organizational",
    "regulatory",
    "other",
)

OTHER_FAMILY = "Other"
SOURCES_FAMILY = "Sources"
MAX_FAMILY_LENGTH = 64

_HEX3 = re.compile(r"#[0-9a-fA-F]{3}")
_HEX6 = re.compile(r"#[0-9a-fA-F]{6}")
_CAMEL_LOWER_UPPER = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_CAMEL_ACRONYM = re.compile(r"(?<=[A-Z])(?=[A-Z][a-z])")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


UNKNOWN_TYPE = "UNKNOWN"


def entity_type_key(value: object) -> str:
    """Return the key a node's ``entity_type`` is resolved and looked up under.

    Missing, null and empty types map to ``"UNKNOWN"``; anything else is
    stringified. Every caller that builds ``observed_types`` or looks a type up
    in ``resolve_display(...)["types"]`` must use this, so the two agree.
    """
    if value is None or value == "":
        return UNKNOWN_TYPE
    return str(value)


def humanize_type(type_name: str) -> str:
    """Return a sentence-case label for a type name.

    Splits camelCase boundaries and underscores:
    ``AdverseEvent`` -> ``Adverse event``, ``MECHANISM_OF_ACTION`` ->
    ``Mechanism of action``.
    """
    text = str(type_name or "")
    text = _CAMEL_LOWER_UPPER.sub(" ", text)
    text = _CAMEL_ACRONYM.sub(" ", text)
    text = text.replace("_", " ")
    text = " ".join(text.split()).lower()
    return text[:1].upper() + text[1:]


def _normalize_color(value: object) -> str | None:
    """Return a lowercase ``#rrggbb`` string, or None when value is invalid."""
    if not isinstance(value, str):
        return None
    candidate = value.strip()
    if _HEX6.fullmatch(candidate):
        return candidate.lower()
    if _HEX3.fullmatch(candidate):
        return "#" + "".join(ch * 2 for ch in candidate[1:].lower())
    return None


def _entity_declarations(schema: dict | None) -> dict[str, dict]:
    """Return ``{type: {"description": str, "display": dict}}`` in schema order."""
    declared: dict[str, dict] = {}
    raw = schema.get("entity_types") if isinstance(schema, dict) else None
    if not isinstance(raw, dict):
        return declared
    for name, spec in raw.items():
        if isinstance(spec, str):
            description, display = spec, {}
        elif isinstance(spec, dict):
            description = spec.get("description", "")
            display = spec.get("display")
        else:
            description, display = "", {}
        declared[str(name)] = {
            "description": description if isinstance(description, str) else "",
            "display": display if isinstance(display, dict) else {},
        }
    return declared


def _extra_color(n: int) -> str:
    """Return the n-th deterministic color beyond the fixed palette."""
    hue = ((n * 137.508) % 360) / 360
    lightness = 0.42 if n % 2 == 0 else 0.50
    r, g, b = colorsys.hls_to_rgb(hue, lightness, 0.65)
    return "#{:02x}{:02x}{:02x}".format(round(r * 255), round(g * 255), round(b * 255))


def _next_unclaimed(claimed: set[str], counter: list[int]) -> str:
    """Return the first palette color not in claimed, then generated extras."""
    for color in PALETTE:
        if color not in claimed:
            return color
    while True:
        counter[0] += 1
        color = _extra_color(counter[0])
        if color not in claimed:
            return color


def _resolve_relations(schema: dict | None, warnings: list[str]) -> dict[str, dict]:
    relations: dict[str, dict] = {}
    raw = schema.get("relation_types") if isinstance(schema, dict) else None
    if isinstance(raw, dict):
        for name, spec in raw.items():
            name = str(name)
            if isinstance(spec, str):
                description, category = spec, None
            elif isinstance(spec, dict):
                description = spec.get("description", "")
                category = spec.get("category")
            else:
                description, category = "", None
            if category is None:
                category = "other"
            elif not isinstance(category, str) or category not in RELATION_CATEGORIES:
                warnings.append(f"{name}: unknown category {category!r}; using 'other'")
                category = "other"
            relations[name] = {
                "category": category,
                "description": description if isinstance(description, str) else "",
                "source_edge": name in SOURCE_EDGE_RELATIONS,
            }
    for name, category in PIPELINE_RELATIONS.items():
        relations.setdefault(
            name,
            {
                "category": category,
                "description": "",
                "source_edge": name in SOURCE_EDGE_RELATIONS,
            },
        )
    return relations


def _resolve(
    schema: dict | None,
    observed_types: Iterable[str],
    overrides: dict[str, str] | None,
) -> dict:
    warnings: list[str] = []
    declared = _entity_declarations(schema)
    extra_observed = sorted({str(t) for t in observed_types} - set(declared))
    order = list(declared) + extra_observed
    overrides = overrides if isinstance(overrides, dict) else {}

    colors: dict[str, str] = {}
    origins: dict[str, str] = {}
    declared_shapes: dict[str, str] = {}
    families: dict[str, str] = {}

    for name in order:
        display = declared.get(name, {}).get("display", {})

        override = overrides.get(name)
        if override is not None:
            normalized = _normalize_color(override)
            if normalized:
                colors[name], origins[name] = normalized, "override"
            else:
                warnings.append(f"{name}: invalid entity_colors override {override!r}; ignored")

        if "color" in display:
            normalized = _normalize_color(display["color"])
            if normalized is None:
                warnings.append(
                    f"{name}: invalid display.color {display['color']!r}; using a palette color"
                )
            elif name not in colors:
                colors[name], origins[name] = normalized, "declared"

        if "shape" in display:
            shape = display["shape"]
            if isinstance(shape, str) and shape in ALLOWED_SHAPES:
                declared_shapes[name] = shape
            else:
                warnings.append(
                    f"{name}: invalid display.shape {shape!r}; allowed: {', '.join(ALLOWED_SHAPES)}"
                )

        family = display.get("family")
        if isinstance(family, str) and family.strip():
            families[name] = family.strip()[:MAX_FAMILY_LENGTH]
        elif name in PIPELINE_TYPES:
            families[name] = PIPELINE_TYPES[name]["family"]
        else:
            families[name] = OTHER_FAMILY

    # Families are grouped case-insensitively; give every member of a family the
    # same spelling (the first one seen, or the built-in spelling for the
    # Other/Sources tails) so consumers can compare family names exactly.
    canonical: dict[str, str] = {
        OTHER_FAMILY.lower(): OTHER_FAMILY,
        SOURCES_FAMILY.lower(): SOURCES_FAMILY,
    }
    for name in order:
        canonical.setdefault(families[name].lower(), families[name])
    for name in order:
        families[name] = canonical[families[name].lower()]

    # Colors: authored (override/declared) first, then pipeline greys, then auto.
    claimed: set[str] = set()
    owner: dict[str, str] = {}
    for name in order:
        color = colors.get(name)
        if color is None:
            continue
        if color in owner:
            warnings.append(f"{owner[color]} and {name} share color {color}")
        else:
            owner[color] = name
        claimed.add(color)
    for name in order:
        if name in colors or name not in PIPELINE_TYPES:
            continue
        grey = PIPELINE_TYPES[name]["color"]
        if grey not in claimed:
            colors[name], origins[name] = grey, "pipeline"
            claimed.add(grey)
    counter = [0]
    for name in order:
        if name not in colors:
            colors[name], origins[name] = _next_unclaimed(claimed, counter), "auto"
            claimed.add(colors[name])

    # Families and shapes: a family's shape is fixed by its first member.
    family_names: list[str] = []
    first_member: dict[str, str] = {}
    for name in order:
        key = families[name].lower()
        if key not in first_member:
            first_member[key] = name
            family_names.append(families[name])
    family_shape: dict[str, str] = {}
    for key, member in first_member.items():
        known = declared_shapes.get(member) or FAMILY_SHAPES.get(key)
        if known:
            family_shape[key] = known
        elif key == OTHER_FAMILY.lower():
            family_shape[key] = "dot"
    out_of_shapes: list[str] = []
    for key in first_member:
        if key in family_shape:
            continue
        used = set(family_shape.values())
        shape = next((s for s in CUSTOM_SHAPE_ORDER if s not in used), None)
        if shape is None:
            out_of_shapes.append(families[first_member[key]])
            shape = "dot"
        family_shape[key] = shape
    if out_of_shapes:
        warnings.append(
            f"no unused shape left for families {', '.join(out_of_shapes)}; using 'dot'"
        )
    by_shape: dict[str, list[str]] = {}
    for key in first_member:
        by_shape.setdefault(family_shape[key], []).append(key)
    for shape, keys in by_shape.items():
        if len(keys) < 2 or set(keys) <= SHARED_DOT_FAMILIES:
            continue
        names = [families[first_member[k]] for k in keys]
        warnings.append(f"families {', '.join(names)} share shape {shape!r}")
    for name in order:
        shape = declared_shapes.get(name)
        key = families[name].lower()
        if shape and shape != family_shape[key]:
            warnings.append(
                f"{name}: display.shape {shape!r} differs from family "
                f"{families[name]!r} shape {family_shape[key]!r}; using the family shape"
            )

    types = {
        name: {
            "label": humanize_type(name),
            "description": declared.get(name, {}).get("description", ""),
            "family": families[name],
            "shape": family_shape[families[name].lower()],
            "color": colors[name],
            "origin": origins[name],
            "is_source": families[name] == SOURCES_FAMILY,
        }
        for name in order
    }

    ordered_families = [f for f in family_names if f.lower() not in ("other", "sources")]
    for tail in (OTHER_FAMILY, SOURCES_FAMILY):
        match = next((f for f in family_names if f.lower() == tail.lower()), None)
        if match:
            ordered_families.append(match)

    return {
        "types": types,
        "families": [{"name": f, "shape": family_shape[f.lower()]} for f in ordered_families],
        "relations": _resolve_relations(schema, warnings),
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def is_source_edge(
    edge: dict,
    source_node_ids: set[str] | frozenset[str],
    relations: dict[str, dict],
) -> bool:
    """Return True when an edge only expresses provenance.

    An edge is a source edge when either endpoint is a Sources-family node or
    its relation is flagged ``source_edge``. Never raises on missing keys.
    The graph view and the workbench share this rule.

    Args:
        edge: Edge dict with ``source``, ``target`` and ``relation_type`` keys.
        source_node_ids: Ids of nodes whose resolved type has ``is_source``.
        relations: The ``relations`` map from :func:`resolve_display`.

    Returns:
        True for provenance edges, False for knowledge edges.
    """
    if edge.get("source") in source_node_ids or edge.get("target") in source_node_ids:
        return True
    spec = relations.get(edge.get("relation_type") or "")
    return isinstance(spec, dict) and spec.get("source_edge") is True


def validate_display(schema: dict | None) -> list[str]:
    """Return warnings for invalid display declarations in a schema; never raises."""
    return _resolve(schema, (), None)["warnings"]


def resolve_display(
    schema: dict | None,
    observed_types: Iterable[str] = (),
    overrides: dict[str, str] | None = None,
) -> dict:
    """Resolve color, shape, family and label for every entity type.

    Args:
        schema: Parsed domain.yaml, or None when the graph has no schema.
        observed_types: Entity types found in the graph; types missing from
            the schema are resolved too (sorted, after the schema types).
        overrides: Legacy ``{type: "#rrggbb"}`` colors that win over declared ones.

    Returns:
        ``{"types": {T: {label, description, family, shape, color, origin,
        is_source}}, "families": [{name, shape}],
        "relations": {R: {category, description, source_edge}},
        "warnings": [str]}``. Colors are unique unless the author declared the
        same color twice, which is kept and reported in ``warnings``.
    """
    return _resolve(schema, observed_types, overrides)


def fill_display_defaults(
    entity_types: dict,
    families: dict[str, dict] | None = None,
) -> dict:
    """Return ``{type: {family, shape, color}}`` for every entity type.

    Existing valid ``display`` fields win; ``families`` (``{type: {family,
    shape?, color?}}``) supplies values for undeclared fields. The input is
    never mutated.
    """
    supplied = families if isinstance(families, dict) else {}
    schema_types: dict[str, dict] = {}
    for name, spec in copy.deepcopy(entity_types or {}).items():
        if isinstance(spec, str):
            spec = {"description": spec}
        elif not isinstance(spec, dict):
            spec = {}
        display = spec.get("display")
        display = dict(display) if isinstance(display, dict) else {}
        extra = supplied.get(name)
        if isinstance(extra, dict):
            for key in ("family", "shape", "color"):
                if key in extra:
                    display.setdefault(key, extra[key])
        spec["display"] = display
        schema_types[str(name)] = spec
    resolved = _resolve({"entity_types": schema_types}, (), None)["types"]
    return {
        name: {"family": r["family"], "shape": r["shape"], "color": r["color"]}
        for name, r in resolved.items()
    }
