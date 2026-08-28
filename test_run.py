"""Tests for globe_fetcher.py.

Two groups:
  - TestOffline: pure logic (validation, parsing, pruning, summarizing). No network.
  - TestLiveSmoke: hits the real GLOBE API once per endpoint variant. Each test
    skips itself if the network/API is unreachable, rather than failing the
    whole suite on a transient outage.

Uses stdlib unittest (pytest is not installed in this environment).
Run with: python test_run.py
"""

import argparse
import unittest
import urllib.error

import globe_fetcher as gf


def make_args(**overrides):
    defaults = dict(
        protocol=["mosquito_habitat_mapper"], start="2024-06-01", end="2024-06-30",
        bbox=None, country=None, place=None,
        sample=False, size=None, full=False,
        summarize=False, pretty=False, out=None,
        list_protocols=False, list_places=False,
    )
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


class TestValidation(unittest.TestCase):
    def test_validate_protocols_valid_passes(self):
        gf.validate_protocols(["mosquito_habitat_mapper", "land_covers"])

    def test_validate_protocols_invalid_raises_with_suggestion(self):
        with self.assertRaises(gf.GlobeFetchError) as ctx:
            gf.validate_protocols(["clouds"])
        # "clouds" doesn't substring-match sky_conditions, so expect the
        # plain "not a valid protocol" branch, not a suggestion.
        self.assertIn("'clouds' is not a valid protocol", str(ctx.exception))

    def test_validate_protocols_invalid_with_real_suggestion(self):
        with self.assertRaises(gf.GlobeFetchError) as ctx:
            gf.validate_protocols(["sky_condition"])
        msg = str(ctx.exception)
        self.assertIn("did you mean", msg)
        self.assertIn("sky_conditions", msg)

    def test_validate_date_valid_passes(self):
        gf.validate_date("2024-01-01", "start")

    def test_validate_date_invalid_raises(self):
        with self.assertRaises(gf.GlobeFetchError):
            gf.validate_date("2024/01/01", "start")


class TestParseBbox(unittest.TestCase):
    def test_valid_bbox(self):
        self.assertEqual(gf.parse_bbox("5,20,115,130"), (5.0, 20.0, 115.0, 130.0))

    def test_wrong_field_count_raises(self):
        with self.assertRaises(gf.GlobeFetchError):
            gf.parse_bbox("1,2,3")

    def test_non_numeric_raises(self):
        with self.assertRaises(gf.GlobeFetchError):
            gf.parse_bbox("a,b,c,d")

    def test_lat_out_of_range_raises(self):
        with self.assertRaises(gf.GlobeFetchError):
            gf.parse_bbox("-95,20,115,130")

    def test_lon_out_of_range_raises(self):
        with self.assertRaises(gf.GlobeFetchError):
            gf.parse_bbox("5,20,115,190")

    def test_min_greater_than_max_raises(self):
        with self.assertRaises(gf.GlobeFetchError):
            gf.parse_bbox("20,5,115,130")


class TestResolveLocation(unittest.TestCase):
    def test_bbox_mode(self):
        args = make_args(bbox="5,20,115,130")
        suffix, params, desc = gf.resolve_location(args)
        self.assertEqual(suffix, "lat/lon/")
        self.assertEqual(params, {"minlat": 5.0, "maxlat": 20.0, "minlon": 115.0, "maxlon": 130.0})
        self.assertIn("bbox", desc)

    def test_country_mode(self):
        args = make_args(country="phl")
        suffix, params, desc = gf.resolve_location(args)
        self.assertEqual(suffix, "country/")
        self.assertEqual(params, {"countrycode": "PHL"})
        self.assertIn("PHL", desc)

    def test_country_invalid_code_raises(self):
        args = make_args(country="USA1")
        with self.assertRaises(gf.GlobeFetchError):
            gf.resolve_location(args)

    def test_place_mode(self):
        args = make_args(place="alps")
        suffix, params, desc = gf.resolve_location(args)
        self.assertEqual(suffix, "lat/lon/")
        self.assertIn("alps", desc)

    def test_unknown_place_raises(self):
        args = make_args(place="sahara")
        with self.assertRaises(gf.GlobeFetchError):
            gf.resolve_location(args)

    def test_missing_location_raises(self):
        args = make_args()
        with self.assertRaises(gf.GlobeFetchError):
            gf.resolve_location(args)

    def test_bbox_and_place_conflict_raises(self):
        args = make_args(bbox="5,20,115,130", place="alps")
        with self.assertRaises(gf.GlobeFetchError):
            gf.resolve_location(args)

    def test_country_and_bbox_conflict_raises(self):
        args = make_args(bbox="5,20,115,130", country="PHL")
        with self.assertRaises(gf.GlobeFetchError):
            gf.resolve_location(args)


class TestPruneRecord(unittest.TestCase):
    def test_drops_none_meta_fields_and_photo_urls_and_null_data(self):
        raw = {
            "protocol": "mosquito_habitat_mapper",
            "measuredDate": "2024-06-04",
            "siteId": 354967,
            "siteName": None,
            "countryCode": "PHL",
            "organizationId": 17419067,
            "pid": 207963548,
            "createDate": "2024-06-04T10:40:02",
            "data": {
                "mosquitohabitatmapperLarvaeCount": "0",
                "mosquitohabitatmapperAbdomenCloseupPhotoUrls": "http://example.com/x.jpg",
                "mosquitohabitatmapperComments": None,
            },
        }
        pruned = gf.prune_record(raw)
        self.assertNotIn("siteName", pruned)
        self.assertNotIn("organizationId", pruned)
        self.assertNotIn("pid", pruned)
        self.assertNotIn("createDate", pruned)
        self.assertEqual(pruned["siteId"], 354967)
        self.assertEqual(pruned["countryCode"], "PHL")
        self.assertIn("mosquitohabitatmapperLarvaeCount", pruned["data"])
        self.assertNotIn("mosquitohabitatmapperAbdomenCloseupPhotoUrls", pruned["data"])
        self.assertNotIn("mosquitohabitatmapperComments", pruned["data"])


class TestSummarize(unittest.TestCase):
    def _records(self):
        return [
            {"siteId": 1, "countryCode": "PHL", "measuredDate": "2024-06-01",
             "data": {"count": 3, "isDry": True, "source": "App"}},
            {"siteId": 2, "countryCode": "PHL", "measuredDate": "2024-06-15",
             "data": {"count": 7, "isDry": False, "source": "App"}},
            {"siteId": 3, "countryCode": "USA", "measuredDate": "2024-06-10",
             "data": {"count": 5, "isDry": True, "source": "Site"}},
        ]

    def test_numeric_field_stats(self):
        summary = gf.summarize(self._records())
        count_field = summary["fields"]["count"]
        self.assertEqual(count_field["type"], "numeric")
        self.assertEqual(count_field["min"], 3)
        self.assertEqual(count_field["max"], 7)
        self.assertEqual(count_field["mean"], 5.0)

    def test_boolean_field_counts(self):
        summary = gf.summarize(self._records())
        is_dry = summary["fields"]["isDry"]
        self.assertEqual(is_dry["type"], "boolean")
        self.assertEqual(is_dry["counts"], {"True": 2, "False": 1})

    def test_categorical_field_distribution(self):
        summary = gf.summarize(self._records())
        source = summary["fields"]["source"]
        self.assertEqual(source["type"], "categorical")
        self.assertEqual(source["distribution"], {"App": 2, "Site": 1})

    def test_free_text_field_over_cardinality_cap(self):
        records = [{"data": {"note": f"unique_{i}"}} for i in range(gf.CATEGORICAL_CARDINALITY_CAP + 1)]
        summary = gf.summarize(records)
        self.assertEqual(summary["fields"]["note"]["type"], "free_text")

    def test_geographic_spread(self):
        summary = gf.summarize(self._records())
        spread = summary["geographic_spread"]
        self.assertEqual(spread["unique_sites"], 3)
        self.assertEqual(spread["unique_countries"], 2)
        self.assertEqual(spread["top_countries"]["PHL"], 2)

    def test_date_coverage(self):
        summary = gf.summarize(self._records())
        coverage = summary["date_coverage_observed"]
        self.assertEqual(coverage["min"], "2024-06-01")
        self.assertEqual(coverage["max"], "2024-06-15")


def _skip_if_unreachable(test_case, fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except gf.GlobeFetchError as exc:
        test_case.skipTest(f"GLOBE API unreachable or errored: {exc}")
    except urllib.error.URLError as exc:
        test_case.skipTest(f"Network unavailable: {exc}")


class TestLiveSmoke(unittest.TestCase):
    """Hits the real GLOBE API. Skips (not fails) on network trouble."""

    def test_bbox_endpoint_returns_data(self):
        args = make_args(bbox="5,20,115,130")
        result = _skip_if_unreachable(self, gf.run, args)
        self.assertIn("records", result)
        self.assertEqual(result["query"]["mode"], "sample")

    def test_country_endpoint_returns_data(self):
        args = make_args(country="PHL")
        result = _skip_if_unreachable(self, gf.run, args)
        self.assertIn("records", result)
        self.assertEqual(result["query"]["location"], "country(PHL)")

    def test_place_endpoint_returns_data(self):
        args = make_args(protocol=["land_covers"], start="2023-01-01", end="2023-12-31", place="alps")
        result = _skip_if_unreachable(self, gf.run, args)
        self.assertIn("records", result)

    def test_summarize_end_to_end(self):
        args = make_args(protocol=["land_covers"], start="2023-01-01", end="2023-12-31",
                          place="alps", full=True, summarize=True)
        result = _skip_if_unreachable(self, gf.run, args)
        self.assertIn("summary", result)
        self.assertGreater(result["summary"]["records_summarized"], 0)

    def test_pagination_offsets_are_disjoint(self):
        params_a = {"protocols": ["mosquito_habitat_mapper"], "startdate": "2020-01-01",
                    "enddate": "2024-12-31", "geojson": "FALSE", "countrycode": "PHL",
                    "sample": "FALSE", "size": 50, "from": 0}
        params_b = {**params_a, "from": 50}
        _, page_a = _skip_if_unreachable(self, gf.fetch_page, "country/", params_a)
        _, page_b = _skip_if_unreachable(self, gf.fetch_page, "country/", params_b)
        ids_a = {r.get("pid") for r in page_a}
        ids_b = {r.get("pid") for r in page_b}
        self.assertTrue(ids_a, "expected page A to have results")
        self.assertTrue(ids_b, "expected page B to have results")
        self.assertEqual(ids_a & ids_b, set(), "pages at different offsets should not overlap")


if __name__ == "__main__":
    unittest.main()
