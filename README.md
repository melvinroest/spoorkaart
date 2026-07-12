# Spoorkaart

Personal web app around the NS Spoorkaart 2026. Two views over one semantic data layer:

1. Geo view (the goal): every station as a dot on a real map at its true GPS location. Enter a GPS coordinate, draw a circle with an adjustable radius, see which stations fall inside and where their direct trains go.
2. Schematic view (debug and personal use): the four original spoorkaart pages (ma-do, vrijdag, weekend, avond). Click a station and the series that stop there stay visible while everything else fades.

Full build plan with phases: `~/.agent/plans/spoorkaart/2026-07-12 spoorkaart build plan.md`. Data contract: FORMAT.md.

## Run

```
npm --prefix app run dev
```

## Design decisions

- Producer-agnostic data contract. FORMAT.md plus schema/*.schema.json define one JSON shape for "series with ordered stops per time window". Two independent producers fill it: LLM agents reading the map, and a GTFS pipeline. Disagreements between the two become a review document instead of silent errors.
- One shared station vocabulary. data/stations.json is the only legal id namespace. Four agents extracting pages independently cannot drift apart on naming, because they may only reference these ids; name fixes and missing stations travel through structured corrections channels.
- Dual truth, deliberately. The map encodes editorial information no dataset has (spits-only stops, direction-only stops, combined series labels, the 4-window split as NS drew it). GTFS has factual per-trip detail the map compresses away. Map wins on editorial semantics, GTFS on stop-level facts.
- React with imperative islands. React renders the chrome (tabs, panels, inputs). The two heavy map surfaces (a multi-megabyte inline SVG, later a Leaflet map) live behind refs; React never diffs them. Highlighting is CSS class toggling.
- Static site, no backend, no auth. Hosting the geo view later is a file upload: it is built entirely from CC0 data (OVapi GTFS, Rijden de Treinen stations) plus OSM tiles. The schematic view embeds NS-copyrighted artwork and stays personal.
- Coordinate trick: pdftocairo -svg keeps the PDF point coordinate system (viewBox 0 0 895.181 1262), and station coordinates were extracted in the same system, so click circles overlay the artwork with no transformation.

## How the PDF extraction works, briefly

Three layers, extracted separately:

1. Visual layer. `pdftocairo -svg` converts each PDF page to an SVG that is pixel-identical to the original (map/pageN.svg). No semantics, just artwork.
2. Station vocabulary (scripts/build_stations.py). A curated table of all 524 stations (names read from the PDF text layer, garbles fixed) is matched against the per-page text layer with PyMuPDF to get label coordinates: word-sequence matching with claiming (longer labels claim their words first so "Soest" cannot steal "Soest Zuid"), plus a search_for fallback for rotated labels. About 30 diagonal labels are invisible to the text layer entirely; those stations have no map coordinates yet and get them via the dev-mode editor later. Suspected garbled names were settled by rendering high-zoom crops of the map and reading the image, which also caught that the map prints "Arnhem Presikhaaf". scripts/merge_public.py joins the Rijden de Treinen stations CSV (CC0) on slugs and aliases to add WGS84 coordinates and NS station codes.
3. Series semantics, two producers:
   - Map extraction: four LLM agents, one per PDF page, each rendering overlapping high-DPI tiles and following every series line end to end. Legend semantics: a line interrupted at a station tick stops there, a line running through does not. A mechanical completeness gate forces every series token in the page text layer to be accounted for, and scripts/validate.py (JSON Schema plus referential checks) is the done-condition. Output: data/pageN.series.json.
   - GTFS pipeline (scripts/build_gtfs_series.py): the OVapi feed carries the treinserie in route_long_name (IC3000, SPR4000, ST37600). Trips are filtered to at least 10 service dates (kills ad-hoc extras), classified into the four windows via calendar_dates day-class majority plus origin departure time (20:00 boundary), and merged per route: stop order comes from direction-0 trips ordered by mean shape_dist_traveled, route variants become separate routes unless their stops are a subset. Output: data/gtfs/pageN.series.json, same schema.

The app prefers map extraction when present and falls back to GTFS; the panel shows which source is active.

## Data sources and licenses

| Source | Used for | License |
| --- | --- | --- |
| spoorkaart2026.pdf (NS) | artwork, editorial series info | NS copyright, personal use |
| OVapi GTFS (gtfs.ovapi.nl) | series, stops, time windows | CC0-sourced |
| Rijden de Treinen stations CSV | station coordinates, codes | CC0 |
| OpenStreetMap tiles (geo view, later) | base map | ODbL |

Research notes with verified URLs and data samples: `research/2026-07-12 public-timetable-data.md`.
