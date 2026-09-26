#!/usr/bin/env python3
"""Compare Tableau migration-spec.json against a Power BI PBIR report.

Usage:
    python scripts/compare_tableau_powerbi.py migration-spec.json <ReportDir> -o validation.json

This is a deterministic structural validator. It does not use an LLM and it does not collapse
results into a single score. Every matched visual gets property-level PASS/WARN/FAIL findings.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

from extract_powerbi_visuals import extract_report


def norm(value: Any) -> str:
    if value is None:
        return ""
    value = str(value).lower()
    value = re.sub(r"[\n\r\t]+", " ", value)
    value = re.sub(r"[^a-z0-9%]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def tokens(value: Any) -> set[str]:
    return {x for x in norm(value).split() if len(x) > 1}


def tableau_field_catalog(spec: dict[str, Any]) -> dict[str, dict[str, Any]]:
    catalog = {}
    for ds in spec.get("data_sources", []):
        if not isinstance(ds, dict):
            continue
        for field in ds.get("fields", []):
            if isinstance(field, dict) and isinstance(field.get("id"), str):
                catalog[field["id"]] = {
                    "caption": field.get("caption") or field.get("name") or field["id"],
                    "name": field.get("name"),
                    "data_type": field.get("data_type"),
                    "datasource": ds.get("caption") or ds.get("id"),
                }
    return catalog


def tableau_visual_fields(ws: dict[str, Any], catalog: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    enc = ws.get("encodings", {}) if isinstance(ws.get("encodings"), dict) else {}
    for role in ("rows", "columns", "color", "size", "shape", "label", "detail", "tooltip"):
        value = enc.get(role)
        values = value if isinstance(value, list) else ([value] if isinstance(value, dict) else [])
        for item in values:
            if not isinstance(item, dict):
                continue
            fid = item.get("field_id")
            if not isinstance(fid, str) or fid.startswith("UNRESOLVED:"):
                continue
            info = catalog.get(fid, {})
            out.append({
                "role": role,
                "field_id": fid,
                "caption": info.get("caption") or fid,
                "aggregation": item.get("aggregation"),
            })
    pivot = ws.get("measure_names_values_pivot")
    if isinstance(pivot, dict):
        for fid in pivot.get("pivoted_field_ids", []):
            if not isinstance(fid, str) or fid.startswith("UNRESOLVED:"):
                continue
            info = catalog.get(fid, {})
            out.append({"role": "measure_values", "field_id": fid, "caption": info.get("caption") or fid})
    return out


def tableau_filter_fields(ws: dict[str, Any], catalog: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for item in ws.get("filters", []) if isinstance(ws.get("filters"), list) else []:
        if not isinstance(item, dict):
            continue
        fid = item.get("field_id")
        if not isinstance(fid, str) or fid.startswith("UNRESOLVED:"):
            continue
        result.append({
            "field_id": fid,
            "caption": catalog.get(fid, {}).get("caption") or fid,
            "type": item.get("type"),
            "members": [norm(x).strip('"') for x in item.get("members", []) if isinstance(x, str)],
        })
    return result


MARK_MAP = {
    "bar": {"barChart", "clusteredBarChart", "stackedBarChart", "100StackedBarChart"},
    "line": {"lineChart"},
    "circle": {"scatterChart"},
    "square": {"scatterChart"},
    "shape": {"scatterChart", "image"},
    "area": {"areaChart", "stackedAreaChart", "100StackedAreaChart"},
    "pie": {"pieChart", "donutChart"},
    "text": {"tableEx", "matrix", "card", "multiRowCard"},
    "automatic": set(),
    "gantt": {"scatterChart"},
    "map": {"map", "azureMap", "filledMap"},
}

def type_compatible_for_visual(ws: dict[str, Any], pbi: dict[str, Any], catalog: dict[str, dict[str, Any]]) -> bool:
    mark = norm(ws.get("mark_type", ""))
    ptype = pbi.get("visual_type", "")
    if type_compatible(mark, ptype):
        return True
    # Tableau frequently represents latitude/longitude maps as Line/Automatic worksheets.
    # Treat a Power BI map as compatible when the migrated visual contains Lat/Long-like fields.
    if ptype in {"map", "azureMap", "filledMap"} and mark in {"line", "automatic", "circle", "shape"}:
        props = {norm(f.get("property")) for f in pbi.get("fields", [])}
        if {"lat", "long"}.issubset(props) or {"latitude", "longitude"}.issubset(props):
            return True
    return False



def type_compatible(mark_type: str, pbi_type: str) -> bool:
    allowed = MARK_MAP.get(norm(mark_type), set())
    if not allowed:
        return True
    return pbi_type in allowed


def pbi_field_key(item: dict[str, Any]) -> tuple[str, str]:
    return norm(item.get("entity")), norm(item.get("property"))


def field_matches(tfield: dict[str, Any], pfields: list[dict[str, Any]]) -> bool:
    target = tokens(tfield.get("caption"))
    if not target:
        return False
    caption_norm = norm(tfield.get("caption"))
    # Tableau captions often contain display units, e.g. "Capacity (Mb/s)", while
    # Power BI's model property is simply "Capacity". Compare the full caption first,
    # then allow the PBIR property to be a complete token subset of the caption.
    for pf in pfields:
        prop_tokens = tokens(pf.get("property"))
        prop_norm = norm(pf.get("property"))
        if target == prop_tokens or caption_norm == prop_norm:
            return True
        if prop_tokens and prop_tokens.issubset(target):
            return True
        overlap = target & prop_tokens
        if overlap and len(overlap) >= max(1, min(2, len(prop_tokens))):
            return True
    return False


def title_candidates(ws: dict[str, Any]) -> list[str]:
    return [x for x in (ws.get("title_text"), ws.get("name")) if isinstance(x, str) and x.strip()]


def score_match(ws: dict[str, Any], pbi: dict[str, Any], catalog: dict[str, dict[str, Any]]) -> tuple[int, list[str]]:
    score = 0
    reasons: list[str] = []
    pbi_titles = [pbi.get("title"), pbi.get("id")]
    wt = [norm(x) for x in title_candidates(ws)]
    for t in wt:
        if not t:
            continue
        if t in {norm(x) for x in pbi_titles if x}:
            score += 70
            reasons.append("exact title/name")
            break
        if t and any(t in norm(x) or norm(x) in t for x in pbi_titles if x):
            score += 35
            reasons.append("partial title/name")
            break

    page = norm(pbi.get("page_name"))
    dash_names = {norm(d.get("name")) for d in ws.get("_dashboard_names", []) if isinstance(d, dict)}
    if page and dash_names and any(page == x or page in x or x in page for x in dash_names if x):
        score += 15
        reasons.append("page/dashboard context")

    tfields = tableau_visual_fields(ws, catalog)
    matched = sum(field_matches(tf, pbi.get("fields", [])) for tf in tfields)
    if tfields:
        ratio = matched / len(tfields)
        score += int(40 * ratio)
        if ratio >= 0.75:
            reasons.append(f"field overlap {matched}/{len(tfields)}")
        elif matched:
            reasons.append(f"partial field overlap {matched}/{len(tfields)}")

    if type_compatible_for_visual(ws, pbi, catalog):
        score += 15
        reasons.append("compatible visual type")
    else:
        score -= 20
        reasons.append("visual type mismatch")
    return score, reasons


def best_matches(spec: dict[str, Any], report: dict[str, Any]) -> list[dict[str, Any]]:
    catalog = tableau_field_catalog(spec)
    dashboards = spec.get("dashboards", [])
    all_pbi = [v for p in report.get("pages", []) for v in p.get("visuals", [])]
    used: set[str] = set()
    results = []
    for ws in spec.get("worksheets", []):
        if not isinstance(ws, dict):
            continue
        ws = dict(ws)
        ws["_dashboard_names"] = dashboards
        candidates = []
        for pbi in all_pbi:
            if pbi.get("id") in used:
                continue
            score, reasons = score_match(ws, pbi, catalog)
            candidates.append((score, pbi, reasons))
        candidates.sort(key=lambda x: (-x[0], str(x[1].get("id"))))
        if candidates and candidates[0][0] >= 30:
            score, pbi, reasons = candidates[0]
            used.add(pbi["id"])
            results.append({"tableau": ws, "powerbi": pbi, "match_score": score, "match_reasons": reasons})
        else:
            results.append({"tableau": ws, "powerbi": None, "match_score": 0, "match_reasons": []})
    return results


def compare_visual(item: dict[str, Any], catalog: dict[str, dict[str, Any]]) -> dict[str, Any]:
    ws = item["tableau"]
    pbi = item["powerbi"]
    findings: list[dict[str, Any]] = []
    def add(status: str, check: str, expected: Any, actual: Any, detail: str) -> None:
        findings.append({"status": status, "check": check, "expected": expected, "actual": actual, "detail": detail})

    if pbi is None:
        add("FAIL", "visual_exists", True, False, "No Power BI visual could be deterministically matched to this Tableau worksheet.")
        return {"tableau_worksheet": ws.get("name"), "powerbi_visual": None, "status": "FAIL", "findings": findings}

    if type_compatible_for_visual(ws, pbi, catalog):
        add("PASS", "visual_type", ws.get("mark_type"), pbi.get("visual_type"), "Tableau mark type is compatible with the Power BI visual type.")
    else:
        add("FAIL", "visual_type", ws.get("mark_type"), pbi.get("visual_type"), "Visual type is not in the deterministic compatibility map.")

    tfields = tableau_visual_fields(ws, catalog)
    missing = [f["caption"] for f in tfields if not field_matches(f, pbi.get("fields", []))]
    if not missing:
        add("PASS", "field_bindings", [f["caption"] for f in tfields], [f.get("property") for f in pbi.get("fields", [])], "All resolvable Tableau encoding fields were found in the Power BI visual query.")
    else:
        add("FAIL", "field_bindings", [f["caption"] for f in tfields], [f.get("property") for f in pbi.get("fields", [])], f"Missing Tableau fields in Power BI query: {', '.join(missing)}")

    tfilters = tableau_filter_fields(ws, catalog)
    pfilter_text = json.dumps(pbi.get("query", {}), ensure_ascii=False) if pbi.get("query") else json.dumps(pbi.get("fields", []), ensure_ascii=False)
    filter_missing = [f["caption"] for f in tfilters if norm(f["caption"]) not in norm(pfilter_text)]
    if not filter_missing:
        add("PASS", "filters", [f["caption"] for f in tfilters], "query", "Resolvable Tableau filter fields are represented in the Power BI query.")
    elif tfilters:
        add("WARN", "filters", [f["caption"] for f in tfilters], "query", f"Could not prove these Tableau filter fields from the normalized PBIR projection inventory: {', '.join(filter_missing)}")

    ttitle = ws.get("title_text")
    ptitle = pbi.get("title")
    if ttitle and ptitle:
        if norm(ttitle) == norm(ptitle):
            add("PASS", "title", ttitle, ptitle, "Titles match after whitespace/case normalization.")
        else:
            add("WARN", "title", ttitle, ptitle, "Both visuals have titles, but the title text differs.")
    elif ttitle and not ptitle:
        add("WARN", "title", ttitle, None, "Tableau has title text but Power BI has no readable title property.")

    # Position is advisory because Tableau tiled layouts and PBIR absolute positions are not equivalent.
    if pbi.get("position") and all(v is not None for v in pbi["position"].values()):
        add("PASS", "position_available", "layout represented", pbi["position"], "Power BI position is available for render/layout validation.")
    else:
        add("WARN", "position_available", "layout represented", pbi.get("position"), "Power BI visual has no complete numeric position box.")

    status = "FAIL" if any(f["status"] == "FAIL" for f in findings) else ("WARN" if any(f["status"] == "WARN" for f in findings) else "PASS")
    return {
        "tableau_worksheet": ws.get("name"),
        "tableau_worksheet_id": ws.get("id"),
        "powerbi_visual": pbi.get("id"),
        "powerbi_page": pbi.get("page_name"),
        "powerbi_visual_type": pbi.get("visual_type"),
        "match_score": item["match_score"],
        "match_reasons": item["match_reasons"],
        "status": status,
        "findings": findings,
    }


def validate(spec_path: Path, report_dir: Path) -> dict[str, Any]:
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    report = extract_report(report_dir)
    catalog = tableau_field_catalog(spec)
    matched = best_matches(spec, report)
    visuals = [compare_visual(x, catalog) for x in matched]
    matched_ids = {x["powerbi_visual"] for x in visuals if x.get("powerbi_visual")}
    all_pbi = [v for p in report["pages"] for v in p["visuals"]]
    unexpected = [
        {"powerbi_visual": v["id"], "page": v["page_name"], "type": v["visual_type"], "title": v.get("title")}
        for v in all_pbi if v["id"] not in matched_ids
    ]
    counts = defaultdict(int)
    for v in visuals:
        counts[v["status"]] += 1
    overall = "FAIL" if counts["FAIL"] or unexpected else ("WARN" if counts["WARN"] else "PASS")
    return {
        "schema_version": "1.0",
        "status": overall,
        "tableau_workbook": spec.get("source", {}).get("workbook_name"),
        "powerbi_report": report["report"],
        "tableau_visuals": len(spec.get("worksheets", [])),
        "powerbi_visuals": report["visual_count"],
        "matched_visuals": sum(1 for x in visuals if x.get("powerbi_visual")),
        "unmatched_tableau_visuals": sum(1 for x in visuals if not x.get("powerbi_visual")),
        "unexpected_powerbi_visuals": len(unexpected),
        "pass": counts["PASS"],
        "warn": counts["WARN"],
        "fail": counts["FAIL"],
        "visuals": visuals,
        "unexpected_powerbi_visuals_detail": unexpected,
    }


def render(result: dict[str, Any]) -> str:
    lines = [
        "TABLEAU -> POWER BI VISUAL VALIDATION",
        f"Status: {result['status']}",
        f"Tableau visuals: {result['tableau_visuals']}",
        f"Power BI visuals: {result['powerbi_visuals']}",
        f"Matched: {result['matched_visuals']}",
        f"PASS: {result['pass']} | WARN: {result['warn']} | FAIL: {result['fail']}",
        f"Unexpected Power BI visuals: {result['unexpected_powerbi_visuals']}",
        "",
    ]
    for visual in result["visuals"]:
        lines.append(f"[{visual['status']}] {visual['tableau_worksheet']} -> {visual.get('powerbi_visual') or 'NOT MATCHED'}")
        if visual.get("powerbi_page"):
            lines.append(f"    page: {visual['powerbi_page']} | type: {visual.get('powerbi_visual_type')} | match: {visual.get('match_score')}")
        for finding in visual["findings"]:
            lines.append(f"    {finding['status']} {finding['check']}: {finding['detail']}")
    if result["unexpected_powerbi_visuals"]:
        lines.append("\nUnexpected Power BI visuals:")
        for v in result["unexpected_powerbi_visuals_detail"]:
            lines.append(f"    - {v['powerbi_visual']}: {v['page']} / {v.get('title') or v['type']}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("migration_spec", type=Path)
    parser.add_argument("report", type=Path)
    parser.add_argument("-o", "--output", type=Path, required=True)
    parser.add_argument("--text-output", type=Path)
    parser.add_argument("--warn-only", action="store_true")
    args = parser.parse_args()
    result = validate(args.migration_spec.resolve(), args.report.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    text = render(result)
    if args.text_output:
        args.text_output.parent.mkdir(parents=True, exist_ok=True)
        args.text_output.write_text(text + "\n", encoding="utf-8")
    print(text)
    if result["status"] == "FAIL" and not args.warn_only:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
