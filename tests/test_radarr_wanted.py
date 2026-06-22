import unittest
from types import SimpleNamespace

from quasarr.providers import radarr_api


class FakeClient:
    """Single-page client: all records on page 1, empty thereafter."""

    def __init__(self, missing, cutoff):
        self._records = {"missing": missing, "cutoff": cutoff}

    def wanted(self, kind, page=1, page_size=50):
        return {"records": self._records.get(kind, []) if page == 1 else []}


class PagedClient:
    """Client keyed by (kind, page) to exercise pagination."""

    def __init__(self, pages):
        self._pages = pages

    def wanted(self, kind, page=1, page_size=50):
        return {"records": self._pages.get((kind, page), [])}


def shared_state_with(client):
    return SimpleNamespace(values={"radarr_client": client})


class RadarrWantedTests(unittest.TestCase):
    def test_skips_unreleased_and_keeps_missing_first(self):
        missing = [
            {"imdbId": "tt1", "status": "announced"},  # not in cinemas yet -> skip
            {"imdbId": "tt2", "status": "inCinemas"},
            {"imdbId": "tt3", "status": "released"},
            {"imdbId": "tt4", "status": "tba"},  # skip
        ]
        cutoff = [
            {"imdbId": "tt3", "status": "released"},  # dupe of missing -> drop
            {"imdbId": "tt5", "status": "released"},
        ]
        ids = radarr_api.get_wanted_imdb_ids(
            shared_state_with(FakeClient(missing, cutoff))
        )
        self.assertEqual(ids, ["tt2", "tt3", "tt5"])

    def test_limit_caps_results(self):
        missing = [{"imdbId": f"tt{i}", "status": "released"} for i in range(10)]
        ids = radarr_api.get_wanted_imdb_ids(
            shared_state_with(FakeClient(missing, [])), limit=3
        )
        self.assertEqual(ids, ["tt0", "tt1", "tt2"])

    def test_pages_past_an_all_unreleased_page(self):
        # Page 1 is entirely announced; the released entry on page 2 must still
        # be picked up rather than yielding an empty seed.
        pages = {
            ("missing", 1): [
                {"imdbId": "tt1", "status": "announced"},
                {"imdbId": "tt2", "status": "tba"},
            ],
            ("missing", 2): [{"imdbId": "tt3", "status": "released"}],
        }
        ids = radarr_api.get_wanted_imdb_ids(
            shared_state_with(PagedClient(pages)), limit=5
        )
        self.assertEqual(ids, ["tt3"])

    def test_empty_without_client(self):
        self.assertEqual(radarr_api.get_wanted_imdb_ids(SimpleNamespace(values={})), [])


if __name__ == "__main__":
    unittest.main()
