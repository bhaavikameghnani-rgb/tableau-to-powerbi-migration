#!/usr/bin/env python3
"""Extract a normalized visual inventory from a Power BI PBIP/PBIR report.

Usage:
    python scripts/extract_powerbi_visuals.py <ReportDir> -o powerbi-visuals.json

The output is intentionally independent of Tableau. It captures the parts of PBIR that are
useful for Tableau -> Power BI fidelity validation: pages, visual type, title, position,
query-state roles, fields, filters, and visual objects.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Iterable


def read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as fh:
        value = json.load(fh)
    return value if isinstance(value, dict) else {}


def clean_literal(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == "'" and value[-1] == "'":
        value = value[1:-1]
    return value.replace("''", "'")


def expression_field(node: Any) -> tuple[str | None, str | None, str | None]:
    """Return (entity, property, kind) from a PBIR field expression."""
    if not isinstance(node, dict):
        return None, None, None
    for kind in ("Column", "Measure"):
        body = node.get(kind)
        if not isinstance(body, dict):
            continue
        expr = body.get("Expression", {})
        src = expr.get("SourceRef", {}) if isinstance(expr, dict) else {}
        entity = src.get("Entity") if isinstance(src, dict) else None
        prop = body.get("Property")
        if isinstance(entity, str) and isinstance(prop, str):
            return entity, prop, kind
    # Hierarchy levels are useful too.
    hierarchy = node.get("HierarchyLevel")
    if isinstance(hierarchy, dict):
        expr = hierarchy.get("Expression", {})
        src = expr.get("SourceRef", {}) if isinstance(expr, dict) else {}
        entity = src.get("Entity") if isinstance(src, dict) else None
        level = hierarchy.get("Level")
        if isinstance(entity, str) and isinstance(level, str):
            return entity, level, "HierarchyLevel"
    return None, None, None


def walk_field_nodes(node: Any) -> Iterable[tuple[str, str, str]]:
    """Walk arbitrary PBIR query JSON and yield referenced fields."""
    if isinstance(node, dict):
        entity, prop, kind = expression_field(node)
        if entity and prop and kind:
            yield entity, prop, kind
        for value in node.values():
            yield from walk_field_nodes(value)
    elif isinstance(node, list):
        for value in node:
            yield from walk_field_nodes(value)


def title_from_container(visual: dict[str, Any]) -> str | None:
    objects = visual.get("visualContainerObjects")
    if not isinstance(objects, dict):
        return None
    title = objects.get("title")
    if not isinstance(title, list):
        return None
    for item in title:
        if not isinstance(item, dict):
            continue
        props = item.get("properties")
        if not isinstance(props, dict):
            continue
        text = props.get("text")
        if isinstance(text, dict):
            expr = text.get("expr", {})
            literal = expr.get("Literal", {}) if isinstance(expr, dict) else {}
            value = literal.get("Value") if isinstance(literal, dict) else None
            if isinstance(value, str):
                return clean_literal(value)
    return None


def visual_objects_summary(visual: dict[str, Any]) -> dict[str, Any]:
    objects = visual.get("objects")
    if not isinstance(objects, dict):
        objects = {}
    return {str(k): True for k in objects}


def extract_visual(path: Path, page_name: str, page_id: str) -> dict[str, Any] | None:
    payload = read_json(path)
    visual = payload.get("visual")
    if not isinstance(visual, dict):
        return None
    visual_type = visual.get("visualType")
    if not isinstance(visual_type, str):
        visual_type = "unknown"
    position = payload.get("position") if isinstance(payload.get("position"), dict) else {}
    query = visual.get("query") if isinstance(visual.get("query"), dict) else {}
    query_state = query.get("queryState") if isinstance(query.get("queryState"), dict) else {}

    roles: dict[str, list[dict[str, Any]]] = {}
    fields: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for role, state in query_state.items():
        projections = state.get("projections", []) if isinstance(state, dict) else []
        if not isinstance(projections, list):
            continue
        roles[role] = []
        for projection in projections:
            if not isinstance(projection, dict):
                continue
            field_node = projection.get("field")
            entity, prop, kind = expression_field(field_node)
            item = {
                "role": role,
                "entity": entity,
                "property": prop,
                "kind": kind,
                "query_ref": projection.get("queryRef"),
                "native_query_ref": projection.get("nativeQueryRef"),
            }
            roles[role].append(item)
            if entity and prop and kind:
                key = (role, entity, prop, kind)
                if key not in seen:
                    seen.add(key)
                    fields.append(item.copy())

    # Also catch field references nested in filters/other query nodes that are not projections.
    for entity, prop, kind in walk_field_nodes(query):
        key = ("__query__", entity, prop, kind)
        if key not in seen:
            seen.add(key)
            fields.append({"role": "__query__", "entity": entity, "property": prop, "kind": kind})

    title = title_from_container(visual)
    if not title:
        # Some generated visuals carry a simple name only. Do not treat the GUID as a title.
        title = None

    return {
        "id": payload.get("name") or path.parent.name,
        "page_id": page_id,
        "page_name": page_name,
        "path": str(path),
        "visual_type": visual_type,
        "title": title,
        "position": {k: position.get(k) for k in ("x", "y", "width", "height")},
        "roles": roles,
        "fields": fields,
        "objects": visual_objects_summary(visual),
        "has_query": bool(query_state),
    }


def extract_report(report_dir: Path) -> dict[str, Any]:
    pages_root = report_dir / "definition" / "pages"
    pages: list[dict[str, Any]] = []
    if not pages_root.is_dir():
        raise FileNotFoundError(f"PBIR pages directory not found: {pages_root}")

    for page_json in sorted(pages_root.rglob("page.json")):
        page = read_json(page_json)
        page_id = page_json.parent.name
        page_name = page.get("displayName") or page.get("name") or page_id
        if not isinstance(page_name, str):
            page_name = page_id
        visuals = []
        for visual_json in sorted(page_json.parent.rglob("visual.json")):
            visual = extract_visual(visual_json, page_name, page_id)
            if visual:
                visuals.append(visual)
        pages.append({"id": page_id, "name": page_name, "visuals": visuals})

    return {
        "schema_version": "1.0",
        "report": report_dir.name,
        "pages": pages,
        "visual_count": sum(len(p["visuals"]) for p in pages),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("-o", "--output", type=Path, required=True)
    args = parser.parse_args()
    result = extract_report(args.report.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {args.output} ({result['visual_count']} visuals)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
