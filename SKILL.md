---
name: ask-globe
description: Research tool. Use when the user asks a question about NASA GLOBE Observer citizen-science measurement data -- e.g. mosquito habitats, land cover, sky conditions, water quality, tree height, soil, or any other GLOBE protocol -- for a specific place and/or time range. Answers are written for scientific/research use - quantified, sourced, and explicit about sampling limitations.
---

# ask-globe

Fetches and filters real NASA GLOBE Observer data via `globe_fetcher.py` (stdlib-only
Python CLI in this project's root) and answers the user's question from the
returned JSON. Never answer a GLOBE data question from memory/training data --
always invoke the CLI first.

## Purpose and audience

This is a **research tool**. The person asking is typically a researcher,
student, or analyst using GLOBE Observer data as evidence for environmental
or scientific work -- not a casual user wanting a quick fun fact. Treat every
answer as if it might be quoted in a lab notebook or a methods section:
precise, sourced, and explicit about uncertainty. See "Scientific
communication style" below for what that means in practice.

## Invocation

```
python globe_fetcher.py --protocol <name...> --start YYYY-MM-DD --end YYYY-MM-DD \
    (--bbox lat_min,lat_max,lon_min,lon_max | --country ISO3 | --place KEYWORD) \
    [--sample | --size N | --full] [--summarize] [--pretty]
```

- `--protocol` is required, one or more names. Run `--list-protocols` if unsure of
  the exact name (e.g. it's `sky_conditions`/`sky_condition_noons`, not `clouds`).
- `--start`/`--end` are required, `YYYY-MM-DD`.
- A location flag is required -- the GLOBE API does not support unfiltered global
  queries. Use `--bbox` for arbitrary coordinates, `--country` for an ISO3 code, or
  `--place` for a small set of pre-sourced named regions (`--list-places`; currently
  just alps, arctic, antarctic, everglades, great barrier reef, himalayas -- for
  anything else, look up real coordinates and pass `--bbox`).
- On error (bad protocol, bad date, missing/conflicting location flags) the CLI
  exits 1 and prints a clear message to stderr -- read it and correct the call
  rather than retrying blindly.

## Choosing a volume flag

- `--sample` (default): ~10 records. Use for exploratory or existence questions
  ("has anyone reported X here?").
- `--size N`: up to N records (soft cap 500), single page. Use when the user wants
  to see actual record-level detail, not just aggregate stats.
- `--full`: every matching record (hard cap 5000, paginated). Use only when you
  also need aggregate statistics -- combine with `--summarize` in that case.
  Avoid `--full` without `--summarize`: dumping thousands of raw records wastes
  context and is rarely what the user needs.
- `--summarize`: replaces raw records with per-field aggregates (numeric min/
  max/mean, boolean counts, categorical distributions, geographic spread, date
  coverage). Strongly recommended whenever the question is about totals, trends,
  or "how common/typical is X" rather than individual reports. Decide based on
  the question -- this is not automatic.

## Scientific communication style

Write like you're informing someone's research, not chatting:

- **Quantify, don't vibe.** Say "12 of 47 reports (26%) recorded standing
  water" instead of "some reports mentioned standing water." Every claim
  about the data should be traceable to a specific number in the response.
- **Always report sample size (n) alongside any statistic or proportion.**
  A rate computed from `total_matched: 4` is not the same kind of claim as
  one computed from `total_matched: 400` -- say so.
- **Distinguish observation from inference.** "GLOBE reports show N sightings
  of X" is an observation. "X is more common here than elsewhere" is an
  inference that requires a comparison you actually ran (e.g. two queries),
  not a guess. Don't imply comparisons, trends, or causation the data doesn't
  support.
- **Hedge in proportion to the evidence.** Prefer calibrated language --
  "consistent with," "suggests," "based on the N reports retrieved" -- over
  definitive claims, especially at low sample sizes or with `truncated: true`.
- **Quote values and units as GLOBE recorded them.** Don't convert units,
  round away precision, or rephrase categorical values -- researchers may
  need the raw recorded value.
- **Treat `--summarize` output as descriptive statistics of the sample
  retrieved, not the population.** GLOBE data is not randomly sampled;
  aggregates describe what was reported, not necessarily the true prevalence
  of a phenomenon.
- **Suggest concrete next queries when data is sparse or the question implies
  a broader analysis** (e.g. widen the date range, check an adjacent region,
  compare against another protocol) -- useful for a researcher iterating on a
  question, rather than just stopping at "no data."

## Required response rules

These apply to every answer built from `globe_fetcher.py` output:

1. **State the query scope explicitly.** Report the bounding box (or place/
   country) and the date range actually used -- these are in the `query` block
   of every response and must be surfaced to the user, not left implicit.
2. **Never conclude absence from zero results.** GLOBE is crowdsourced; a lack
   of reports in a region/time window means no one happened to submit data
   there, not that the phenomenon doesn't occur. Say so explicitly whenever
   `total_matched` is 0 or very low.
3. **Structure substantive answers as:**
   - **Summary Metrics** -- key numbers from the response (`total_matched`,
     `records_included`, `truncated`, and/or summary stats).
   - **Key Observations** -- what the data actually shows, in plain language,
     quantified per the style rules above.
   - **Data Limitations** -- sampling caveats (crowdsourced, uneven coverage),
     `truncated: true` if not all matching records were returned, and any
     data-quality artifacts noticed (see below).

## Known data-quality caveat

Site coordinates are occasionally mis-registered relative to the organization's
actual country -- e.g. a bbox query for the Alps returned a site tagged
`countryCode: ARG` (Argentina) because that site's registered lat/lon fell
inside the Alps bbox despite the organization being Argentine. The bbox
filtering itself is correct (verified live); this is a data-entry artifact in
the crowdsourced dataset. Don't treat every geographic anomaly as a script bug
-- but do mention such anomalies in Data Limitations if they materially affect
the answer.

## Field pruning (already applied by the CLI)

Records are pruned before you see them: null fields, photo URL fields, and
bookkeeping fields (`organizationId`, `pid`, `createDate`, `updateDate`,
`publishDate`) are already dropped. Remaining `data.*` field names keep their
original GLOBE protocol prefix (e.g. `mosquitohabitatmapperLarvaeCount`) --
this is intentional, do not assume a stripped/normalized name.
