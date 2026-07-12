#!/usr/bin/env python3
"""Merge Rijden de Treinen station data (CC0) into data/stations.json.

Adds geo ([lat, lon] WGS84) and code (NS station code, lowercase) to every
station it can match. Matching: RdT slug equals our id, else slug of RdT
name_long equals our id, else the ALIASES table. Reports what stays unmatched.

Usage:
    uv run scripts/merge_public.py
"""

import csv
import json
import re
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIONS = ROOT / "data" / "stations.json"
CSV_PATH = ROOT / "data" / "sources" / "stations-2023-09.csv"

# our station id -> RdT code (uppercase, as in the CSV)
ALIASES = {
    "alphen-aan-den-rijn": "APN",
    "bork": "EBOK",
    "bunde-westfalen": "BUENDE",
    "coesfeld": "ECMF",
    "den-haag-laan-van-noi": "LAA",
    "frankfurt-m-flughafen-fernbhf": "FNAF",
    "gronau": "G",
    "heide": "MID",
    "houthem-sint-gerlach": "SGL",
    "leer": "LEER",
    "lette": "ELET",
    "london-st-pancras-international": "STP",
    "munster-zentrum-nord": "ENHF",
    "nieuwerkerk-aan-den-ijssel": "NWK",
    "paris-aeroport-roissy-charles-de-gaulle": "ACDG",
    "paris-marne-la-vallee-chessy": "MARNE",
}

COUNTRY = {"NL": "NL", "D": "DE", "B": "BE", "F": "FR", "GB": "GB"}


def slug(name):
    s = name.replace("ß", "ss")
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower().replace("'", "").replace("’", "")
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s


def main():
    rows = list(csv.DictReader(CSV_PATH.open()))
    by_slug = {}
    by_code = {}
    for r in rows:
        by_slug.setdefault(r["slug"], r)
        by_slug.setdefault(slug(r["name_long"]), r)
        by_code[r["code"].upper()] = r

    doc = json.loads(STATIONS.read_text())
    matched = 0
    country_mismatch = []
    unmatched = []
    for st in doc["stations"]:
        row = by_slug.get(st["id"])
        if row is None and st["id"] in ALIASES:
            row = by_code.get(ALIASES[st["id"]])
        if row is None:
            unmatched.append(f"{st['id']} ({st['country']})")
            continue
        st["geo"] = [round(float(row["geo_lat"]), 5), round(float(row["geo_lng"]), 5)]
        st["code"] = row["code"].lower()
        st["type"] = row["type"]
        matched += 1
        rdt_country = COUNTRY.get(row["country"], row["country"])
        if rdt_country != st["country"]:
            country_mismatch.append(f"{st['id']}: ours {st['country']} vs RdT {rdt_country}")

    STATIONS.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n")
    print(f"OK matched {matched}/{len(doc['stations'])} stations with geo + code")
    if country_mismatch:
        print("country mismatches:")
        for c in country_mismatch:
            print(f"  {c}")
    if unmatched:
        print(f"unmatched ({len(unmatched)}):")
        for u in unmatched:
            print(f"  {u}")


if __name__ == "__main__":
    main()
