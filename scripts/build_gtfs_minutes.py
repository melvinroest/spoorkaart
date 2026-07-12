#!/usr/bin/env python3
"""Cumulative travel minutes plus headway per serie per window, from GTFS.

Reads the EXISTING data/gtfs/pageN.series.json files and computes, for each
route's stop array, cumulative median minutes along the stops, plus one
median headway per serie per window. Output: data/gtfs/pageN.minutes.json,
with route arrays aligned index for index with the series file stop arrays.
The series files are never rewritten; alignment holds by construction.

Trip selection and window classification mirror build_gtfs_series.py; the
shared constants and helpers are imported from that module so the two
cannot drift apart silently.

Usage:
    uv run scripts/build_gtfs_minutes.py /path/to/gtfs-nl.zip
"""

import json
import statistics
import sys
import zipfile
from collections import Counter, defaultdict
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

DAY_OF_WINDOW = {1: "madot", 2: "vr", 3: "weekend"}
MIN_PAIR_MINUTES = 0.5  # floor for span-derived estimates that noise pushes to 0


def parse_min(hms):
    try:
        h, m, s = hms.split(":")
        return int(h) * 60 + int(m) + int(s) / 60
    except (ValueError, AttributeError):
        return None


def main():
    if len(sys.argv) != 2:
        print("usage: build_gtfs_minutes.py <gtfs-nl.zip>")
        sys.exit(2)
    zf = zipfile.ZipFile(sys.argv[1])

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
            )
    rail_sids = {sid for _rid, sid, _d in trips.values()}

    rows = read_csv(zf, "calendar_dates.txt")
    header = {c: i for i, c in enumerate(next(rows))}
    service_days = defaultdict(lambda: defaultdict(int))
    service_dates = defaultdict(set)
    date_services = Counter()
    for r in rows:
        sid = r[header["service_id"]]
        if sid not in rail_sids:
            continue
        d = r[header["date"]]
        service_days[sid][day_class(d)] += 1
        service_dates[sid].add(d)
        date_services[d] += 1
    # Representative date per day class: the date with the most active rail
    # services, so headways are read off a normal, well-covered day.
    rep_date = {}
    for d, n in date_services.items():
        dc = day_class(d)
        if dc not in rep_date or n > date_services[rep_date[dc]]:
            rep_date[dc] = d
    rep_date["all"] = max(date_services, key=date_services.get)

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
    i_trip, i_seq = header["trip_id"], header["stop_sequence"]
    i_stop, i_arr, i_dep = header["stop_id"], header["arrival_time"], header["departure_time"]
    for r in rows:
        tid = r[i_trip]
        if tid not in trips:
            continue
        station = stop_station.get(r[i_stop])
        arr = parse_min(r[i_arr])
        dep = parse_min(r[i_dep])
        if station is None or dep is None:
            continue
        per_trip[tid].append((int(r[i_seq]), station, arr if arr is not None else dep, dep))

    # Window classification, mirroring build_gtfs_series.py.
    window_trips = defaultdict(list)
    for tid, (rid, sid, _d) in trips.items():
        days = service_days.get(sid)
        stops = per_trip.get(tid)
        if not days or not stops:
            continue
        total = sum(days.values())
        if total < MIN_SERVICE_DATES:
            continue
        stops.sort()
        serie = route_serie[rid]
        if stops[0][3] >= 20 * 60:
            window_trips[(4, serie)].append(tid)
            continue
        if days["madot"] / total >= DAY_FRACTION:
            window_trips[(1, serie)].append(tid)
        if days["vr"] / total >= DAY_FRACTION:
            window_trips[(2, serie)].append(tid)
        if days["weekend"] / total >= DAY_FRACTION:
            window_trips[(3, serie)].append(tid)

    for page in (1, 2, 3, 4):
        series_path = GTFS_DIR / f"page{page}.series.json"
        doc = json.loads(series_path.read_text())
        out_series = {}
        missing_series = []
        unresolved_pairs = 0
        for entry in doc["series"]:
            serie = entry["id"]
            tids = window_trips.get((page, serie), [])
            if not tids:
                missing_series.append(serie)
                continue
            route_stop_sets = [set(r["stops"]) for r in entry["routes"]]
            route_samples = [defaultdict(list) for _ in entry["routes"]]
            route_dwells = [defaultdict(list) for _ in entry["routes"]]
            for tid in tids:
                stations = [(st, arr, dep) for _seq, st, arr, dep in per_trip[tid]]
                stset = {st for st, _a, _d in stations}
                target = None
                for k, rs in enumerate(route_stop_sets):
                    if stset <= rs:
                        target = k
                        break
                if target is None:
                    continue
                pos = {s: i for i, s in enumerate(entry["routes"][target]["stops"])}
                for (u, _au, du), (v, av, _dv) in zip(stations, stations[1:]):
                    # Travel = departure at u to arrival at v, dwell excluded.
                    delta = av - du
                    iu, iv = pos[u], pos[v]
                    if delta < 0 or iu == iv:
                        continue
                    route_samples[target][(min(iu, iv), max(iu, iv))].append(delta)
                for st, arr, dep in stations:
                    dwell = dep - arr
                    if 0 <= dwell <= 30:
                        route_dwells[target][pos[st]].append(dwell)
            route_cums = []
            for k, route in enumerate(entry["routes"]):
                n = len(route["stops"])
                samples = route_samples[k]
                dwell_med = {
                    i: statistics.median(v) for i, v in route_dwells[k].items()
                }
                pair_med = {}
                for (a, b), vals in samples.items():
                    if b - a == 1:
                        pair_med[a] = statistics.median(vals)
                # Fill missing adjacent pairs from the smallest span whose
                # other internal pairs are already known. A span (a, b) is
                # dep(a) to arr(b), so interior dwells are part of it.
                changed = True
                while changed:
                    changed = False
                    for i in range(n - 1):
                        if i in pair_med:
                            continue
                        best = None
                        for (a, b), vals in samples.items():
                            if a <= i < b and all(
                                j in pair_med for j in range(a, b) if j != i
                            ):
                                if best is None or b - a < best[1] - best[0]:
                                    best = (a, b)
                        if best:
                            a, b = best
                            rest = sum(pair_med[j] for j in range(a, b) if j != i)
                            rest += sum(dwell_med.get(j, 0) for j in range(a + 1, b))
                            est = statistics.median(samples[(a, b)]) - rest
                            pair_med[i] = max(est, MIN_PAIR_MINUTES)
                            changed = True
                # Two clocks from departure at stop 0: arrival time and
                # departure time per stop, so minutes(a, b) = arr[b] - dep[a]
                # is exact for any stop pair, dwell at a and b excluded.
                arr_cum = [0.0]
                dep_cum = [0.0]
                broken = False
                for i in range(n - 1):
                    if broken or i not in pair_med:
                        broken = True
                        unresolved_pairs += 1
                        arr_cum.append(None)
                        dep_cum.append(None)
                    else:
                        a = dep_cum[i] + pair_med[i]
                        arr_cum.append(round(a, 1))
                        dep_cum.append(round(a + dwell_med.get(i + 1, 0), 1))
                route_cums.append({"arr": arr_cum, "dep": dep_cum})
            dir0 = [t for t in tids if trips[t][2] != "1"] or tids
            counts = Counter(st for t in dir0 for _s, st, _a, _d in per_trip[t])
            headway = None
            if counts:
                ref = counts.most_common(1)[0][0]
                date = rep_date.get(DAY_OF_WINDOW.get(page, "all"), rep_date["all"])
                deps = sorted(
                    dep
                    for t in dir0
                    if date in service_dates[trips[t][1]]
                    for _s, st, _a, dep in per_trip[t]
                    if st == ref
                )
                gaps = [b - a for a, b in zip(deps, deps[1:]) if b - a > 0]
                if gaps:
                    headway = round(statistics.median(gaps), 1)
            out_series[serie] = {"headwayMinutes": headway, "routes": route_cums}
        out = {
            "schemaVersion": 1,
            "page": page,
            "timeWindow": TIME_WINDOWS[page],
            "series": out_series,
            "notes": [
                "Cumulatieve mediane minuten per route, index-gelijk aan de stops-arrays "
                f"in page{page}.series.json.",
                "headwayMinutes: mediane tijd tussen vertrekken (richting 0) op het "
                "drukst bediende station op een representatieve dag.",
            ],
        }
        path = GTFS_DIR / f"page{page}.minutes.json"
        path.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
        msg = f"OK page {page}: {len(out_series)}/{len(doc['series'])} series with minutes"
        if missing_series:
            msg += f"; no trips for: {', '.join(missing_series[:8])}"
        if unresolved_pairs:
            msg += f"; unresolved stop pairs: {unresolved_pairs}"
        print(msg)

    # Spot checks against known real-world times.
    doc = json.loads((GTFS_DIR / "page1.minutes.json").read_text())
    sdoc = json.loads((GTFS_DIR / "page1.series.json").read_text())
    for serie, a, b in (("3000", "utrecht-centraal", "arnhem-centraal"),
                        ("4000", "rotterdam-centraal", "uitgeest")):
        entry = next((s for s in sdoc["series"] if s["id"] == serie), None)
        mins = doc["series"].get(serie)
        if not entry or not mins:
            continue
        for route, cum in zip(entry["routes"], mins["routes"]):
            stops = route["stops"]
            if a in stops and b in stops:
                ia, ib = stops.index(a), stops.index(b)
                lo, hi = min(ia, ib), max(ia, ib)
                if cum["dep"][lo] is not None and cum["arr"][hi] is not None:
                    print(f"  spot {serie} {a} -> {b}: "
                          f"{cum['arr'][hi] - cum['dep'][lo]:.0f} min, "
                          f"headway {mins['headwayMinutes']}")
                break


if __name__ == "__main__":
    main()
