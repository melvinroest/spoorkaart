# Spoorkaart 2026 data contract, v1

Four extraction agents, one per PDF page (each page is the same base map for a different time window). This file plus `data/stations.json` is the full contract. Each agent produces one file, `data/page{N}.series.json`, and is done only when `scripts/validate.py` prints OK on it.

The format is producer-agnostic on purpose: the same series files can later be filled or cross-checked from public timetable data (GTFS) instead of map reading.

## Files

| Path | Producer | Role |
| --- | --- | --- |
| `data/stations.json` | orchestrator, before agents run | shared station vocabulary: ids, names, map coords, geo coords |
| `data/page1.series.json` | agent 1 | series ma-do tot 20 uur |
| `data/page2.series.json` | agent 2 | series vrijdag tot 20 uur |
| `data/page3.series.json` | agent 3 | series weekend tot 20 uur |
| `data/page4.series.json` | agent 4 | series ma-zo na 20 uur |
| `data/gtfs/pageN.minutes.json` | scripts/build_gtfs_minutes.py | per serie per route: cumulative arr/dep minutes, index-aligned with the stops array of `data/gtfs/pageN.series.json`, plus median headway per serie; minutes(a, b) = arr[b] - dep[a] |
| `data/gtfs/pageN.shapes.json` | scripts/build_gtfs_shapes.py | per serie per route: real track polyline ([lat, lon] list, Douglas-Peucker 25 m) from the best anchor-passing trip shape, route-index-aligned with `data/gtfs/pageN.series.json`; null = no shape passed the 500 m stop-to-line anchor, consumer falls back to straight lines |
| `schema/*.schema.json` | fixed | JSON Schema, machine validation |
| `scripts/validate.py` | fixed | schema plus referential validation |

## Principles

1. Transcribe, do not interpret. Series ids and note texts exactly as printed on the map. If interpretation is unavoidable, put it in `issues` and mark it as interpretation.
2. Station ids come only from `data/stations.json`. Never invent an id. `stations.json` is read-only for agents; name fixes go in `corrections`, missing stations in `unknownStations`.
3. `note` fields carry verbatim Dutch map text.
4. Honest `confidence` per series, every ambiguity in `issues`. A low-confidence entry with clear issues beats a silent guess.
5. Stop semantics follow the map legend: line interrupted at a station means the train stops there; line running through uninterrupted means it passes. Passed stations never appear in `stops` (optionally in `via`).
6. Directional markers ("trein stopt alleen in deze richting") and spits-only stations become `exceptions`, never silent omissions.
7. Validation gate: `uv run --with jsonschema scripts/validate.py data/pageN.series.json` must print OK.

## data/stations.json

```json
{
  "schemaVersion": 1,
  "source": "spoorkaart2026.pdf versie 26.02 (oktober 2025)",
  "stations": [
    {
      "id": "s-hertogenbosch",
      "name": "'s-Hertogenbosch",
      "nameAsPrinted": "'s-Hertogenbosch",
      "country": "NL",
      "major": true,
      "coords": {"1": [412.3, 618.9], "2": [412.3, 618.9]},
      "geo": [51.69048, 5.29362],
      "code": "ht",
      "suspect": false
    }
  ]
}
```

| Field | Meaning |
| --- | --- |
| `id` | slug of the canonical name: lowercase, diacritics stripped, apostrophes dropped, any other non-alphanumeric run becomes one hyphen. "'t Harde" gives `t-harde`. Printed abbreviations are expanded before slugging ("A'dam" to "Amsterdam", "Utr." to "Utrecht"). Ids are stable opaque keys; a later name correction does not change the id. |
| `name` | canonical display name, abbreviations expanded |
| `nameAsPrinted` | literal map text, kept for traceability |
| `country` | NL, DE, BE, FR, GB |
| `major` | boxed label on the map |
| `coords` | per page number: [x, y] in PDF points, origin top left, y grows downward (PyMuPDF convention) |
| `geo` | [lat, lon] WGS84, merged in from public station data, for the geographic view |
| `code` | station code (NS afkorting, e.g. `ut`, `asd`), join key to public datasets |
| `type` | station service type from the Rijden de Treinen CSV, verbatim (megastation, knooppuntIntercitystation, intercitystation, knooppuntSneltreinstation, sneltreinstation, knooppuntStoptreinstation, stoptreinstation, facultatiefStation) |
| `suspect` | text layer looked garbled; verify the name on the rendered image and file a correction |

Agents never fill `geo`, `code`, `type`, or `coords`; those are orchestrator fields.

## data/pageN.series.json

```json
{
  "schemaVersion": 1,
  "page": 1,
  "timeWindow": "ma-do tot 20 uur",
  "series": [],
  "corrections": [],
  "unknownStations": [],
  "legendVerbatim": [],
  "notes": []
}
```

`timeWindow` per page: 1 `ma-do tot 20 uur`, 2 `vrijdag tot 20 uur`, 3 `weekend tot 20 uur`, 4 `ma-zo na 20 uur`. `legendVerbatim`: copy every legend line of your page.

### Series entry

```json
{
  "id": "3000",
  "kind": "binnenland",
  "frequency": {"class": "2x_per_uur", "note": "2x per uur (7-20u)"},
  "routes": [
    {"stops": ["den-helder", "den-helder-zuid", "schagen"], "via": [], "note": ""}
  ],
  "exceptions": [
    {"type": "spits_only_stop", "station": "emmen-zuid", "note": "alleen in de spitsrichting"}
  ],
  "colorHint": "donkerblauw",
  "confidence": "high",
  "issues": []
}
```

Values above are illustrative, not authoritative extraction.

- `id`: exactly as printed near the line. Combined labels stay combined (`700/800`, `2200/2300`) unless the map shows the numbers on separate trajects on this page; if you split, say so in `issues`. `37000 (dal)/37100 (spits)` becomes two entries (`37000`, `37100`) with the verbatim text in `frequency.note`.
- `kind`: `binnenland` (entirely within NL), `internationaal` (crosses the NL border), `buitenland` (entirely outside NL, like German RE/RB/RS lines or Belgian locals at the map edge).
- `frequency.class` follows the line style per your page legend, `frequency.note` carries the verbatim legend or asterisk text ("" if none):

| class | typical legend text |
| --- | --- |
| `1x_per_uur` | 1x per uur |
| `2x_per_uur` | 2x per uur |
| `spits_1x` | 1x per uur (7-9 en 16-18u) |
| `spits_2x` | 2x per uur (7-9 en 16-18u, plus varianten) |
| `dal_1x` | 1x per uur (buiten spitsuren) |
| `zomer_2x` | 2x per uur alleen in de zomermaanden |
| `za_1x` | 1x per uur alleen op zaterdag |
| `za_2x` | 2x per uur alleen op zaterdag, plus varianten |
| `x_per_dag` | 7x per dag |
| `overig` | anything else, verbatim text in note |

- `routes`: one entry per continuous traject of this series on this page. A branch or detached segment is its own route. `stops` is the ordered end-to-end list of station ids where the train stops. `via` is optional (stations visibly passed without stopping) and not required to be exhaustive.
- `exceptions` types: `direction_only_stop`, `spits_only_stop`, `seasonal`, `splits_combines`, `other`. `station` may be omitted where it does not apply.
- `colorHint`: optional, approximate line color (Dutch color word or hex). Helps later SVG path tagging.
- `confidence`: `high`, `medium`, `low`. `issues`: one entry per ambiguity (crossings you could not untangle, labels you could not attribute, unclear gaps).

### corrections and unknownStations

```json
{"stationId": "woleze", "field": "name", "value": "Wolfheze", "evidence": "duidelijk leesbaar op het kaartbeeld tussen Ede-Wageningen en Oosterbeek"}
```

```json
{"nameAsSeen": "Voorbeeldstad", "betweenStops": ["arnhem-centraal", "velp"], "series": ["30800"], "note": "ontbreekt in vocabulaire"}
```

A correction fixes an existing vocabulary entry (`field`: `name`, `country`, `major`, `delete`). Keep using the existing id in your routes; the orchestrator merges corrections afterwards. A station missing entirely from the vocabulary cannot be referenced in `stops`: leave it out, report it in `unknownStations` with `betweenStops` (its neighbors in your route) so the route can be patched mechanically, and add an issue on the affected series.

## Validation

```
uv run --with jsonschema scripts/validate.py data/stations.json
uv run --with jsonschema scripts/validate.py data/page1.series.json
```

Checks: JSON Schema, duplicate ids, every station reference known, page and timeWindow consistency, consecutive duplicate stops. Output is OK, WARNING or FAIL lines, nothing else.
