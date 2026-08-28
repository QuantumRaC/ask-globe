# ask-globe

An LLM Skill (backed by a standalone CLI) that fetches crowdsourced
[GLOBE Observer](https://observer.globe.gov/) citizen-science data (e.g.
mosquito habitats, land cover, sky conditions, water quality, tree height,
soil properties) and outputs answers to natural-language questions 
for researchers.

Ask your agent a question in plain language (e.g. *"has anyone logged
mosquito breeding sites in the Philippines this year?"*) and it fetches
GLOBE data, prunes it for context and performance optimization, and answers
using the structured, quantified format defined in [SKILL.md](SKILL.md) --
explicit sample sizes, calibrated hedging, and guardrails against common
mistakes when reasoning about sparse, non-randomly-sampled crowdsourced data.
You can always personalize your output preferences in [SKILL.md](SKILL.md).

No external dependencies. This CLI is a Python standard library built With
Python 3.8, developed with AI assistance.


## Context - What is GLOBE Observer?

[GLOBE Observer](https://observer.globe.gov/) is a NASA citizen-science program
where volunteers worldwide submit environmental measurements via a mobile app.
`ask-globe` queries this public dataset in real time through GLOBE's REST API,
addressing the time sensitivity of this active data source.

## Requirements

- Python 3.8+
- An agent that supports custom skills/instructions + shell execution (e.g.
  [Claude Code](https://docs.claude.com/en/docs/claude-code/overview))

## Installing as a skill

### Claude Code

Skills live in a `.claude/skills/<name>/` directory and are auto-discovered.
Keep `SKILL.md`, `globe_fetcher.py`, and `locations.py` together in this
directory `ask-globe`. The skill's instructions invoke the script by relative path.

**Option A -- project-level** (only available inside one project):

```bash
mkdir -p .claude/skills
git clone https://github.com/QuantumRaC/ask-globe.git .claude/skills/ask-globe
```

**Option B -- user-level** (available in every project on your machine):

```bash
mkdir -p ~/.claude/skills
git clone https://github.com/QuantumRaC/ask-globe.git ~/.claude/skills/ask-globe
```

Then start Claude Code and ask a GLOBE-related question. Claude Code will 
recognize the skill from its `description` frontmatter in `SKILL.md`, 
invoke `globe_fetcher.py`, and answer using the structured format
(Summary Metrics / Key Observations / Data Limitations) that `SKILL.md`
requires. 

You can confirm whether `ask-globe` is installed by asking Claude Code to list its
available skills.

### Other agents

`ask-globe` doesn't depend on any Claude-specific API, so any agent can use
it as well.

## Example

Once installed, a plain-language question like:

> by how much has mosquito habitat records increased in the past 1 year in Florida?

causes the agent to run something like:

```bash
python globe_fetcher.py --protocol mosquito_habitat_mapper --start 2025-08-28 --end 2026-08-28 --bbox 24.5,31.0,-87.6,-80.0 --full --summarize --pretty 
```

and answer from the resulting JSON -- explicitly stating the spatial/temporal
window it searched (and never concluding "no mosquitoes" just because
`total_matched` is low). (see [SKILL.md](SKILL.md) for why).

## CLI reference

You normally won't type these flags yourself -- your agent constructs them
from your question, per [SKILL.md](SKILL.md)'s guidance. This reference is
for understanding what the agent is doing, or for running `globe_fetcher.py`
directly.

```
python globe_fetcher.py --protocol <name...> --start YYYY-MM-DD --end YYYY-MM-DD \
    (--bbox lat_min,lat_max,lon_min,lon_max | --country ISO3 | --place KEYWORD) \
    [--sample | --size N | --full] [--summarize] [--pretty] [--out FILE]
```

### Required arguments

| Flag | Description |
|---|---|
| `--protocol NAME [NAME ...]` | One or more GLOBE protocol names. See `--list-protocols` for the full valid set (e.g. `mosquito_habitat_mapper`, `land_covers`, `sky_conditions`, `tree_heights`, `soil_phs`, ...). |
| `--start YYYY-MM-DD` | Start of the date range (inclusive). |
| `--end YYYY-MM-DD` | End of the date range (inclusive). |
| location (one required) | `--bbox`, `--country`, or `--place` -- see below. The GLOBE API does not support unfiltered global queries, so exactly one is required. |

### Location (choose exactly one)

| Flag | Description |
|---|---|
| `--bbox lat_min,lat_max,lon_min,lon_max` | Arbitrary bounding box in decimal degrees. |
| `--country ISO3` | Three-letter ISO country code (e.g. `USA`, `PHL`, `KEN`). |
| `--place KEYWORD` | A small set of pre-sourced named regions (see `--list-places`). Currently: `alps`, `antarctic`, `arctic`, `everglades`, `great barrier reef`, `himalayas`. For anything else, look up real coordinates and use `--bbox`. |

### Volume control (choose at most one; default `--sample`)

| Flag | Description |
|---|---|
| `--sample` | ~10 sample records. Good for exploratory/existence questions. **Default if no volume flag is given.** |
| `--size N` | Fetch up to N records in a single page (soft cap 500). |
| `--full` | Fetch every matching record via pagination (hard cap 5000). Best paired with `--summarize`. |

### Output options

| Flag | Description |
|---|---|
| `--summarize` | Return aggregated per-field statistics (numeric min/max/mean, boolean counts, categorical distributions, geographic spread, date coverage) instead of raw records. Orthogonal to the volume flags -- combine with `--full` for real aggregate stats, or with `--sample`/`--size` for a quick peek. |
| `--pretty` | Pretty-print the JSON output (indented). Default is compact. |
| `--out FILE` | Write JSON to a file instead of stdout. |

### Discovery

| Flag | Description |
|---|---|
| `--list-protocols` | Print all valid `--protocol` names and exit. |
| `--list-places` | Print all valid `--place` keywords and exit. |

## Example output

```bash
$ python globe_fetcher.py --protocol mosquito_habitat_mapper \
    --start 2024-06-01 --end 2024-06-30 --country PHL --pretty
```

```json
{
  "query": {
    "protocols": ["mosquito_habitat_mapper"],
    "date_range": {"start": "2024-06-01", "end": "2024-06-30"},
    "location": "country(PHL)",
    "mode": "sample",
    "total_matched": 3,
    "records_included": 3,
    "truncated": false
  },
  "records": [
    {
      "protocol": "mosquito_habitat_mapper",
      "measuredDate": "2024-06-04",
      "siteId": 354967,
      "countryCode": "PHL",
      "countryName": "Philippines",
      "latitude": 14.61003,
      "longitude": 121.045827,
      "data": {
        "mosquitohabitatmapperLarvaeCount": "0",
        "mosquitohabitatmapperBreedingGroundEliminated": false,
        ...
      }
    }
  ]
}
```

Every response includes a `query` block reporting exactly what spatial and
temporal window was used -- this is intentional (see [SKILL.md](SKILL.md)) so
downstream consumers never lose track of query scope.

## How it works

1. **Validate** -- protocol names, date format, and bounding box are checked
   locally before any network call. Invalid protocols get a "did you mean"
   suggestion.
2. **Resolve location** -- `--bbox`/`--country`/`--place` map to one of three
   GLOBE API endpoint variants (`.../lat/lon/`, `.../country/`, or a plain
   bbox lookup via `locations.py` for `--place`).
3. **Fetch** -- a single `urllib` GET request (or a paginated loop for
   `--full`, using the API's `from`/`size` params) against
   `api.globe.gov/search/v1/measurement/protocol/measureddate`.
4. **Prune** -- each raw record is stripped of `null` fields, photo-URL
   fields, and non-scientific bookkeeping fields (`organizationId`, `pid`,
   `createDate`, `updateDate`, `publishDate`). Field names are left untouched
   (no protocol-prefix stripping), so `data.*` keys stay traceable to their
   source protocol.
5. **Summarize (optional)** -- if `--summarize` is passed, per-field type
   detection (boolean / numeric / categorical / free-text) produces
   aggregate statistics instead of returning raw records.

## Testing

```bash
python test_run.py -v
```

Runs offline unit tests (validation, parsing, pruning, summarization logic)
plus live smoke tests against the real GLOBE API (one fetch per endpoint
variant, plus a pagination-offset check). Live tests skip gracefully rather
than failing the suite if the network/API is unreachable. No `pytest`
required -- uses stdlib `unittest`.

## Known limitations

- **Crowdsourced data, sparse coverage.** A query returning zero or few
  results means no one happened to submit data for that place/time -- not
  that the phenomenon doesn't occur there. See [SKILL.md](SKILL.md) for how
  this should be communicated.
- **Occasional data-entry artifacts.** Site coordinates are sometimes
  mis-registered relative to the submitting organization's actual country
  (e.g. a bbox query for the Alps can surface a site tagged with an
  unrelated `countryCode` because that site's registered coordinates happen
  to fall in the box). This is a property of the underlying dataset, not a
  bug in the query/filtering logic.
- **`--place` covers only 6 regions.** Each entry is sourced from a specific,
  re-checkable OpenStreetMap/Nominatim boundary or a fixed astronomical
  definition (see `locations.py`). Broader macro-regions (Sahara, Amazon
  Basin, Pacific Northwest, etc.) were deliberately left out because no
  single agreed-upon polygon could be sourced without guessing -- use
  `--bbox` for those instead.

## Project structure

```
ask-globe/
├── globe_fetcher.py   # CLI: fetch, validate, prune, summarize
├── locations.py        # --place keyword -> bounding box lookup
├── test_run.py          # unittest suite (offline + live smoke tests)
├── SKILL.md              # LLM-facing usage/interpretation rules
└── README.md
```
