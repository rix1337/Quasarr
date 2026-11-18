import unittest
from datetime import datetime
from json import dumps, loads
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from quasarr.constants import (
    SEARCH_CAT_MOVIES,
    SEARCH_CAT_MOVIES_HD,
    SEARCH_CAT_SHOWS,
)
from quasarr.providers.imdb_metadata import (
    IMDbHTML,
    _localized_titles_from_arr_record,
    get_imdb_id_from_title,
    get_imdb_metadata,
    get_localized_title,
)
from quasarr.providers.radarr_api import RadarrAPIClient
from quasarr.providers.sonarr_api import SonarrAPIClient


class FakeDB:
    def __init__(self):
        self.values = {}

    def retrieve(self, key):
        return self.values.get(key)

    def update_store(self, key, value):
        self.values[key] = value


class FakeSharedState:
    def __init__(self, radarr=None, sonarr=None):
        self.values = {
            "radarr_client": radarr,
            "sonarr_client": sonarr,
        }

    def update(self, key, value):
        self.values[key] = value


class IMDbMetadataTests(unittest.TestCase):
    def setUp(self):
        self.databases = {
            "imdb_metadata": FakeDB(),
            "imdb_searches": FakeDB(),
        }
        self.db_patch = patch(
            "quasarr.providers.imdb_metadata._get_db",
            side_effect=lambda table: self.databases.setdefault(table, FakeDB()),
        )
        self.db_patch.start()

    def tearDown(self):
        self.db_patch.stop()

    def test_movie_metadata_uses_radarr_title_year_and_remote_poster(self):
        radarr = MagicMock()
        radarr.movie_lookup_imdb.return_value = {
            "title": "Synthetic Movie",
            "year": 2032,
            "remotePoster": "https://images.invalid/poster.jpg",
            "alternateTitles": [{"title": "Unlabelled German Guess"}],
        }
        sonarr = MagicMock()
        state = FakeSharedState(radarr=radarr, sonarr=sonarr)

        metadata = get_imdb_metadata(state, "tt0000001", SEARCH_CAT_MOVIES)

        self.assertEqual("Synthetic Movie", metadata["title"])
        self.assertEqual(2032, metadata["year"])
        self.assertEqual("https://images.invalid/poster.jpg", metadata["poster_link"])
        self.assertEqual({}, metadata["localized"])
        radarr.movie_lookup_imdb.assert_called_once_with("tt0000001")
        sonarr.series_lookup_imdb.assert_not_called()

    def test_tv_metadata_uses_sonarr_only(self):
        radarr = MagicMock()
        sonarr = MagicMock()
        sonarr.series_lookup_imdb.return_value = {
            "title": "Synthetic Series",
            "year": 2031,
            "images": [
                {
                    "coverType": "poster",
                    "remoteUrl": "https://images.invalid/series.jpg",
                }
            ],
        }
        state = FakeSharedState(radarr=radarr, sonarr=sonarr)

        metadata = get_imdb_metadata(state, "tt0000002", SEARCH_CAT_SHOWS)

        self.assertEqual("Synthetic Series", metadata["title"])
        self.assertEqual(2031, metadata["year"])
        sonarr.series_lookup_imdb.assert_called_once_with("tt0000002")
        radarr.movie_lookup_imdb.assert_not_called()

    def test_arr_refresh_preserves_html_localized_cache(self):
        self.databases["imdb_metadata"].values["tt0000003"] = dumps(
            {
                "title": "Old Base Title",
                "year": 2029,
                "poster_link": None,
                "localized": {"de": "Synthetic German Title"},
                "ttl": datetime.now().timestamp() - 1,
            }
        )
        radarr = MagicMock()
        radarr.movie_lookup_imdb.return_value = {
            "title": "New Base Title",
            "year": 2030,
            "alternateTitles": [{"title": "Unlabelled Guess"}],
        }

        metadata = get_imdb_metadata(
            FakeSharedState(radarr=radarr), "tt0000003", SEARCH_CAT_MOVIES
        )

        self.assertEqual("New Base Title", metadata["title"])
        self.assertEqual("Synthetic German Title", metadata["localized"]["de"])
        stored = loads(self.databases["imdb_metadata"].values["tt0000003"])
        self.assertEqual("Synthetic German Title", stored["localized"]["de"])

    def test_localized_title_always_uses_html_without_proven_arr_locale(self):
        state = FakeSharedState()
        cached = {
            "title": "Configured Arr Display Title",
            "localized": {},
        }
        with (
            patch(
                "quasarr.providers.imdb_metadata._get_cached_metadata",
                return_value=cached,
            ),
            patch.object(
                IMDbHTML, "get_localized_title", return_value="Synthetic German Title"
            ) as html_lookup,
            patch("quasarr.providers.imdb_metadata._update_cache") as update_cache,
        ):
            title = get_localized_title(state, "tt0000004", "de")

        self.assertEqual("Synthetic German Title", title)
        html_lookup.assert_called_once_with("tt0000004", "de", deadline=None)
        update_cache.assert_called_once_with(
            "tt0000004", "localized", "Synthetic German Title", "de"
        )

    def test_german_localized_title_is_canonical_for_every_source(self):
        state = FakeSharedState()
        cached = {
            "title": "Synthetic Base Title",
            "localized": {},
        }
        with (
            patch(
                "quasarr.providers.imdb_metadata._get_cached_metadata",
                return_value=cached,
            ),
            patch.object(
                IMDbHTML,
                "get_localized_title",
                return_value="Synthetic ÄÖÜ ß Title",
            ),
            patch("quasarr.providers.imdb_metadata._update_cache") as update_cache,
        ):
            title = get_localized_title(state, "tt0000008", "de")

        self.assertEqual("Synthetic AeOeUe ss Title", title)
        update_cache.assert_called_once_with(
            "tt0000008", "localized", "Synthetic ÄÖÜ ß Title", "de"
        )

    def test_german_cached_title_is_canonicalized_before_return(self):
        cached = {
            "title": "Synthetic Base Title",
            "localized": {"de": "Synthetic Ümlaut Title"},
            "ttl": datetime.now().timestamp() + 60,
        }
        with (
            patch(
                "quasarr.providers.imdb_metadata._get_cached_metadata",
                return_value=cached,
            ),
            patch.object(IMDbHTML, "get_localized_title") as html_lookup,
        ):
            title = get_localized_title(FakeSharedState(), "tt0000009", "de")

        self.assertEqual("Synthetic Uemlaut Title", title)
        html_lookup.assert_not_called()

    def test_non_german_title_does_not_apply_german_transliteration(self):
        cached = {
            "title": "Synthetic Base Title",
            "localized": {"fr": "Synthetic Ü Title"},
            "ttl": datetime.now().timestamp() + 60,
        }

        with patch(
            "quasarr.providers.imdb_metadata._get_cached_metadata",
            return_value=cached,
        ):
            title = get_localized_title(FakeSharedState(), "tt0000010", "fr")

        self.assertEqual("Synthetic Ü Title", title)

    def test_missing_localized_title_does_not_fallback_to_arr_base_title(self):
        cached = {"title": "Synthetic Arr Base Title", "localized": {}}
        with (
            patch(
                "quasarr.providers.imdb_metadata._get_cached_metadata",
                return_value=cached,
            ),
            patch.object(IMDbHTML, "get_localized_title", return_value=None),
            patch("quasarr.providers.imdb_metadata.warn") as log_warn,
        ):
            title = get_localized_title(FakeSharedState(), "tt0000011", "de")

        self.assertIsNone(title)
        log_warn.assert_called_once_with(
            "Could not get localized title for tt0000011 in de"
        )

    def test_stale_localized_cache_is_refreshed_from_html(self):
        self.databases["imdb_metadata"].values["tt0000007"] = dumps(
            {
                "title": "Base Title",
                "year": 2030,
                "poster_link": None,
                "localized": {"de": "Stale Synthetic Title"},
                "ttl": datetime.now().timestamp() - 1,
            }
        )
        radarr = MagicMock()
        radarr.movie_lookup_imdb.return_value = {
            "title": "Base Title",
            "year": 2030,
        }
        state = FakeSharedState(radarr=radarr)

        with patch.object(
            IMDbHTML, "get_localized_title", return_value="Fresh Synthetic Title"
        ) as html_lookup:
            title = get_localized_title(state, "tt0000007", "de", SEARCH_CAT_MOVIES)

        self.assertEqual("Fresh Synthetic Title", title)
        html_lookup.assert_called_once_with("tt0000007", "de", deadline=None)
        stored = loads(self.databases["imdb_metadata"].values["tt0000007"])
        self.assertEqual("Fresh Synthetic Title", stored["localized"]["de"])

    def test_cold_tv_localized_title_uses_only_sonarr_for_base_metadata(self):
        radarr = MagicMock()
        sonarr = MagicMock()
        sonarr.series_lookup_imdb.return_value = {
            "title": "Synthetic Series",
            "year": 2033,
        }
        state = FakeSharedState(radarr=radarr, sonarr=sonarr)

        with patch.object(
            IMDbHTML, "get_localized_title", return_value="Synthetic Localized Series"
        ):
            # Custom TV categories must retain Sonarr routing after base resolution.
            title = get_localized_title(state, "tt0000012", "de", 105040)

        self.assertEqual("Synthetic Localized Series", title)
        sonarr.series_lookup_imdb.assert_called_once_with("tt0000012")
        radarr.movie_lookup_imdb.assert_not_called()

    def test_cold_arr_language_coded_title_skips_html_lookup(self):
        radarr = MagicMock()
        radarr.movie_lookup_imdb.return_value = {
            "title": "Synthetic Movie",
            "year": 2034,
            "alternateTitles": [
                {
                    "title": "Synthetic German Alternate",
                    "languageCode": "de",
                }
            ],
        }
        state = FakeSharedState(radarr=radarr)

        with patch.object(IMDbHTML, "get_localized_title") as html_lookup:
            title = get_localized_title(state, "tt0000014", "de", SEARCH_CAT_MOVIES)

        self.assertEqual("Synthetic German Alternate", title)
        radarr.movie_lookup_imdb.assert_called_once_with("tt0000014")
        html_lookup.assert_not_called()

    def test_cold_arr_english_original_title_skips_html_lookup(self):
        radarr = MagicMock()
        radarr.movie_lookup_imdb.return_value = {
            "title": "Synthetischer Anzeigetitel",
            "year": 2035,
            "originalTitle": "Synthetic Original Movie",
            "originalLanguage": {"id": 1, "name": "English"},
            "alternateTitles": [{"sourceType": "tmdb", "title": "Unlabelled Guess"}],
        }
        state = FakeSharedState(radarr=radarr)

        with patch.object(IMDbHTML, "get_localized_title") as html_lookup:
            title = get_localized_title(state, "tt0000017", "en", SEARCH_CAT_MOVIES)

        # The instance's localized display title must not be used for en - only
        # the language-proven originalTitle qualifies.
        self.assertEqual("Synthetic Original Movie", title)
        html_lookup.assert_not_called()

    def test_cold_sonarr_english_original_seeds_en_from_title(self):
        radarr = MagicMock()
        sonarr = MagicMock()
        sonarr.series_lookup_imdb.return_value = {
            "title": "Synthetic Series Title",
            "year": 2036,
            "originalLanguage": {"id": 1, "name": "English"},
        }
        state = FakeSharedState(radarr=radarr, sonarr=sonarr)

        with patch.object(IMDbHTML, "get_localized_title") as html_lookup:
            title = get_localized_title(state, "tt0000018", "en", SEARCH_CAT_SHOWS)

        # Sonarr's AlternateTitleResource has no originalTitle, so title is used.
        self.assertEqual("Synthetic Series Title", title)
        html_lookup.assert_not_called()

    def test_cold_arr_non_english_original_falls_back_to_html_for_en(self):
        radarr = MagicMock()
        radarr.movie_lookup_imdb.return_value = {
            "title": "Synthetic Anime",
            "year": 2037,
            "originalTitle": "Synthetic Original Anime",
            "originalLanguage": {"id": 8, "name": "Japanese"},
        }
        state = FakeSharedState(radarr=radarr)

        with patch.object(
            IMDbHTML,
            "get_localized_title",
            return_value="Synthetic English Anime Title",
        ) as html_lookup:
            title = get_localized_title(state, "tt0000019", "en", SEARCH_CAT_MOVIES)

        self.assertEqual("Synthetic English Anime Title", title)
        html_lookup.assert_called_once_with("tt0000019", "en", deadline=None)

    def test_arr_original_language_seeds_matching_code_only(self):
        record = {
            "title": "Synthetic Anime",
            "year": 2037,
            "originalTitle": "Synthetic Original Anime",
            "originalLanguage": {"id": 8, "name": "Japanese"},
        }

        self.assertEqual(
            {"ja": "Synthetic Original Anime"},
            _localized_titles_from_arr_record(record),
        )
        self.assertEqual({}, _localized_titles_from_arr_record({"title": "No Lang"}))
        self.assertEqual(
            {"de": "Synthetischer Originaltitel"},
            _localized_titles_from_arr_record(
                {
                    "title": "Synthetic Display Title",
                    "originalTitle": "Synthetischer Originaltitel",
                    "originalLanguage": {"id": 4, "name": "German"},
                }
            ),
        )
        self.assertEqual(
            {"fr": "Titre Original Synthetique"},
            _localized_titles_from_arr_record(
                {
                    "title": "Synthetic Display Title",
                    "originalTitle": "Titre Original Synthetique",
                    "originalLanguage": {"id": 2, "name": "French"},
                }
            ),
        )

    def test_cold_movie_localized_title_uses_only_radarr_for_base_metadata(self):
        radarr = MagicMock()
        radarr.movie_lookup_imdb.return_value = {
            "title": "Synthetic Movie",
            "year": 2034,
        }
        sonarr = MagicMock()
        state = FakeSharedState(radarr=radarr, sonarr=sonarr)

        with patch.object(
            IMDbHTML, "get_localized_title", return_value="Synthetic Localized Movie"
        ):
            title = get_localized_title(state, "tt0000013", "de", SEARCH_CAT_MOVIES_HD)

        self.assertEqual("Synthetic Localized Movie", title)
        radarr.movie_lookup_imdb.assert_called_once_with("tt0000013")
        sonarr.series_lookup_imdb.assert_not_called()

    def test_html_parser_rejects_page_title_without_country_aka(self):
        payload = {
            "props": {
                "pageProps": {
                    "contentData": {
                        "entityMetadata": {
                            "titleText": {"text": "Synthetic Localized Title"}
                        }
                    }
                }
            }
        }
        html = (
            '<html><script id="__NEXT_DATA__" type="application/json">'
            f"{dumps(payload)}"
            "</script></html>"
        )

        self.assertIsNone(IMDbHTML._parse_localized_title(html, "de"))

    def test_html_parser_uses_country_aka_instead_of_page_title(self):
        payload = {
            "props": {
                "pageProps": {
                    "contentData": {
                        "entityMetadata": {
                            "titleText": {"text": "Synthetic Original Title"}
                        }
                    }
                }
            }
        }
        html = (
            '<html><script id="__NEXT_DATA__" type="application/json">'
            f"{dumps(payload)}"
            "</script>"
            '<section data-testid="sub-section-akas"><ul><li>'
            "<span>Germany</span><span>Synthetic German Title</span>"
            "</li></ul></section></html>"
        )

        self.assertEqual(
            "Synthetic German Title", IMDbHTML._parse_localized_title(html, "de")
        )

    def test_html_parser_uses_iso_country_code_from_embedded_aka(self):
        payload = {
            "props": {
                "pageProps": {
                    "contentData": {
                        "data": {
                            "title": {
                                "akas": {
                                    "edges": [
                                        {
                                            "node": {
                                                "country": {
                                                    "id": "DE",
                                                    "text": "Synthetic Country Label",
                                                },
                                                "displayableProperty": {
                                                    "value": {
                                                        "plainText": "Synthetic German Title"
                                                    }
                                                },
                                            }
                                        }
                                    ]
                                }
                            }
                        }
                    }
                }
            }
        }
        html = (
            '<html><script id="__NEXT_DATA__" type="application/json">'
            f"{dumps(payload)}"
            "</script></html>"
        )

        self.assertEqual(
            "Synthetic German Title", IMDbHTML._parse_localized_title(html, "de")
        )

    def test_html_parser_rejects_conflicting_language_in_multilingual_country(self):
        payload = {
            "props": {
                "pageProps": {
                    "contentData": {
                        "data": {
                            "title": {
                                "akas": {
                                    "edges": [
                                        {
                                            "node": {
                                                "country": {"id": "CA"},
                                                "language": {"id": "en"},
                                                "displayableProperty": {
                                                    "value": {
                                                        "plainText": "Synthetic English Title"
                                                    }
                                                },
                                            }
                                        },
                                        {
                                            "node": {
                                                "country": {"id": "CA"},
                                                "language": {"id": "fr"},
                                                "displayableProperty": {
                                                    "value": {
                                                        "plainText": "Synthetic French Title"
                                                    }
                                                },
                                            }
                                        },
                                    ]
                                }
                            }
                        }
                    }
                }
            }
        }
        html = (
            '<html><script id="__NEXT_DATA__" type="application/json">'
            f"{dumps(payload)}"
            "</script></html>"
        )

        self.assertEqual(
            "Synthetic French Title", IMDbHTML._parse_localized_title(html, "fr")
        )

    def test_html_parser_prefers_visible_aka_over_proven_page_title(self):
        payload = {
            "props": {
                "pageProps": {
                    "requestContext": {
                        "sidecar": {
                            "localizationResponse": {
                                "userLanguage": "de-DE",
                                "isFullLocalizationEnabled": True,
                                "isOriginalTitlePreferenceSet": False,
                            }
                        }
                    },
                    "contentData": {
                        "entityMetadata": {
                            "titleText": {"text": "Synthetic German Display Title"}
                        }
                    },
                }
            }
        }
        html = (
            '<html><script id="__NEXT_DATA__" type="application/json">'
            f"{dumps(payload)}"
            "</script>"
            '<section data-testid="sub-section-akas"><ul><li>'
            "<span>Germany</span><span>Synthetic Explicit German AKA</span>"
            "</li></ul></section></html>"
        )

        self.assertEqual(
            "Synthetic Explicit German AKA",
            IMDbHTML._parse_localized_title(html, "de"),
        )

    def test_html_parser_skips_conflicting_visible_country_qualifier(self):
        html = (
            '<section data-testid="sub-section-akas"><ul>'
            "<li><span>Canada</span><span>Synthetic English Title</span>"
            "<span>(English)</span></li>"
            "<li><span>Canada</span><span>Synthetic French Title</span>"
            "<span>(French)</span></li>"
            "</ul></section>"
        )

        self.assertEqual(
            "Synthetic French Title", IMDbHTML._parse_localized_title(html, "fr")
        )

    def test_html_parser_uses_title_text_only_with_proven_locale_context(self):
        payload = {
            "props": {
                "pageProps": {
                    "requestContext": {
                        "sidecar": {
                            "localizationResponse": {
                                "userLanguage": "de-DE",
                                "isFullLocalizationEnabled": True,
                                "isOriginalTitlePreferenceSet": False,
                            }
                        }
                    },
                    "contentData": {
                        "entityMetadata": {
                            "titleText": {"text": "Synthetic German Display Title"}
                        }
                    },
                }
            }
        }
        html = (
            '<html><script id="__NEXT_DATA__" type="application/json">'
            f"{dumps(payload)}"
            "</script></html>"
        )

        self.assertEqual(
            "Synthetic German Display Title",
            IMDbHTML._parse_localized_title(html, "de"),
        )

    def test_html_parser_rejects_title_text_with_unproven_locale_context(self):
        localization_cases = (
            {
                "userLanguage": "en-US",
                "isFullLocalizationEnabled": True,
                "isOriginalTitlePreferenceSet": False,
            },
            {
                "userLanguage": "de-DE",
                "isFullLocalizationEnabled": False,
                "isOriginalTitlePreferenceSet": False,
            },
            {
                "userLanguage": "de-DE",
                "isFullLocalizationEnabled": True,
                "isOriginalTitlePreferenceSet": True,
            },
        )
        for localization in localization_cases:
            with self.subTest(localization=localization):
                payload = {
                    "props": {
                        "pageProps": {
                            "requestContext": {
                                "sidecar": {"localizationResponse": localization}
                            },
                            "contentData": {
                                "entityMetadata": {
                                    "titleText": {
                                        "text": "Synthetic Unproven Display Title"
                                    }
                                }
                            },
                        }
                    }
                }
                html = (
                    '<html><script id="__NEXT_DATA__" type="application/json">'
                    f"{dumps(payload)}"
                    "</script></html>"
                )

                self.assertIsNone(IMDbHTML._parse_localized_title(html, "de"))

    def test_html_lookup_uses_explicit_locale_path(self):
        with patch.object(IMDbHTML, "_request", return_value=None) as request:
            self.assertIsNone(IMDbHTML.get_localized_title("tt0000015", "de"))

        request.assert_called_once_with(
            "https://www.imdb.com/de/title/tt0000015/releaseinfo/", "de", deadline=None
        )

    def test_html_lookup_en_uses_unprefixed_default_path(self):
        with patch.object(IMDbHTML, "_request", return_value=None) as request:
            self.assertIsNone(IMDbHTML.get_localized_title("tt0000016", "en"))

        request.assert_called_once_with(
            "https://www.imdb.com/title/tt0000016/releaseinfo/", "en", deadline=None
        )

    def test_html_request_sets_explicit_locale_and_crawler_user_agent(self):
        html = (
            '<section data-testid="sub-section-akas"><ul><li>'
            "<span>Germany</span><span>Synthetic German Title</span>"
            "</li></ul></section>"
        )
        response = SimpleNamespace(status_code=200, text=html)
        with patch(
            "quasarr.providers.imdb_metadata.requests.get", return_value=response
        ) as request_get:
            result = IMDbHTML._request("https://metadata.invalid/releaseinfo/", "de")

        self.assertEqual(html, result)
        headers = request_get.call_args.kwargs["headers"]
        self.assertEqual("de-DE,de;q=0.9,en;q=0.8", headers["Accept-Language"])
        self.assertIn("Applebot", headers["User-Agent"])

    def test_html_request_retries_transport_when_direct_page_has_no_aka(self):
        direct_response = SimpleNamespace(
            status_code=200, text="<html>Synthetic Page Title Only</html>"
        )
        solver_html = (
            '<section data-testid="sub-section-akas"><ul><li>'
            "<span>Germany</span><span>Synthetic German Title</span>"
            "</li></ul></section>"
        )
        solver_response = SimpleNamespace(
            status_code=200,
            json=lambda: {
                "status": "ok",
                "solution": {"response": solver_html},
            },
        )
        database = MagicMock()
        database.retrieve.return_value = None
        with (
            patch(
                "quasarr.providers.imdb_metadata.requests.get",
                return_value=direct_response,
            ),
            patch(
                "quasarr.providers.imdb_metadata.requests.post",
                return_value=solver_response,
            ) as solver_request,
            patch(
                "quasarr.providers.imdb_metadata._get_config",
                return_value={"url": "https://solver.invalid"},
            ),
            patch("quasarr.providers.imdb_metadata._get_db", return_value=database),
        ):
            result = IMDbHTML._request("https://metadata.invalid/releaseinfo/", "de")

        self.assertEqual(solver_html, result)
        solver_request.assert_called_once()

    def test_title_lookup_uses_radarr_for_movies_and_sonarr_for_series(self):
        radarr = MagicMock()
        radarr.movie_lookup.return_value = [
            {"title": "Synthetic Movie", "imdbId": "tt0000005"}
        ]
        sonarr = MagicMock()
        sonarr.series_lookup.return_value = [
            {"title": "Synthetic Series", "imdbId": "tt0000006"}
        ]
        state = FakeSharedState(radarr=radarr, sonarr=sonarr)

        movie_id = get_imdb_id_from_title(state, "Synthetic.Movie.2030")
        series_id = get_imdb_id_from_title(state, "Synthetic.Series.S01E02")

        self.assertEqual("tt0000005", movie_id)
        self.assertEqual("tt0000006", series_id)
        radarr.movie_lookup.assert_called_once_with("Synthetic Movie 2030")
        sonarr.series_lookup.assert_called_once_with("Synthetic Series")


class ArrClientLookupTests(unittest.TestCase):
    def test_radarr_title_lookup_uses_movie_lookup_endpoint(self):
        client = RadarrAPIClient("https://radarr.invalid", "synthetic-key")
        with patch.object(client, "_get", return_value=[]) as request_get:
            self.assertEqual([], client.movie_lookup("Synthetic Movie"))
        request_get.assert_called_once_with(
            "/movie/lookup", params={"term": "Synthetic Movie"}
        )

    def test_sonarr_title_lookup_uses_series_lookup_endpoint(self):
        client = SonarrAPIClient("https://sonarr.invalid", "synthetic-key")
        with patch.object(client, "_get", return_value=[]) as request_get:
            self.assertEqual([], client.series_lookup("Synthetic Series"))
        request_get.assert_called_once_with(
            "/series/lookup", params={"term": "Synthetic Series"}
        )


if __name__ == "__main__":
    unittest.main()
