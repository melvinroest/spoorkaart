# Data architecture: sources, decisions, and where everything lives

The single document for how this project's data works. Concepts are defined in GLOSSARY.md; the contract fields in FORMAT.md; the original source research with verified URLs in research/2026-07-12 public-timetable-data.md.

## Sources

| Source | What we take from it | License | Chain |
| --- | --- | --- | --- |
| spoorkaart2026.pdf (NS, versie 26.02) | artwork (SVG), station vocabulary, serie colors, line geometry, editorial series semantics via extraction agents | NS copyright, personal use | NS publishes the PDF for download |
| OVapi GTFS (gtfs.ovapi.nl/nl/gtfs-nl.zip) | series to ordered stops per window, product type, frequencies, later travel minutes | CC0-sourced | NS timetable -> IFF -> NDOV Loket (CC0) -> OVapi conversion, rebuilt nightly |
| Rijden de Treinen stations CSV (data/sources/stations-2023-09.csv) | WGS84 coordinates and NS station codes | CC0 | independent open-data export |
| NS IFF (data.ndovloket.nl/iff/ns-latest.zip) | NOT parsed today; the authoritative source for stations a train passes without stopping | CC0 | the raw NS delivery behind the GTFS |

## The two producers, one contract

Both fill the same schema (FORMAT.md, schema/, scripts/validate.py as done-gate):

- Map extraction: data/page{1..4}.series.json, produced by one LLM agent per PDF page reading rendered tiles. Editorial truth.
- GTFS pipeline: data/gtfs/page{1..4}.series.json, produced by scripts/build_gtfs_series.py. Factual truth.

The app prefers the map file per page and falls back to GTFS (app/src/data.ts); the panel shows which source is active.

## Why two sources: where the map is sharper than the data

Observed in this project, not theoretical:

1. One line per serie is an editorial judgment, not a query result. GTFS is 36,873 raw trips including works diversions, 700000-offset variants and ad-hoc 28xxx trains; the pipeline approximates a serie with thresholds (minimum 10 service dates, dominant patterns) and still produced a wrong 5700 before tuning. The map states the answer directly.
2. Footnote rules do not exist in GTFS as rules. "Emmen en Emmen Zuid alleen in de spitsrichting", half-circle direction-only stops (Rosmalen, 's-Hertogenbosch Oost), "2700 middagspits richting Den Helder", "na 22 u: 1x per uur", "Bourg-St-Maurice alleen in de wintermaanden". The trips behind them are in GTFS; the rule itself is only printed on the map. Captured as structured exceptions in the series files.
3. The four time windows are editorial. GTFS has dates and times; that ma-do, vrijdag, weekend and avond are THE four patterns, including the edge cases, is NS's compression. The pipeline reconstructs it (day-class majority plus 20:00 origin-departure boundary); the map embodies it.
4. Stop versus pass is drawn. The 1100 visibly bypasses the Dordrecht capsule; 9100 passes Antwerpen-Centraal while 9300 stops. GTFS is silent about passes (a missing station is just missing); IFF would be the data source if we ever need passes authoritatively.
5. Coupled-family semantics. 2200/2300 is one drawn trunk that splits in Zeeland, where 2300 skips Arnemuiden and Kapelle-Biezelinge and 2200 stops. GTFS presents two unrelated series.
6. Foreign lines. RB51, RB61, RB64, RE13 (German locals on the map edge) are not in the Dutch feed at all.

And the mirror image, where GTFS is sharper: exact times (the future minutes-per-leg data), platforms, boarding and alighting flags, actual calendar dates, and series that exist in reality but are not printed on the map (16900, 300, 900, the night set).

## Decision rules

- Editorial semantics (what stops where per window, footnotes, combined labels): the MAP file wins.
- Facts (travel minutes, frequencies as numbers, calendar reality): GTFS wins.
- Disputes: scripts/diff_map_gtfs.py writes research/2026-07-12 map-vs-gtfs-diff.md; disagreements are reviewed by hand, not auto-resolved. Example dispute already settled by a third source: Utrecht - Nieuw Vennep direct existed on weekdays (map plus GTFS agreed; a weekend Google check initially suggested otherwise).
- Vocabulary: data/stations.json is the only legal station id namespace for every producer. Changes go through scripts/build_stations.py plus scripts/merge_public.py, then validation.
- Every generated data file must pass scripts/validate.py before use.

## Where is what (and how to regenerate it)

| Artifact | Contents | Regenerate with |
| --- | --- | --- |
| map/pageN.svg | artwork, PDF points viewBox 0 0 895.181 1262 | pdftocairo -svg -f N -l N spoorkaart2026.pdf map/pageN.svg |
| data/stations.json | 524 stations: id, name, country, major, coords (PDF pt per page), geo (WGS84), code | uv run --with pymupdf scripts/build_stations.py, then uv run scripts/merge_public.py, then scripts/build_gtfs_series.py fills GTFS-only gaps |
| data/gtfs/pageN.series.json | GTFS-derived series per window, incl. product | uv run scripts/build_gtfs_series.py <gtfs-nl.zip> (download from gtfs.ovapi.nl if absent) |
| data/pageN.series.json | map-extracted series (agents produce these; do not regenerate by script) | re-run an extraction agent if ever needed |
| data/serie-colors.json | line color per serie (stroke under the label, badge fallback) | uv run --with pymupdf scripts/extract_serie_colors.py |
| data/highlights/pageN.json | drawn line geometry per serie for the app overlay | uv run --with pymupdf scripts/extract_highlights.py |
| research/2026-07-12 map-vs-gtfs-diff.md | disagreement report for hand review | uv run scripts/diff_map_gtfs.py > "research/2026-07-12 map-vs-gtfs-diff.md" |
| data/sources/stations-2023-09.csv | vendored RdT station list | re-download from opendata.rijdendetreinen.nl if ever needed |

Regeneration order after a vocabulary change: build_stations -> merge_public -> build_gtfs_series -> build_gtfs_minutes -> extract_serie_colors -> extract_highlights -> diff_map_gtfs -> validate everything (series AND minutes files; the minutes are index-aligned with the series stop arrays, so they must regenerate together).

## Refresh policy

The GTFS feed horizon ends 2026-12-12 (timetable year). Re-running build_gtfs_series against a fresh download is enough; weekly is plenty. When dienstregeling 2027 appears (mid-December 2026), the same pipeline regenerates everything; the map side then needs the 2027 spoorkaart PDF and a re-run of the extraction agents.
