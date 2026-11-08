import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from quasarr.search.sources.templates.sf import search as sf

SEASON_HTML = """
<div class="entry">
<div class="row">
<div class="col">
<h3><label class="opn" for="se1"></label>Staffel 1
<span class="morespec">1080p | 8 GB</span><span class="grouptag">GRP</span></h3>
<small>Synthetic.Show.S01.German.DL.1080p.WEB.h264-GRP</small>
</div>
</div>
<div class="row">
<a class="dlb row" href="/external/2/season-1f"><div class="col"><span>1fichier</span></div></a>
<a class="dlb row" href="/external/2/season-dd"><div class="col"><span>ddownload</span></div></a>
</div>
<div class="list simple">
<div class="row head"><div>Nr.</div><div>Titel</div><div>Download</div></div>
<div class="row"><div>1.</div><div>Synthetic Episode One</div>
<div class="row">
<a class="dlb row" href="/external/2/ep1-1f"><div class="col"><span>1F</span></div></a>
<a class="dlb row" href="/external/2/ep1-dd"><div class="col"><span>DD</span></div></a>
</div>
</div>
<div class="row"><div>2.</div><div>Synthetic Episode Two</div>
<div class="row">
<a class="dlb row" href="/external/2/ep2-1f"><div class="col"><span>1F</span></div></a>
<a class="dlb row" href="/external/2/ep2-dd"><div class="col"><span>DD</span></div></a>
</div>
</div>
</div>
</div>
"""

SERIES_PAGE = """
<html><body>
<a href="https://www.imdb.com/title/tt1234567/">IMDb</a>
<script>initSeason('synthetic-season-id', 1);</script>
</body></html>
"""

SEARCH_API_PAYLOAD = {
    "result": [{"title": "Synthetic Show", "url_id": "synthetic-show"}]
}

SEASON_TITLE = "Synthetic.Show.S01.German.DL.1080p.WEB.h264-GRP"
EPISODE_TITLE = "Synthetic.Show.S01E02.German.DL.1080p.WEB.h264-GRP"


class FakeResponse:
    def __init__(self, text="", payload=None):
        self.text = text
        self.status_code = 200
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


class FakeCfSession:
    """Serves the three requests _search makes: search API, series page, season API."""

    def __init__(self):
        self.requested_urls = []

    def get(self, url, headers, timeout, request_get=None):
        self.requested_urls.append(url)
        if "/api/v2/search" in url:
            return FakeResponse(payload=SEARCH_API_PAYLOAD)
        if "/api/v1/" in url:
            return FakeResponse(payload={"html": SEASON_HTML})
        return FakeResponse(text=SERIES_PAGE)


def fake_shared_state():
    return SimpleNamespace(
        values={
            "config": lambda section: {"sf": "sf.invalid"},
            "user_agent": "UA",
        },
        update=lambda *args, **kwargs: None,
    )


def run_search(episode):
    """Run _search with a fake session; returns (releases, generate_download_link mock)."""
    link_maker = MagicMock(return_value="http://quasarr.invalid/download/?payload=x")
    with (
        patch.object(sf, "get_recently_searched", return_value={}),
        patch.object(sf, "is_valid_release", return_value=True),
        patch.object(sf, "generate_download_link", link_maker),
        patch.object(sf, "clear_hostname_issue"),
        patch.object(sf, "mark_hostname_issue"),
    ):
        releases = sf.Source()._search(
            fake_shared_state(),
            0.0,
            "5000",
            "Synthetic Show",
            1,
            episode,
            FakeCfSession(),
        )
    return releases, link_maker


class SfEpisodeSearchTests(unittest.TestCase):
    def _source_passed_to_download_link(self, link_maker):
        # generate_download_link(shared_state, title, source, mb, password, ...)
        return link_maker.call_args.args[2]

    def test_string_episode_yields_per_episode_release(self):
        # Sonarr's newznab "ep" parameter arrives as a STRING (it comes straight
        # from request.query.ep and is never coerced on the way in). Formatting
        # it with :02d without an int() cast raises ValueError, which the broad
        # except swallowed - silently dropping the entire release, so every
        # episode search returned nothing at all.
        releases, link_maker = run_search("2")

        self.assertEqual(len(releases), 1)
        self.assertEqual(releases[0]["details"]["title"], EPISODE_TITLE)
        # The per-episode container must be grabbed, not the whole-season one.
        self.assertEqual(
            self._source_passed_to_download_link(link_maker),
            "https://sf.invalid/external/2/ep2-1f",
        )

    def test_int_episode_yields_same_result_as_string(self):
        # The q-as-episode code path in api/arr hands over an int, so both types
        # reach this code and must behave identically.
        releases, link_maker = run_search(2)

        self.assertEqual(len(releases), 1)
        self.assertEqual(releases[0]["details"]["title"], EPISODE_TITLE)
        self.assertEqual(
            self._source_passed_to_download_link(link_maker),
            "https://sf.invalid/external/2/ep2-1f",
        )

    def test_episode_release_size_is_pack_size_divided_by_episode_count(self):
        # The pack advertises one size for all episodes; a single-episode
        # release must report its share (8 GB / 2 episodes = 4 GB).
        releases, _ = run_search("2")

        self.assertEqual(releases[0]["details"]["size"], 4096 * 1024 * 1024)

    def test_season_search_still_returns_the_full_pack(self):
        # Legacy path: without an episode the season container is returned
        # unchanged and the title keeps its plain S01 form.
        releases, link_maker = run_search(None)

        self.assertEqual(len(releases), 1)
        self.assertEqual(releases[0]["details"]["title"], SEASON_TITLE)
        self.assertEqual(
            self._source_passed_to_download_link(link_maker),
            "https://sf.invalid/external/2/season-1f",
        )


if __name__ == "__main__":
    unittest.main()
