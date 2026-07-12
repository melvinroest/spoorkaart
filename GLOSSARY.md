# Glossary

Short explanations of every domain concept in this project, with pointers to the deeper source. Style: concrete, no metaphors.

## The data chain

NS -> NDOV Loket (raw, CC0) -> OVapi (GTFS conversion) -> this project's pipeline.

- **NS spoorkaart**: the official schematic rail map PDF (spoorkaart2026.pdf, versie 26.02). Four pages, same base map, four time windows. Editorial: NS cartographers decide what one line per serie looks like and which footnotes exist. Copyright NS, which is why only the geo view is publicly hostable.
- **IFF**: NS's own timetable exchange format, the raw delivery behind everything. A zip of fixed-width text files (timetbls.dat, stations.dat, footnote.dat), one record block per train run, first character = field type. Uniquely encodes stations a train passes WITHOUT stopping (";" lines), which GTFS drops. Sample decoded in research/2026-07-12 public-timetable-data.md, source 2. Available at data.ndovloket.nl/iff/ns-latest.zip.
- **NDOV Loket** (data.ndovloket.nl): the national open-data clearinghouse where Dutch public-transport operators must publish their raw timetable data. CC0, no registration.
- **OVapi** (gtfs.ovapi.nl): volunteer-run openOV service that converts all NDOV deliveries into one national GTFS zip covering every Dutch operator (gtfs-nl.zip, about 236 MB, rebuilt nightly, valid through the timetable year, currently 2026-12-12).
- **GTFS** (General Transit Feed Specification): the world-standard transit schedule format, invented 2006 by Google and Portland's TriMet so Google Maps could plan transit trips. A zip of CSVs: stops.txt (stations, lat/lon), routes.txt (lines), trips.txt (individual runs), stop_times.txt (ordered stops with times per run), calendar_dates.txt (which dates each run rides). Full field notes: research report, source 1.
- **Rijden de Treinen** (rijdendetreinen.nl): Dutch train-data site whose CC0 stations CSV (data/sources/stations-2023-09.csv) supplies WGS84 coordinates and station codes for NL plus border stations.

## Rail concepts

- **Treinserie (serie)**: a numbered family of trains on one route pattern, e.g. serie 3000 = the Den Helder - Nijmegen intercity. Individual trips carry numbers inside the block (3015, 3021); serie = trip number floored to hundreds, but the reliable source is the route name in GTFS ("Den Helder <-> Nijmegen IC3000"). The spoorkaart draws one line per serie.
- **Product**: train type of a serie: Intercity, Sprinter, Stoptrein, Sneltrein, ICE, Eurostar. From GTFS route_short_name, stored in the optional "product" field. The app's intercity/sprinter filters classify on it.
- **Station code**: the short NS code per station ("ut" Utrecht Centraal, "asd" Amsterdam Centraal, "nm" Nijmegen). The join key across all sources: GTFS zone_id, IFF station records, RdT CSV. Stored per station in data/stations.json as "code".
- **Time windows (the four pages)**: the spoorkaart's editorial split of the week: 1 ma-do tot 20u, 2 vrijdag tot 20u, 3 weekend tot 20u, 4 ma-zo na 20u. GTFS has no such split; the pipeline reconstructs it from calendar_dates day classes plus origin departure time (20:00 boundary).
- **Stop versus pass (map legend)**: a line interrupted at a station tick means the train stops there; a line running through uninterrupted means it passes. In the contract: passed stations go in "via", never in "stops". IFF is the authoritative data source for pass-throughs.
- **Spits**: rush hour (ochtendspits/middagspits). Spits-only stops and direction-only stops are map footnotes captured as structured "exceptions" in the series files.

## Project concepts

- **The contract** (FORMAT.md plus schema/): one JSON shape for "series with ordered stops per time window", producer-agnostic. Two producers fill it: map-extraction agents (data/pageN.series.json) and the GTFS pipeline (data/gtfs/pageN.series.json). The app prefers map files.
- **Vocabulary** (data/stations.json): the single legal namespace of station ids (524 stations). Ids are slugs of canonical names. Every stop reference in every series file must exist here; scripts/validate.py enforces it.
- **coords versus geo**: per station, "coords" = label position in PDF points per page (schematic view overlay), "geo" = [lat, lon] WGS84 (geo view). Two different coordinate systems for two different views.
- **Serie colors** (data/serie-colors.json): per-serie line color, extracted from the stroke of the drawn path under each serie label (badge fill as fallback). Some series are recolored per page; the highlight extractor has a per-page fallback.
- **Highlights** (data/highlights/pageN.json): the actual drawn line geometry per serie, extracted from the PDF vector drawings by color match plus station-corridor proximity plus connectivity chaining. This is what lights up in the app.
- **Dual truth and the diff**: map extraction carries editorial info (footnotes, combined labels, the window split as NS intended); GTFS carries factual per-trip detail. scripts/diff_map_gtfs.py writes the discrepancy report (research/2026-07-12 map-vs-gtfs-diff.md) for hand review.

## Where the deep versions live

- Data sources, decision rules, regeneration commands, where is what: DATA.md
- GTFS, IFF, NDOV, OVapi, RdT, licensing: research/2026-07-12 public-timetable-data.md
- Contract field semantics: FORMAT.md
- Design decisions and extraction method: README.md
- Process lessons: REFLECTION.md
- Priorities: BACKLOG.md
- Geo view mission for the next session: GEO_VIEW_HANDOFF.md
