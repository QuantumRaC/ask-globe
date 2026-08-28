"""Small hardcoded keyword -> bounding box lookup for named geographic regions.

Scope: sub-country / cross-country REGIONS only. Whole countries are already
covered precisely via `--country <ISO3>` against the GLOBE API's own country
endpoint, so they are intentionally NOT duplicated here.

Each entry's bbox comes from a specific, re-checkable source (either a real
OpenStreetMap/Nominatim boundary relation, or a fixed astronomical definition)
-- not from memory. Many candidate regions (Amazon Basin, Sahara, Sahel,
Pacific Northwest, Great Plains, Caribbean, Great Lakes, Mediterranean Basin,
Congo Basin) were deliberately left out: they have no single agreed-upon
polygon in OpenStreetMap, and geocoding queries for them return unrelated
small places (a Missouri hamlet named "Amazonia", a San Diego street named
"Pacific Northwest", etc). Add regions here only when a real, checkable
source is found -- do not fill gaps with guessed coordinates.

Bbox tuples are (min_lat, max_lat, min_lon, max_lon) in decimal degrees.
"""

REGIONS = {
    "great barrier reef": {
        "bbox": (-24.4984989, -10.6818889, 142.5316508, 154.0009989),
        "source": "OpenStreetMap/Nominatim relation 'Great Barrier Reef Marine Park, Australia' (leisure=nature_reserve)",
    },
    "alps": {
        "bbox": (43.4077305, 48.4092924, 5.0455740, 16.6058353),
        "source": "OpenStreetMap/Nominatim relation 'Alps' (boundary=region)",
    },
    "everglades": {
        "bbox": (24.8511292, 25.8915125, -81.5205256, -80.3889942),
        "source": "OpenStreetMap/Nominatim relation 'Everglades National Park, Florida, United States' (leisure=nature_reserve)",
    },
    "himalayas": {
        "bbox": (26.8633002, 34.9400032, 75.0805444, 94.7240991),
        "source": "OpenStreetMap/Nominatim relation 'Himalayas' (natural=mountain_range)",
    },
    "arctic": {
        "bbox": (66.5, 90.0, -180.0, 180.0),
        "source": "Standard definition of the Arctic Circle (~66°33'N)",
    },
    "antarctic": {
        "bbox": (-90.0, -66.5, -180.0, 180.0),
        "source": "Standard definition of the Antarctic Circle (~66°33'S)",
    },
}


def resolve_place(keyword):
    """Look up a region keyword and return (min_lat, max_lat, min_lon, max_lon), or None."""
    entry = REGIONS.get(keyword.strip().lower())
    return entry["bbox"] if entry else None


def list_places():
    """Return the sorted list of supported region keywords."""
    return sorted(REGIONS)
