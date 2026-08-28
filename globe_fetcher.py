#!/usr/bin/env python3
"""CLI to fetch, prune, and optionally summarize NASA GLOBE Observer measurement data.

Stdlib-only (urllib) -- no external dependencies required.
"""

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime

import locations

API_BASE = "https://api.globe.gov/search/v1/measurement/protocol/measureddate"
REQUEST_TIMEOUT = 30

# From live Swagger inspection of https://api.globe.gov/search/v1/api-docs?group=public-api
VALID_PROTOCOLS = {
    "aerosols", "air_temp_dailies", "air_temp_monthlies", "air_temp_noons", "air_temps",
    "eclipses", "barometric_pressure_noons", "barometric_pressures", "biometry_trees",
    "carbon_cycle", "conductivities", "dissolved_oxygens", "freshwater_macroinvertebrates",
    "frost_tubes", "graminoid_biomasses", "greenings", "humidities", "humidity_monthlies",
    "humidity_noons", "hydrology_alkalinities", "hydrology_phs", "land_covers",
    "mosquito_habitat_mapper", "nitrates", "phenological_gardens", "precipitation_monthlies",
    "precipitations", "salinities", "sky_condition_noons", "sky_conditions", "snowpacks",
    "soil_characterizations", "soil_densities", "soil_fertilities", "soil_infiltrations",
    "soil_layer_descriptions", "soil_moisture_for_smap", "soil_moisture_via_gravimetrics",
    "soil_particle_size_distributions", "soil_phs", "soil_temp_dailies", "soil_temp_monthlies",
    "soil_temp_noons", "soil_temp_sub_days", "surface_temperature_noons", "surface_temperatures",
    "transparencies", "tree_heights", "vegatation_covers", "volumetric_soil_moisture_monthlies",
    "water_temperatures", "water_vapor_noons", "water_vapors", "winds",
}

# Stable fields present on every record regardless of protocol. Bookkeeping-only
# fields (organizationId, pid, createDate, updateDate, publishDate) are dropped
# here -- not scientifically relevant, and this is a generic rule, not a
# per-protocol schema.
META_FIELDS = [
    "protocol", "measuredDate", "siteId", "siteName", "countryCode", "countryName",
    "latitude", "longitude", "elevation", "organizationName",
]

SOFT_SIZE_CAP = 500
FULL_PAGE_SIZE = 500
FULL_HARD_CAP = 5000
CATEGORICAL_CARDINALITY_CAP = 15


class GlobeFetchError(Exception):
    pass


def validate_protocols(protocols):
    invalid = [p for p in protocols if p not in VALID_PROTOCOLS]
    if not invalid:
        return
    lines = []
    for bad in invalid:
        bad_key = bad.replace("_", "").lower()
        close = sorted(p for p in VALID_PROTOCOLS if bad_key in p.replace("_", "").lower())
        if close:
            lines.append(f"  {bad!r} is not valid -- did you mean: {', '.join(close)}?")
        else:
            lines.append(f"  {bad!r} is not a valid protocol")
    raise GlobeFetchError(
        "Invalid protocol(s):\n" + "\n".join(lines) +
        "\n\nValid protocols:\n  " + ", ".join(sorted(VALID_PROTOCOLS))
    )


def validate_date(value, label):
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        raise GlobeFetchError(f"--{label} must be YYYY-MM-DD, got {value!r}")


def parse_bbox(raw):
    parts = raw.split(",")
    if len(parts) != 4:
        raise GlobeFetchError("--bbox must be 'lat_min,lat_max,lon_min,lon_max'")
    try:
        min_lat, max_lat, min_lon, max_lon = (float(p.strip()) for p in parts)
    except ValueError:
        raise GlobeFetchError(f"--bbox values must be numeric, got {raw!r}")
    if not (-90 <= min_lat <= 90 and -90 <= max_lat <= 90):
        raise GlobeFetchError("--bbox latitudes must be within -90..90")
    if not (-180 <= min_lon <= 180 and -180 <= max_lon <= 180):
        raise GlobeFetchError("--bbox longitudes must be within -180..180")
    if min_lat > max_lat or min_lon > max_lon:
        raise GlobeFetchError("--bbox min must be <= max for both lat and lon")
    return min_lat, max_lat, min_lon, max_lon


def resolve_location(args):
    """Return (base_url_suffix, extra_params, location_description)."""
    if not (args.bbox or args.country or args.place):
        raise GlobeFetchError(
            "One of --bbox, --country, or --place is required "
            "(the GLOBE API does not support unfiltered global queries)"
        )
    if args.bbox and args.place:
        raise GlobeFetchError("--bbox and --place are mutually exclusive")
    if (args.bbox or args.place) and args.country:
        raise GlobeFetchError("--country cannot be combined with --bbox/--place")

    bbox = None
    if args.bbox:
        bbox = parse_bbox(args.bbox)
    elif args.place:
        bbox = locations.resolve_place(args.place)
        if bbox is None:
            raise GlobeFetchError(
                f"Unknown --place {args.place!r}. Known regions: "
                f"{', '.join(locations.list_places())}. Use --bbox for anything else."
            )

    if bbox:
        min_lat, max_lat, min_lon, max_lon = bbox
        desc = f"bbox(lat {min_lat}..{max_lat}, lon {min_lon}..{max_lon})"
        if args.place:
            desc = f"{args.place} -> {desc}"
        return "lat/lon/", {
            "minlat": min_lat, "maxlat": max_lat, "minlon": min_lon, "maxlon": max_lon,
        }, desc

    if args.country:
        code = args.country.strip().upper()
        if len(code) != 3 or not code.isalpha():
            raise GlobeFetchError(f"--country expects an ISO3 code (e.g. USA), got {args.country!r}")
        return "country/", {"countrycode": code}, f"country({code})"

    raise GlobeFetchError("Unreachable: no location resolved")


def http_get_json(url):
    # No explicit Accept header: the GLOBE API's content negotiation returns
    # HTTP 406 if "Accept: application/json" is sent, even though it serves
    # valid JSON by default with no Accept header at all (verified live).
    request = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
            body = response.read()
    except urllib.error.HTTPError as exc:
        raise GlobeFetchError(f"GLOBE API returned HTTP {exc.code} for {url}\n{exc.read()[:500]!r}")
    except urllib.error.URLError as exc:
        raise GlobeFetchError(f"Failed to reach GLOBE API: {exc.reason}")
    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise GlobeFetchError(f"GLOBE API returned non-JSON response: {exc}")


def fetch_page(endpoint_suffix, params):
    query = urllib.parse.urlencode(params, doseq=True)
    url = f"{API_BASE}/{endpoint_suffix}?{query}"
    payload = http_get_json(url)
    if "results" not in payload:
        raise GlobeFetchError(f"Unexpected GLOBE API response shape: {list(payload)[:10]}")
    return payload["count"], payload["results"]


def fetch_records(args, endpoint_suffix, extra_params):
    base_params = {
        "protocols": args.protocol,
        "startdate": args.start,
        "enddate": args.end,
        "geojson": "FALSE",
        **extra_params,
    }

    if args.full:
        raw_records = []
        total_count = None
        offset = 0
        while True:
            params = {**base_params, "sample": "FALSE", "size": FULL_PAGE_SIZE, "from": offset}
            count, page = fetch_page(endpoint_suffix, params)
            if total_count is None:
                total_count = count
            raw_records.extend(page)
            offset += FULL_PAGE_SIZE
            if len(page) < FULL_PAGE_SIZE or offset >= FULL_HARD_CAP or len(raw_records) >= total_count:
                break
        truncated = total_count is not None and len(raw_records) < total_count
        return total_count, raw_records, truncated, "full"

    if args.size is not None:
        size = min(args.size, SOFT_SIZE_CAP)
        params = {**base_params, "sample": "FALSE", "size": size, "from": 0}
        total_count, raw_records = fetch_page(endpoint_suffix, params)
        truncated = total_count > len(raw_records)
        return total_count, raw_records, truncated, "size"

    # default: sample
    params = {**base_params, "sample": "TRUE"}
    total_count, raw_records = fetch_page(endpoint_suffix, params)
    truncated = total_count > len(raw_records)
    return total_count, raw_records, truncated, "sample"


def is_photo_url_field(key):
    lowered = key.lower()
    return "photourl" in lowered


def prune_record(raw):
    meta = {k: raw.get(k) for k in META_FIELDS if raw.get(k) is not None}
    data = raw.get("data") or {}
    pruned_data = {
        k: v for k, v in data.items()
        if v is not None and not is_photo_url_field(k)
    }
    meta["data"] = pruned_data
    return meta


def summarize(records):
    total = len(records)
    field_values = defaultdict(list)
    for rec in records:
        for key, value in rec.get("data", {}).items():
            field_values[key].append(value)

    fields_summary = {}
    for key, values in field_values.items():
        non_null = len(values)
        null = total - non_null
        if all(isinstance(v, bool) for v in values):
            counts = Counter(values)
            fields_summary[key] = {
                "type": "boolean", "non_null": non_null, "null": null,
                "counts": {str(k): v for k, v in counts.items()},
            }
        elif all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in values):
            fields_summary[key] = {
                "type": "numeric", "non_null": non_null, "null": null,
                "min": min(values), "max": max(values),
                "mean": round(sum(values) / len(values), 3),
            }
        else:
            counts = Counter(str(v) for v in values)
            if len(counts) <= CATEGORICAL_CARDINALITY_CAP:
                fields_summary[key] = {
                    "type": "categorical", "non_null": non_null, "null": null,
                    "distribution": dict(counts.most_common()),
                }
            else:
                fields_summary[key] = {
                    "type": "free_text", "non_null": non_null, "null": null,
                    "note": f"{len(counts)} distinct values, not enumerated",
                }

    site_ids = {rec.get("siteId") for rec in records if rec.get("siteId") is not None}
    country_counts = Counter(rec.get("countryCode") for rec in records if rec.get("countryCode"))
    dates = sorted(rec.get("measuredDate") for rec in records if rec.get("measuredDate"))

    return {
        "records_summarized": total,
        "geographic_spread": {
            "unique_sites": len(site_ids),
            "unique_countries": len(country_counts),
            "top_countries": dict(country_counts.most_common(5)),
        },
        "date_coverage_observed": {
            "min": dates[0] if dates else None,
            "max": dates[-1] if dates else None,
        },
        "fields": fields_summary,
    }


def build_parser():
    parser = argparse.ArgumentParser(
        description="Fetch and filter NASA GLOBE Observer measurement data.",
    )
    parser.add_argument("--protocol", nargs="+", metavar="NAME",
                         help="One or more GLOBE protocol names (see --list-protocols)")
    parser.add_argument("--start", metavar="YYYY-MM-DD")
    parser.add_argument("--end", metavar="YYYY-MM-DD")

    loc = parser.add_mutually_exclusive_group()
    loc.add_argument("--bbox", metavar="lat_min,lat_max,lon_min,lon_max")
    loc.add_argument("--country", metavar="ISO3")
    loc.add_argument("--place", metavar="KEYWORD",
                      help="Region keyword resolved via locations.py (see --list-places)")

    vol = parser.add_mutually_exclusive_group()
    vol.add_argument("--sample", action="store_true",
                      help="~10 sample records (default if no other volume flag given)")
    vol.add_argument("--size", type=int, metavar="N",
                      help=f"Fetch N records (soft cap {SOFT_SIZE_CAP})")
    vol.add_argument("--full", action="store_true",
                      help=f"Fetch all matching records (hard cap {FULL_HARD_CAP})")

    parser.add_argument("--summarize", action="store_true",
                         help="Emit aggregated field statistics instead of raw records")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output")
    parser.add_argument("--out", metavar="FILE", help="Write JSON to a file instead of stdout")
    parser.add_argument("--list-protocols", action="store_true",
                         help="Print valid protocol names and exit")
    parser.add_argument("--list-places", action="store_true",
                         help="Print valid --place keywords and exit")
    return parser


def run(args):
    if not args.sample and args.size is None and not args.full:
        args.sample = True

    if not args.protocol or not args.start or not args.end:
        raise GlobeFetchError("--protocol, --start, and --end are required")

    validate_protocols(args.protocol)
    validate_date(args.start, "start")
    validate_date(args.end, "end")

    endpoint_suffix, extra_params, location_desc = resolve_location(args)
    total_count, raw_records, truncated, mode = fetch_records(args, endpoint_suffix, extra_params)
    records = [prune_record(r) for r in raw_records]

    result = {
        "query": {
            "protocols": args.protocol,
            "date_range": {"start": args.start, "end": args.end},
            "location": location_desc,
            "mode": mode,
            "total_matched": total_count,
            "records_included": len(records),
            "truncated": truncated,
        }
    }
    if args.summarize:
        result["summary"] = summarize(records)
    else:
        result["records"] = records
    return result


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.list_protocols:
        print("\n".join(sorted(VALID_PROTOCOLS)))
        return 0
    if args.list_places:
        print("\n".join(locations.list_places()))
        return 0

    try:
        result = run(args)
    except GlobeFetchError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    text = json.dumps(result, indent=2 if args.pretty else None)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
