#!/usr/bin/env python3
"""Validate spoorkaart data files against the schemas in schema/ plus referential rules.

Usage:
    uv run --with jsonschema scripts/validate.py data/stations.json
    uv run --with jsonschema scripts/validate.py data/page1.series.json
"""

import json
import sys
from pathlib import Path

import jsonschema

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_DIR = ROOT / "schema"
STATIONS_PATH = ROOT / "data" / "stations.json"

EXPECTED_TIME_WINDOWS = {
    1: "ma-do tot 20 uur",
    2: "vrijdag tot 20 uur",
    3: "weekend tot 20 uur",
    4: "ma-zo na 20 uur",
}


def load(path):
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        print(f"FAIL: file not found: {path}")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"FAIL: invalid JSON in {path}: {e}")
        sys.exit(1)


def schema_errors(doc, schema_name):
    schema = load(SCHEMA_DIR / schema_name)
    validator = jsonschema.Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(doc), key=lambda e: list(e.absolute_path))
    return [
        "schema: {} at /{}".format(e.message, "/".join(str(p) for p in e.absolute_path))
        for e in errors
    ]


def validate_stations(doc):
    errors = schema_errors(doc, "stations.schema.json")
    if errors:
        return errors, ""
    ids = [s["id"] for s in doc["stations"]]
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    if dupes:
        errors.append(f"duplicate station ids: {dupes}")
    return errors, f"{len(ids)} stations"


def validate_series_file(doc, target):
    errors = schema_errors(doc, "series.schema.json")
    if errors:
        return errors, ""
    warnings = []
    page = doc["page"]
    if doc["timeWindow"] != EXPECTED_TIME_WINDOWS[page]:
        errors.append(
            f"timeWindow '{doc['timeWindow']}' does not match page {page} "
            f"('{EXPECTED_TIME_WINDOWS[page]}')"
        )
    if target.name != f"page{page}.series.json":
        warnings.append(f"filename {target.name} does not match page {page}")
    stations_doc = load(STATIONS_PATH)
    known = {s["id"] for s in stations_doc["stations"]}
    seen_series = set()
    for s in doc["series"]:
        sid = s["id"]
        if sid in seen_series:
            errors.append(f"duplicate series id '{sid}'")
        seen_series.add(sid)
        for i, route in enumerate(s["routes"]):
            stops = route["stops"]
            for st in stops:
                if st not in known:
                    errors.append(f"series '{sid}' route {i}: unknown stop '{st}'")
            for a, b in zip(stops, stops[1:]):
                if a == b:
                    errors.append(f"series '{sid}' route {i}: consecutive duplicate stop '{a}'")
            repeats = sorted({st for st in stops if stops.count(st) > 1})
            if repeats:
                warnings.append(f"series '{sid}' route {i}: repeated stops {repeats}")
            for st in route.get("via", []):
                if st not in known:
                    errors.append(f"series '{sid}' route {i}: unknown via '{st}'")
        for e in s.get("exceptions", []):
            st = e.get("station")
            if st is not None and st not in known:
                errors.append(f"series '{sid}' exception: unknown station '{st}'")
    for c in doc.get("corrections", []):
        if c["stationId"] not in known:
            errors.append(f"correction: unknown stationId '{c['stationId']}'")
    for u in doc.get("unknownStations", []):
        for st in u.get("betweenStops", []):
            errors_msg = f"unknownStations '{u['nameAsSeen']}': unknown betweenStops id '{st}'"
            if st not in known:
                errors.append(errors_msg)
    for w in warnings:
        print(f"WARNING: {w}")
    return errors, f"{len(doc['series'])} series, station refs OK"


def main():
    if len(sys.argv) != 2:
        print("usage: validate.py <data/stations.json | data/pageN.series.json>")
        sys.exit(2)
    target = Path(sys.argv[1])
    doc = load(target)
    if target.name == "stations.json":
        errors, summary = validate_stations(doc)
    else:
        errors, summary = validate_series_file(doc, target)
    if errors:
        for e in errors[:80]:
            print(f"FAIL: {e}")
        sys.exit(1)
    print(f"OK {target.name}: {summary}")


if __name__ == "__main__":
    main()
