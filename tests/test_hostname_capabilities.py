import inspect
import unittest

from quasarr.constants import SEARCH_CAT_SHOWS
from quasarr.providers.html_images import FLAG_SVGS, LANGUAGE_FLAG_EMOJI
from quasarr.search.sources import get_sources
from quasarr.search.sources.helpers import get_source_metadata
from quasarr.storage.setup.hostnames import (
    _capabilities_html,
    _language_flag_html,
)

# Languages the editor knows how to render a flag for. Every source must declare
# one of these so its row gets a flag instead of a blank.
ALLOWED_LANGUAGES = {"de", "en", "fr"}


class SourceLanguageContractTests(unittest.TestCase):
    def test_every_source_declares_a_known_language(self):
        for key, source in get_sources().items():
            with self.subTest(source=key):
                self.assertIn(
                    source.language,
                    ALLOWED_LANGUAGES,
                    f"{key.upper()} declares unsupported language {source.language!r}",
                )

    def test_flag_assets_cover_every_used_language(self):
        used = {source.language for source in get_sources().values()}
        for language in used:
            with self.subTest(language=language):
                self.assertIn(language, LANGUAGE_FLAG_EMOJI)
                self.assertIn(language, FLAG_SVGS)

    def test_date_numbering_sources_accept_shared_date_context(self):
        for key, source in get_sources().items():
            if (
                SEARCH_CAT_SHOWS not in source.supported_categories
                or not source.supports_date_numbering
            ):
                continue
            with self.subTest(source=key):
                self.assertIn(
                    "episode_date",
                    inspect.signature(source.search).parameters,
                )

    def test_date_numbering_enabled_for_all_compatible_tv_sources(self):
        expected = {
            "by",
            "dd",
            "dj",
            "dl",
            "dt",
            "dw",
            "fx",
            "he",
            "hs",
            "mb",
            "nk",
            "nx",
            "rm",
            "sf",
            "sj",
            "sl",
            "wd",
            "wx",
        }
        actual = {
            key
            for key, source in get_sources().items()
            if SEARCH_CAT_SHOWS in source.supported_categories
            and source.supports_date_numbering
        }
        self.assertEqual(expected, actual)


class SourceMetadataTests(unittest.TestCase):
    def test_metadata_exposes_expected_keys_for_every_source(self):
        expected_keys = {
            "language",
            "categories",
            "supports_imdb",
            "requires_login",
            "requires_account",
            "invite_only",
            "requires_flaresolverr",
            "requires_radarr",
            "requires_sonarr",
        }
        metadata = get_source_metadata()
        self.assertEqual(set(metadata), set(get_sources()))
        for key, meta in metadata.items():
            with self.subTest(source=key):
                self.assertEqual(set(meta), expected_keys)

    def test_metadata_mirrors_source_attributes(self):
        sources = get_sources()
        metadata = get_source_metadata()
        for key, meta in metadata.items():
            source = sources[key]
            with self.subTest(source=key):
                self.assertEqual(meta["language"], source.language)
                self.assertEqual(meta["categories"], list(source.supported_categories))
                self.assertEqual(meta["requires_login"], source.requires_login)
                self.assertEqual(meta["requires_account"], source.requires_account)
                self.assertEqual(meta["invite_only"], source.invite_only)
                self.assertEqual(
                    meta["requires_flaresolverr"], source.requires_flaresolverr
                )
                self.assertEqual(meta["requires_radarr"], source.requires_radarr)
                self.assertEqual(meta["requires_sonarr"], source.requires_sonarr)

    def test_metadata_marks_clear_flaresolverr_required_sources(self):
        metadata = get_source_metadata()
        self.assertTrue(metadata["al"]["requires_flaresolverr"])
        self.assertTrue(metadata["sl"]["requires_flaresolverr"])
        self.assertTrue(metadata["wd"]["requires_flaresolverr"])


class EditorRenderHelpersTests(unittest.TestCase):
    def test_language_flag_html_carries_swap_hook(self):
        html = _language_flag_html("fr")
        self.assertIn("data-flag", html)
        self.assertIn('data-lang="fr"', html)
        self.assertIn(LANGUAGE_FLAG_EMOJI["fr"], html)

    def test_language_flag_html_blank_for_unknown_language(self):
        self.assertEqual(_language_flag_html(None), "")
        self.assertEqual(_language_flag_html("xx"), "")

    def test_capabilities_html_blank_without_metadata(self):
        self.assertEqual(_capabilities_html({}), "")

    def test_capabilities_html_renders_invite_login_and_feed_chips(self):
        html = _capabilities_html(
            {
                "language": "en",
                "categories": [],
                "requires_login": True,
                "requires_account": True,
                "invite_only": True,
                "requires_flaresolverr": True,
                "requires_radarr": True,
                "requires_sonarr": True,
            }
        )
        # Invite-only sites still surface the login requirement (not hidden by it).
        self.assertIn("🔒 Invite Only", html)
        self.assertIn("🔑 Login Required", html)
        self.assertIn("🛡️ FlareSolverr Required", html)
        self.assertIn("📡 Radarr Required", html)
        self.assertIn("📡 Sonarr Required", html)
        self.assertLess(html.index('data-lang="en"'), html.index("🔒 Invite Only"))
        self.assertLess(html.index("🔒 Invite Only"), html.index("🔑 Login Required"))
        self.assertLess(
            html.index("🔑 Login Required"), html.index("🛡️ FlareSolverr Required")
        )

    def test_capabilities_html_account_without_login(self):
        html = _capabilities_html(
            {"categories": [], "requires_login": False, "requires_account": True}
        )
        self.assertIn("👤 Account Required", html)
        self.assertNotIn("🔑 Login Required", html)


if __name__ == "__main__":
    unittest.main()
