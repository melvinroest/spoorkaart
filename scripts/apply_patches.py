#!/usr/bin/env python3
"""Apply verdict patches to the map series files, in array order.

Semantics follow the patch file's applyNote: afterStation refers to the stop
order at application time, START means first, add_stop also removes the
station from via, rename happens in place, add_route creates the serie entry
from meta when it does not exist yet.

Usage:
    uv run scripts/apply_patches.py
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PATCHES = ROOT / "data" / "patches" / "verdict-patches.json"


def find(doc, sid):
    for s in doc["series"]:
        if s["id"] == sid:
            return s
    return None


def main():
    pdoc = json.loads(PATCHES.read_text())
    docs = {
        n: json.loads((ROOT / f"data/page{n}.series.json").read_text())
        for n in (1, 2, 3, 4)
    }
    counts = {}
    for p in pdoc["patches"]:
        doc = docs[p["page"]]
        op = p["op"]
        s = find(doc, p["serie"])
        if op == "add_route" and s is None:
            s = {"id": p["serie"], **p["meta"], "routes": []}
            doc["series"].append(s)
        if s is None:
            raise SystemExit(f"FAIL: serie {p['serie']} not found on page {p['page']}")
        if op == "rename_serie":
            if find(doc, p["newId"]) is not None:
                raise SystemExit(f"FAIL: rename collision {p['newId']} page {p['page']}")
            s["id"] = p["newId"]
        elif op == "add_stop":
            r = s["routes"][p["routeIndex"]]
            st = p["station"]
            if st in r["stops"]:
                raise SystemExit(f"FAIL: {st} already in {p['serie']} page {p['page']}")
            if p["afterStation"] == "START":
                r["stops"].insert(0, st)
            else:
                r["stops"].insert(r["stops"].index(p["afterStation"]) + 1, st)
            if st in r.get("via", []):
                r["via"].remove(st)
        elif op == "remove_stop":
            s["routes"][p["routeIndex"]]["stops"].remove(p["station"])
        elif op == "replace_route_stops":
            s["routes"][p["routeIndex"]]["stops"] = p["stops"]
        elif op == "remove_route":
            s["routes"].pop(p["routeIndex"])
        elif op == "add_route":
            s["routes"].insert(p["routeIndex"], {"stops": p["stops"]})
        else:
            raise SystemExit(f"FAIL: unknown op {op}")
        counts[op] = counts.get(op, 0) + 1
    stamp = (
        "Verdict patches applied 2026-07-12 from data/patches/verdict-patches.json; "
        "evidence in research/2026-07-12 diff-verdicts.md."
    )
    for n, doc in docs.items():
        doc.setdefault("notes", []).append(stamp)
        (ROOT / f"data/page{n}.series.json").write_text(
            json.dumps(doc, indent=1, ensure_ascii=False) + "\n"
        )
    print("OK applied:", ", ".join(f"{k} {v}" for k, v in sorted(counts.items())))


if __name__ == "__main__":
    main()
