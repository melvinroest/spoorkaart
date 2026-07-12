#!/usr/bin/env python3
"""Extract the drawn rail-line geometry per treinserie from the PDF artwork.

Idea: every series line is stroked in the color of its series badge (see
extract_serie_colors.py). get_drawings() returns all vector paths with stroke
color, width, dashes, and geometry in PDF points, the coordinate system shared
by the SVG viewBox and stations.json. A path belongs to a serie when its
stroke color matches the serie's badge color AND its points run along the
serie's station corridor (this separates series that share a color but live
in different regions).

Output: data/highlights/pageN.json = {serie: [{"d": svgPath, "w": width,
"dash": dasharray or ""}]}, drawn by the app's overlay at full opacity.

Usage:
    uv run --with pymupdf scripts/extract_highlights.py
"""

import json
import math
import re
from pathlib import Path

import fitz

ROOT = Path(__file__).resolve().parent.parent
PDF = ROOT / "spoorkaart2026.pdf"
OUTDIR = ROOT / "data" / "highlights"

TOL_SEG = 34.0    # pt distance to the chord between consecutive stops
TOL_STOP = 42.0   # pt distance to any stop of the serie
MIN_FRAC = 0.6   # share of a path's points that must sit in the corridor
CHAIN_TOL = 3.5  # pt endpoint distance for the connectivity chaining pass
WIDTH_MIN = 1.0   # rail lines only; station ticks and hairlines fall outside
WIDTH_MAX = 7.0


def to_hex(rgb):
    return "#" + "".join(f"{round(c * 255):02x}" for c in rgb)


def seg_dist(p, a, b):
    ax, ay = a
    bx, by = b
    px, py = p
    dx, dy = bx - ax, by - ay
    l2 = dx * dx + dy * dy
    if l2 == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / l2))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def path_points(items):
    pts = []
    for it in items:
        if it[0] == "l":
            pts.extend([(it[1].x, it[1].y), (it[2].x, it[2].y)])
        elif it[0] == "c":
            pts.extend([(it[1].x, it[1].y), (it[4].x, it[4].y)])
        elif it[0] == "re":
            r = it[1]
            pts.append(((r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2))
        elif it[0] == "qu":
            q = it[1]
            pts.extend([(q.ul.x, q.ul.y), (q.lr.x, q.lr.y)])
    return pts


def path_to_d(items):
    parts = []
    cur = None
    for it in items:
        if it[0] == "l":
            p1, p2 = it[1], it[2]
            if cur is None or (cur.x, cur.y) != (p1.x, p1.y):
                parts.append(f"M {p1.x:.1f} {p1.y:.1f}")
            parts.append(f"L {p2.x:.1f} {p2.y:.1f}")
            cur = p2
        elif it[0] == "c":
            p1, p2, p3, p4 = it[1], it[2], it[3], it[4]
            if cur is None or (cur.x, cur.y) != (p1.x, p1.y):
                parts.append(f"M {p1.x:.1f} {p1.y:.1f}")
            parts.append(
                f"C {p2.x:.1f} {p2.y:.1f} {p3.x:.1f} {p3.y:.1f} {p4.x:.1f} {p4.y:.1f}"
            )
            cur = p4
    return " ".join(parts)


def load_series(page):
    for prefix in ("", "gtfs/"):
        p = ROOT / "data" / f"{prefix}page{page}.series.json"
        if p.exists():
            return json.loads(p.read_text())["series"]
    return []


def main():
    colors = json.loads((ROOT / "data" / "serie-colors.json").read_text())
    stations = {
        s["id"]: s for s in json.loads((ROOT / "data" / "stations.json").read_text())["stations"]
    }
    doc = fitz.open(PDF)
    OUTDIR.mkdir(exist_ok=True)

    serie_word = re.compile(r"^([0-9]{3,6}(?:/[0-9]{3,6})?)$")
    for page_no in (1, 2, 3, 4):
        page = doc[page_no - 1]
        by_color = {}
        all_strokes = []
        for d in page.get_drawings():
            color = d.get("color")
            width = d.get("width") or 0
            if color is None or not (WIDTH_MIN <= width <= WIDTH_MAX):
                continue
            pts = path_points(d["items"])
            if not pts:
                continue
            dash = d.get("dashes") or ""
            if dash in ("[] 0", "[ ] 0"):
                dash = ""
            chex = to_hex(color)
            by_color.setdefault(chex, []).append(
                {"pts": pts, "items": d["items"], "w": width, "dash": dash}
            )
            segs = []
            for it in d["items"]:
                if it[0] == "l":
                    segs.append(((it[1].x, it[1].y), (it[2].x, it[2].y)))
                elif it[0] == "c":
                    segs.append(((it[1].x, it[1].y), (it[4].x, it[4].y)))
            if segs:
                all_strokes.append((segs, chex))

        # Label positions per serie token on this page, for the per-page
        # color fallback (some series are recolored per page).
        label_pos = {}
        for x0, y0, x1, y1, word, *_ in page.get_text("words"):
            m = serie_word.match(word.strip(".,"))
            if m:
                for part in m.group(1).split("/"):
                    label_pos.setdefault(part, []).append(((x0 + x1) / 2, (y0 + y1) / 2))

        def page_local_color(serie):
            votes = {}
            for c in label_pos.get(serie, []):
                best_d, best_c = 8.0, None
                for segs, chex in all_strokes:
                    for a, b in segs:
                        dd = seg_dist(c, a, b)
                        if dd < best_d:
                            best_d, best_c = dd, chex
                if best_c:
                    votes[best_c] = votes.get(best_c, 0) + 1
            return max(votes, key=votes.get) if votes else None

        series = load_series(page_no)
        out = {}
        missing_color = []
        no_paths = []
        for s in series:
            color = colors.get(s["id"])
            if color is None and "/" in s["id"]:
                for part in s["id"].split("/"):
                    color = colors.get(part)
                    if color:
                        break
            if color is None:
                missing_color.append(s["id"])
                continue
            stops = []
            for r in s["routes"]:
                for sid in r["stops"]:
                    c = stations.get(sid, {}).get("coords", {}).get(str(page_no))
                    if c:
                        stops.append(tuple(c))
            if len(stops) < 2:
                no_paths.append(s["id"])
                continue
            segs = list(zip(stops, stops[1:]))
            if not by_color.get(color):
                local = page_local_color(s["id"])
                if local:
                    color = local
            matched = []
            pool = []
            for cand in by_color.get(color, []):
                pts = cand["pts"]
                ok = 0
                for p in pts:
                    near_stop = any(
                        math.hypot(p[0] - q[0], p[1] - q[1]) <= TOL_STOP for q in stops
                    )
                    near_seg = near_stop or any(
                        seg_dist(p, a, b) <= TOL_SEG for a, b in segs
                    )
                    if near_seg:
                        ok += 1
                if ok / len(pts) >= MIN_FRAC:
                    matched.append(cand)
                else:
                    pool.append(cand)
            # Chaining: the strict corridor match seeds the line; same-color
            # paths whose endpoints touch an already-matched path continue it.
            # Fills gaps where the drawn line swings far from the label chords.
            changed = True
            while changed and pool:
                changed = False
                anchor = [p for c in matched for p in c["pts"]]
                keep = []
                for cand in pool:
                    if any(
                        math.hypot(p[0] - q[0], p[1] - q[1]) <= CHAIN_TOL
                        for p in cand["pts"]
                        for q in anchor
                    ):
                        matched.append(cand)
                        changed = True
                    else:
                        keep.append(cand)
                pool = keep
            result = []
            for cand in matched:
                d_str = path_to_d(cand["items"])
                if d_str:
                    result.append(
                        {"d": d_str, "w": round(cand["w"], 2), "dash": cand["dash"]}
                    )
            if result:
                out[s["id"]] = result
            else:
                no_paths.append(s["id"])

        path = OUTDIR / f"page{page_no}.json"
        path.write_text(json.dumps(out, ensure_ascii=False) + "\n")
        total_paths = sum(len(v) for v in out.values())
        print(
            f"OK page {page_no}: {len(out)}/{len(series)} series matched, "
            f"{total_paths} paths"
        )
        if missing_color:
            print(f"  no badge color: {', '.join(missing_color[:10])}")
        if no_paths:
            print(f"  no geometry match: {', '.join(no_paths[:10])}")


if __name__ == "__main__":
    main()
