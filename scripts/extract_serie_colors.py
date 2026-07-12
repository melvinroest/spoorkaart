#!/usr/bin/env python3
"""Extract the line color per treinserie from the map artwork.

Primary method: a series label sits on its own line, so the serie's color is
the stroke color of the drawn path nearest to the label (segment distance,
majority vote across all occurrences on all four pages). Fallback: the fill
color of the badge rectangle behind the label. The fallback alone is not
enough because several badges are printed in a darker shade than their line.

Tokens are restricted to serie ids that actually occur in the series files,
so footnote numbers and speed markers (140/240) cannot pollute the output.

Usage:
    uv run --with pymupdf scripts/extract_serie_colors.py
"""

import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path

import fitz

ROOT = Path(__file__).resolve().parent.parent
PDF = ROOT / "spoorkaart2026.pdf"
OUT = ROOT / "data" / "serie-colors.json"

SERIE_RE = re.compile(r"^([0-9]{3,6}(?:/[0-9]{3,6})?|R[SEB][0-9]{1,3})$")
LINE_TOL = 8.0      # pt max distance from label center to its line
WIDTH_MIN = 1.0
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


def path_segments(items):
    segs = []
    for it in items:
        if it[0] == "l":
            segs.append(((it[1].x, it[1].y), (it[2].x, it[2].y)))
        elif it[0] == "c":
            segs.append(((it[1].x, it[1].y), (it[4].x, it[4].y)))
    return segs


def known_ids():
    ids = set()
    for pattern in ("gtfs/page*.series.json", "page*.series.json"):
        for p in (ROOT / "data").glob(pattern):
            for s in json.loads(p.read_text())["series"]:
                ids.add(s["id"])
                for part in s["id"].split("/"):
                    ids.add(part)
    return ids


def main():
    ids = known_ids()
    doc = fitz.open(PDF)
    line_votes = defaultdict(Counter)
    badge_votes = defaultdict(Counter)

    for page in doc:
        strokes = []
        fills = []
        for d in page.get_drawings():
            color = d.get("color")
            width = d.get("width") or 0
            if color is not None and WIDTH_MIN <= width <= WIDTH_MAX:
                segs = path_segments(d["items"])
                if segs:
                    strokes.append((segs, to_hex(color)))
            fill = d.get("fill")
            if fill is not None:
                r = d["rect"]
                if 4 < r.width < 90 and 4 < r.height < 90:
                    fills.append((r, to_hex(fill)))

        for x0, y0, x1, y1, word, *_ in page.get_text("words"):
            m = SERIE_RE.match(word.strip(".,"))
            if not m:
                continue
            token = m.group(1)
            parts = [p for p in token.split("/") if p in ids]
            if not parts:
                continue
            cx, cy = (x0 + x1) / 2, (y0 + y1) / 2

            best_d, best_c = LINE_TOL + 1, None
            for segs, colorhex in strokes:
                for a, b in segs:
                    dd = seg_dist((cx, cy), a, b)
                    if dd < best_d:
                        best_d, best_c = dd, colorhex
            if best_c is not None and best_d <= LINE_TOL:
                for serie in parts:
                    line_votes[serie][best_c] += 1

            containing = [
                (r.get_area(), c)
                for r, c in fills
                if r.x0 <= cx <= r.x1 and r.y0 <= cy <= r.y1
            ]
            if containing:
                _, c = min(containing)
                if c != "#ffffff":
                    for serie in parts:
                        badge_votes[serie][c] += 1

    colors = {}
    for serie in sorted(ids):
        if line_votes.get(serie):
            colors[serie] = line_votes[serie].most_common(1)[0][0]
        elif badge_votes.get(serie):
            colors[serie] = badge_votes[serie].most_common(1)[0][0]
    OUT.write_text(json.dumps(colors, indent=1) + "\n")

    line_n = sum(1 for s in colors if line_votes.get(s))
    print(f"OK {len(colors)} serie colors ({line_n} from line stroke, "
          f"{len(colors) - line_n} from badge fill) -> {OUT}")
    for s in ("31300", "4900", "5600", "5700", "3000", "300", "900", "16900"):
        print(f"  {s}: {colors.get(s, 'absent')}")


if __name__ == "__main__":
    main()
