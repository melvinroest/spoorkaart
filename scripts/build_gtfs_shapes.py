#!/usr/bin/env python3
"""Real track geometry per serie route from GTFS shapes.txt.

For every route in data/gtfs/pageN.series.json, pick the trip with the best
stop coverage, take its shape, downsample it (Douglas-Peucker), and write
data/gtfs/pageN.shapes.json with route arrays index-aligned with the series
files. Routes whose stations end up too far from their polyline (or without
a usable shape) get null; the app falls back to straight chords there.

Built-in truth anchor: every stop of a route must lie within ANCHOR_MAX_M of
the emitted polyline, otherwise that route is rejected to null and reported.
Stations sit on the track, so a polyline that fails this is the wrong shape.

Trip selection and window classification mirror build_gtfs_series.py.

Usage:
    uv run scripts/build_gtfs_shapes.py /path/to/gtfs-nl.zip
"""

import json
import math
import sys
import zipfile
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from build_gtfs_series import (
    DAY_FRACTION,
    MIN_SERVICE_DATES,
    SERIE_RE,
    TIME_WINDOWS,
    day_class,
    read_csv,
)

ROOT = Path(__file__).resolve().parent.parent
STATIONS = ROOT / "data" / "stations.json"
GTFS_DIR = ROOT / "data" / "gtfs"

SIMPLIFY_TOL_M = 25.0   # Douglas-Peucker tolerance; rail curves stay smooth
ANCHOR_MAX_M = 500.0    # every route stop must lie this close to its polyline

# Equirectangular projection around NL latitude, good enough for tolerances.
M_PER_DEG_LAT = 111320.0
M_PER_DEG_LON = 111320.0 * math.cos(math.radians(52.0))


def to_xy(lat, lon):
    return (lon * M_PER_DEG_LON, lat * M_PER_DEG_LAT)


def seg_dist_m(p, a, b):
    px, py = p
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    l2 = dx * dx + dy * dy
    if l2 == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / l2))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def douglas_peucker(pts_xy, tol):
    if len(pts_xy) < 3:
        return list(range(len(pts_xy)))
    keep = [False] * len(pts_xy)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts_xy) - 1)]
    while stack:
        a, b = stack.pop()
        if b - a < 2:
            continue
        best_d, best_i = -1.0, None
        pa, pb = pts_xy[a], pts_xy[b]
        for i in range(a + 1, b):
            d = seg_dist_m(pts_xy[i], pa, pb)
            if d > best_d:
                best_d, best_i = d, i
        if best_d > tol:
            keep[best_i] = True
            stack.append((a, best_i))
            stack.append((best_i, b))
    return [i for i, k in enumerate(keep) if k]


def main():
    if len(sys.argv) != 2:
        print("usage: build_gtfs_shapes.py <gtfs-nl.zip>")
        sys.exit(2)
    zf = zipfile.ZipFile(sys.argv[1])

    station_geo = {}
    for st in json.loads(STATIONS.read_text())["stations"]:
        if "geo" in st:
            station_geo[st["id"]] = tuple(st["geo"])
    by_code = {}
    for st in json.loads(STATIONS.read_text())["stations"]:
        if "code" in st:
            by_code[st["code"]] = st["id"]

    rows = read_csv(zf, "routes.txt")
    header = {c: i for i, c in enumerate(next(rows))}
    route_serie = {}
    for r in rows:
        if not r[header["agency_id"]].startswith("IFF:") or r[header["route_type"]] != "2":
            continue
        m = SERIE_RE.search(r[header["route_long_name"]])
        if m:
            route_serie[r[header["route_id"]]] = m.group(1)

    rows = read_csv(zf, "trips.txt")
    header = {c: i for i, c in enumerate(next(rows))}
    trips = {}
    for r in rows:
        rid = r[header["route_id"]]
        if rid in route_serie:
            trips[r[header["trip_id"]]] = (
                rid,
                r[header["service_id"]],
                r[header["direction_id"]],
                r[header["shape_id"]],
            )

    rows = read_csv(zf, "calendar_dates.txt")
    header = {c: i for i, c in enumerate(next(rows))}
    service_days = defaultdict(lambda: defaultdict(int))
    for r in rows:
        service_days[r[header["service_id"]]][day_class(r[header["date"]])] += 1

    rows = read_csv(zf, "stops.txt")
    header = {c: i for i, c in enumerate(next(rows))}
    stop_station = {}
    for r in rows:
        zone = r[header["zone_id"]]
        if zone.startswith("IFF:"):
            sid = by_code.get(zone[4:].lower())
            if sid:
                stop_station[r[header["stop_id"]]] = sid

    per_trip = defaultdict(list)
    rows = read_csv(zf, "stop_times.txt")
    header = {c: i for i, c in enumerate(next(rows))}
    i_trip, i_seq, i_stop, i_dep = (
        header["trip_id"],
        header["stop_sequence"],
        header["stop_id"],
        header["departure_time"],
    )
    for r in rows:
        tid = r[i_trip]
        if tid not in trips:
            continue
        station = stop_station.get(r[i_stop])
        if station is None:
            continue
        try:
            dep = int(r[i_dep].split(":")[0]) * 60 + int(r[i_dep].split(":")[1])
        except (ValueError, IndexError):
            continue
        per_trip[tid].append((int(r[i_seq]), station, dep))

    window_trips = defaultdict(list)
    for tid, (rid, sid, _d, _sh) in trips.items():
        days = service_days.get(sid)
        stops = per_trip.get(tid)
        if not days or not stops:
            continue
        total = sum(days.values())
        if total < MIN_SERVICE_DATES:
            continue
        stops.sort()
        serie = route_serie[rid]
        if stops[0][2] >= 20 * 60:
            window_trips[(4, serie)].append(tid)
            continue
        if days["madot"] / total >= DAY_FRACTION:
            window_trips[(1, serie)].append(tid)
        if days["vr"] / total >= DAY_FRACTION:
            window_trips[(2, serie)].append(tid)
        if days["weekend"] / total >= DAY_FRACTION:
            window_trips[(3, serie)].append(tid)

    # First pass over pages: rank candidate trips (and so shapes) per route.
    # The anchor check later walks this ranking until a shape passes, so a
    # trip on a diversion variant cannot poison a route.
    candidates = defaultdict(list)  # (page, serie, route_idx) -> [(cov, dir0, shape)]
    needed_shapes = set()
    page_docs = {}
    for page in (1, 2, 3, 4):
        doc = json.loads((GTFS_DIR / f"page{page}.series.json").read_text())
        page_docs[page] = doc
        for entry in doc["series"]:
            serie = entry["id"]
            tids = window_trips.get((page, serie), [])
            if not tids:
                continue
            route_sets = [set(r["stops"]) for r in entry["routes"]]
            for tid in tids:
                stset = {st for _s, st, _d in per_trip[tid]}
                shape = trips[tid][3]
                if not shape:
                    continue
                for k, rs in enumerate(route_sets):
                    if stset <= rs:
                        cov = len(stset)
                        dir0 = trips[tid][2] != "1"
                        candidates[(page, serie, k)].append((cov, dir0, shape))
                        break
    for key, cands in candidates.items():
        cands.sort(reverse=True)
        # Keep the ranking but only distinct shapes, capped to a handful.
        seen = set()
        distinct = []
        for cov, d0, shape in cands:
            if shape in seen:
                continue
            seen.add(shape)
            distinct.append((cov, d0, shape))
            if len(distinct) == 5:
                break
        candidates[key] = distinct
        for _c, _d, shape in distinct:
            needed_shapes.add(shape)

    # Stream shapes.txt once, keeping only the shapes we chose.
    shape_pts = defaultdict(list)
    rows = read_csv(zf, "shapes.txt")
    header = {c: i for i, c in enumerate(next(rows))}
    i_id, i_seq2 = header["shape_id"], header["shape_pt_sequence"]
    i_lat, i_lon = header["shape_pt_lat"], header["shape_pt_lon"]
    for r in rows:
        sid = r[i_id]
        if sid in needed_shapes:
            shape_pts[sid].append((int(r[i_seq2]), float(r[i_lat]), float(r[i_lon])))

    total_kept = 0
    total_raw = 0
    anchor_fails = []
    for page in (1, 2, 3, 4):
        doc = page_docs[page]
        out_series = {}
        for entry in doc["series"]:
            serie = entry["id"]
            routes_out = []
            any_shape = False
            for k, route in enumerate(entry["routes"]):
                stops_xy = [
                    to_xy(*station_geo[st])
                    for st in route["stops"]
                    if st in station_geo
                ]
                result = None
                worst_seen = None
                for _cov, _d0, shape_id in candidates.get((page, serie, k), []):
                    raw = sorted(shape_pts.get(shape_id, []))
                    if len(raw) < 2:
                        continue
                    latlon = [(lat, lon) for _s, lat, lon in raw]
                    xy = [to_xy(lat, lon) for lat, lon in latlon]
                    # Truth anchor on the raw shape: every stop must sit near
                    # the line, otherwise try the next-ranked shape.
                    worst = 0.0
                    for p in stops_xy:
                        d = min(
                            seg_dist_m(p, xy[i], xy[i + 1])
                            for i in range(len(xy) - 1)
                        )
                        worst = max(worst, d)
                    if worst_seen is None or worst < worst_seen:
                        worst_seen = worst
                    if worst > ANCHOR_MAX_M:
                        continue
                    idxs = douglas_peucker(xy, SIMPLIFY_TOL_M)
                    total_raw += len(latlon)
                    total_kept += len(idxs)
                    result = [
                        [round(latlon[i][0], 5), round(latlon[i][1], 5)] for i in idxs
                    ]
                    break
                if result is None and worst_seen is not None:
                    anchor_fails.append(
                        f"page{page} {serie} route {k}: best {worst_seen:.0f} m"
                    )
                routes_out.append(result)
                if result is not None:
                    any_shape = True
            if any_shape:
                out_series[serie] = {"routes": routes_out}
        out = {
            "schemaVersion": 1,
            "page": page,
            "timeWindow": TIME_WINDOWS[page],
            "series": out_series,
            "notes": [
                "Spoorgeometrie per route uit GTFS shapes.txt (best dekkende rit), "
                f"Douglas-Peucker {SIMPLIFY_TOL_M:.0f} m, index-gelijk aan de routes "
                f"in page{page}.series.json; null = geen bruikbare shape.",
                f"Waarheidsanker: elk station ligt binnen {ANCHOR_MAX_M:.0f} m van "
                "zijn polylijn, anders is de route verworpen.",
            ],
        }
        path = GTFS_DIR / f"page{page}.shapes.json"
        path.write_text(json.dumps(out, ensure_ascii=False) + "\n")
        n_routes = sum(
            1 for s in out_series.values() for r in s["routes"] if r is not None
        )
        n_total = sum(len(e["routes"]) for e in doc["series"])
        print(
            f"OK page {page}: {n_routes}/{n_total} routes with track geometry, "
            f"{path.stat().st_size // 1024} KiB"
        )
    if total_raw:
        print(
            f"downsampling: {total_raw} -> {total_kept} points "
            f"({100 * total_kept / total_raw:.0f}% kept)"
        )
    if anchor_fails:
        print(f"anchor rejects ({len(anchor_fails)}):")
        for f in anchor_fails[:12]:
            print(f"  {f}")


if __name__ == "__main__":
    main()
