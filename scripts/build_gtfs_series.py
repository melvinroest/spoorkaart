#!/usr/bin/env python3
"""Derive series -> ordered stops per spoorkaart time window from the OVapi GTFS feed.

Produces data/gtfs/page{1..4}.series.json (same schema as the map extraction,
FORMAT.md) and fills missing code/geo in data/stations.json for stations the
Rijden de Treinen CSV lacks, using GTFS stop names and platform coordinates.

Window model (mirrors the spoorkaart pages):
    1 ma-do tot 20 uur, 2 vrijdag tot 20 uur, 3 weekend tot 20 uur, 4 ma-zo na 20 uur.
A trip belongs to a day class when at least DAY_FRACTION of its service dates
fall in that class; it belongs to window 4 when its origin departure is 20:00
or later (GTFS hours can exceed 24 for after-midnight runs).

Usage:
    uv run scripts/build_gtfs_series.py /path/to/gtfs-nl.zip
"""

import csv
import io
import json
import re
import sys
import unicodedata
import zipfile
from collections import defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIONS = ROOT / "data" / "stations.json"
OUTDIR = ROOT / "data" / "gtfs"

MIN_SERVICE_DATES = 10   # drops ad-hoc 28xxx trains and one-off variants
DAY_FRACTION = 0.15      # share of a trip's dates needed to count for a day class
RARE_STOP_FRACTION = 0.2 # stops served by fewer trips than this get an issue note

TIME_WINDOWS = {
    1: "ma-do tot 20 uur",
    2: "vrijdag tot 20 uur",
    3: "weekend tot 20 uur",
    4: "ma-zo na 20 uur",
}
SPAN_HOURS = {1: 13.0, 2: 13.0, 3: 13.0, 4: 4.5}

SERIE_RE = re.compile(r"([0-9]{3,6})\s*$")

# GTFS station code -> our station id, for stops whose GTFS name does not
# slug-match the vocabulary (e.g. GTFS says plain "Preussen").
GTFS_CODE_ALIASES = {"eprn": "lunen-preussen"}


def slug(name):
    s = name.replace("ß", "ss")
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower().replace("'", "").replace("’", "")
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s


def read_csv(zf, name):
    with zf.open(name) as f:
        yield from csv.reader(io.TextIOWrapper(f, encoding="utf-8-sig"))


def day_class(d):
    wd = date(int(d[:4]), int(d[4:6]), int(d[6:8])).weekday()
    if wd <= 3:
        return "madot"
    if wd == 4:
        return "vr"
    return "weekend"


def main():
    if len(sys.argv) != 2:
        print("usage: build_gtfs_series.py <gtfs-nl.zip>")
        sys.exit(2)
    zf = zipfile.ZipFile(sys.argv[1])

    stations_doc = json.loads(STATIONS.read_text())
    by_code = {}
    by_slug = {}
    for st in stations_doc["stations"]:
        if "code" in st:
            by_code[st["code"]] = st
        by_slug[st["id"]] = st

    # routes: rail only, serie from route_long_name suffix
    rows = read_csv(zf, "routes.txt")
    header = {c: i for i, c in enumerate(next(rows))}
    route_serie = {}
    route_product = {}
    skipped_routes = []
    for r in rows:
        if not r[header["agency_id"]].startswith("IFF:") or r[header["route_type"]] != "2":
            continue
        m = SERIE_RE.search(r[header["route_long_name"]])
        if not m:
            skipped_routes.append(r[header["route_long_name"]] or r[header["route_id"]])
            continue
        rid = r[header["route_id"]]
        route_serie[rid] = m.group(1)
        route_product[rid] = r[header["route_short_name"]]

    # trips
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

    # calendar_dates: service -> day-class counts
    rows = read_csv(zf, "calendar_dates.txt")
    header = {c: i for i, c in enumerate(next(rows))}
    service_days = defaultdict(lambda: defaultdict(int))
    window_dates = defaultdict(set)
    for r in rows:
        dc = day_class(r[header["date"]])
        service_days[r[header["service_id"]]][dc] += 1
        window_dates[dc].add(r[header["date"]])

    # stops: platform -> station code and coordinates
    rows = read_csv(zf, "stops.txt")
    header = {c: i for i, c in enumerate(next(rows))}
    stop_code = {}
    code_name = {}
    code_coords = defaultdict(list)
    for r in rows:
        zone = r[header["zone_id"]]
        if not zone.startswith("IFF:"):
            continue
        code = zone[4:].lower()
        stop_code[r[header["stop_id"]]] = code
        code_name.setdefault(code, r[header["stop_name"]])
        try:
            code_coords[code].append(
                (float(r[header["stop_lat"]]), float(r[header["stop_lon"]]))
            )
        except ValueError:
            pass

    # fill vocabulary gaps (stations the RdT CSV lacks) from GTFS names
    filled = []
    for code, gname in code_name.items():
        if code in by_code:
            continue
        st = by_slug.get(GTFS_CODE_ALIASES.get(code) or slug(gname))
        if st is not None and "code" not in st:
            st["code"] = code
            pts = code_coords[code]
            if pts and "geo" not in st:
                st["geo"] = [
                    round(sum(p[0] for p in pts) / len(pts), 5),
                    round(sum(p[1] for p in pts) / len(pts), 5),
                ]
            by_code[code] = st
            filled.append(f"{st['id']} <- {gname} ({code})")

    # stop_times: stream the big one
    per_trip = defaultdict(list)
    first_dep = {}
    rows = read_csv(zf, "stop_times.txt")
    header = {c: i for i, c in enumerate(next(rows))}
    i_trip, i_seq = header["trip_id"], header["stop_sequence"]
    i_stop, i_dep = header["stop_id"], header["departure_time"]
    i_dist = header.get("shape_dist_traveled")
    for r in rows:
        tid = r[i_trip]
        if tid not in trips:
            continue
        seq = int(r[i_seq])
        dist = None
        if i_dist is not None and r[i_dist]:
            try:
                dist = float(r[i_dist])
            except ValueError:
                dist = None
        per_trip[tid].append((seq, r[i_stop], dist))
        prev = first_dep.get(tid)
        if prev is None or seq < prev[0]:
            first_dep[tid] = (seq, r[i_dep])

    # classify trips into windows
    window_trips = defaultdict(list)  # (window, serie) -> [trip_id]
    for tid, (rid, sid, _direction) in trips.items():
        days = service_days.get(sid)
        if not days or tid not in first_dep:
            continue
        total = sum(days.values())
        if total < MIN_SERVICE_DATES:
            continue
        dep = first_dep[tid][1]
        try:
            hour = int(dep.split(":")[0])
        except (ValueError, IndexError):
            continue
        serie = route_serie[rid]
        if hour >= 20:
            window_trips[(4, serie)].append(tid)
            continue
        if days["madot"] / total >= DAY_FRACTION:
            window_trips[(1, serie)].append(tid)
        if days["vr"] / total >= DAY_FRACTION:
            window_trips[(2, serie)].append(tid)
        if days["weekend"] / total >= DAY_FRACTION:
            window_trips[(3, serie)].append(tid)

    unmapped_codes = defaultdict(int)

    def build_route(trip_ids):
        """Merge trips of ONE route_id into an ordered stop list plus counts.

        Ordering uses direction-0 trips only (shape_dist scales are only
        comparable within one direction of one route); counts use all trips.
        """
        count = defaultdict(int)
        for tid in trip_ids:
            for _seq, stop_id, _dist in per_trip[tid]:
                code = stop_code.get(stop_id)
                st = by_code.get(code) if code else None
                if st is None:
                    if code:
                        unmapped_codes[code] += 1
                    continue
                count[st["id"]] += 1
        dir0 = [t for t in trip_ids if trips[t][2] != "1"]
        use = dir0 or trip_ids
        reverse_final = not dir0
        pos = defaultdict(list)
        for tid in use:
            stops_raw = sorted(per_trip[tid])
            n = len(stops_raw)
            for k, (_seq, stop_id, dist) in enumerate(stops_raw):
                code = stop_code.get(stop_id)
                st = by_code.get(code) if code else None
                if st is None:
                    continue
                pos[st["id"]].append(dist if dist is not None else k / max(n - 1, 1))
        if not pos:
            return [], {}
        order = {s: sum(v) / len(v) for s, v in pos.items()}
        # Stations served only in direction 1 have no direction-0 ordering key
        # and were silently dropped (proven: meppel on the weekend 700). Map
        # their direction-1 keys onto the direction-0 axis with a linear fit
        # over the stations both directions serve.
        missing = [s for s in count if s not in order]
        if missing and dir0:
            pos1 = defaultdict(list)
            for tid in trip_ids:
                if trips[tid][2] != "1":
                    continue
                stops_raw = sorted(per_trip[tid])
                n = len(stops_raw)
                for k, (_seq, stop_id, dist) in enumerate(stops_raw):
                    code = stop_code.get(stop_id)
                    st = by_code.get(code) if code else None
                    if st is not None:
                        pos1[st["id"]].append(
                            dist if dist is not None else k / max(n - 1, 1)
                        )
            common = [s for s in order if s in pos1]
            if len(common) >= 2:
                xs = [sum(pos1[s]) / len(pos1[s]) for s in common]
                ys = [order[s] for s in common]
                mx = sum(xs) / len(xs)
                my = sum(ys) / len(ys)
                var = sum((x - mx) ** 2 for x in xs)
                if var > 0:
                    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / var
                    a = my - b * mx
                    for s in missing:
                        if s in pos1:
                            order[s] = a + b * (sum(pos1[s]) / len(pos1[s]))
        ordered = sorted(order, key=lambda s: order[s])
        if reverse_final:
            ordered.reverse()
        return ordered, count

    OUTDIR.mkdir(exist_ok=True)
    summary = []
    for page in (1, 2, 3, 4):
        series_out = []
        for (win, serie), tids in sorted(window_trips.items()):
            if win != page:
                continue
            by_route = defaultdict(list)
            for tid in tids:
                by_route[trips[tid][0]].append(tid)
            candidates = []
            for rid_tids in by_route.values():
                stops, count = build_route(rid_tids)
                if len(stops) >= 2:
                    candidates.append((stops, count, len(rid_tids)))
            if not candidates:
                continue
            # longest route first; absorb routes whose stops are a subset
            candidates.sort(key=lambda c: -len(c[0]))
            kept = []
            for stops, count, n in candidates:
                if any(set(stops) <= set(k[0]) for k in kept):
                    continue
                kept.append((stops, count, n))
            stops, count, _ = kept[0]
            n_trips = len(tids)
            issues = []
            if len(kept) > 1:
                issues.append(
                    f"{len(kept) - 1} extra routevariant(en) met eigen traject"
                )
            rare = [s for s in stops if count[s] < n_trips * RARE_STOP_FRACTION]
            if rare:
                issues.append(
                    "stations met weinig ritten (mogelijk variant of spitsstop): "
                    + ", ".join(rare[:12])
                )
            dates = window_dates["madot" if page == 1 else "vr" if page == 2 else "weekend"]
            n_days = max(len(dates), 1) if page != 4 else 156
            per_day = n_trips_per_day(tids, trips, service_days)
            per_hour = per_day / 2 / SPAN_HOURS[page]
            if per_hour >= 1.5:
                fclass = "2x_per_uur"
            elif per_hour >= 0.6:
                fclass = "1x_per_uur"
            else:
                fclass = "overig"
            products = defaultdict(int)
            for tid in tids:
                p = route_product.get(trips[tid][0])
                if p:
                    products[p] += 1
            product = max(products, key=products.get) if products else ""
            countries = {by_slug[s]["country"] for s in stops}
            series_out.append(
                {
                    "id": serie,
                    "product": product,
                    "kind": "binnenland" if countries == {"NL"} else "internationaal",
                    "frequency": {
                        "class": fclass,
                        "note": f"GTFS-afgeleid: ~{per_day:.0f} ritten per dag "
                                f"(beide richtingen) in dit venster",
                    },
                    "routes": [{"stops": ks} for ks, _, _ in kept],
                    "confidence": "low" if n_trips < 5 or rare else "medium",
                    "issues": issues,
                }
            )
        out = {
            "schemaVersion": 1,
            "page": page,
            "timeWindow": TIME_WINDOWS[page],
            "series": series_out,
            "notes": [
                "Afgeleid uit OVapi GTFS (gtfs.ovapi.nl, CC0-bron), niet uit de kaart.",
                f"Parameters: min {MIN_SERVICE_DATES} rijdagen per rit, "
                f"dagklasse-drempel {DAY_FRACTION}, venster 4 = vertrek 20:00 of later.",
                "Frequentieklasse is een benadering op ritaantallen.",
            ],
        }
        path = OUTDIR / f"page{page}.series.json"
        path.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
        summary.append(f"page {page}: {len(series_out)} series")

    STATIONS.write_text(json.dumps(stations_doc, indent=2, ensure_ascii=False) + "\n")

    print("OK " + "; ".join(summary))
    if filled:
        print(f"vocabulary filled from GTFS ({len(filled)}):")
        for f in filled:
            print(f"  {f}")
    top_unmapped = sorted(unmapped_codes.items(), key=lambda kv: -kv[1])[:15]
    if top_unmapped:
        print("unmapped station codes (dropped from routes, top 15):")
        for code, n in top_unmapped:
            print(f"  {code} ({code_name.get(code, '?')}): {n} stop events")
    if skipped_routes:
        print(f"routes without serie suffix skipped: {len(skipped_routes)}")


def n_trips_per_day(tids, trips, service_days):
    """Average trips per active day: sum of each trip's dates / distinct dates."""
    total_dates = 0
    for tid in tids:
        days = service_days[trips[tid][1]]
        total_dates += sum(days.values())
    # 156 dates over ~22 weeks; a daily trip contributes ~156, so trips/day =
    # total trip-date pairs / feed horizon days. Approximate horizon per window
    # by the max dates any single trip has.
    horizon = max(
        (sum(service_days[trips[tid][1]].values()) for tid in tids), default=1
    )
    return total_dates / max(horizon, 1)


if __name__ == "__main__":
    main()
