import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from quasarr import downloads
from quasarr.downloads.sources import he

SOURCE_URL = "https://source.invalid/releases/synthetic/"
HOSTER_URL = "https://hoster.invalid/files/synthetic"
SYNTHETIC_TITLE = "Synthetic.Release.2031.1080p-GRP"

NORMAL_FORM_HTML = """
<form id="content-protector-access-form-synthetic">
  <input name="content-protector-captcha" value="1">
  <input name="content-protector-token" value="token">
  <input name="captcha_answer" value="" disabled>
  <input name="captcha_id" value="" disabled>
  <input name="altcha-payload" value="synthetic-proof">
</form>
"""

CAPTCHA_FORM_HTML = """
<form id="content-protector-access-form-synthetic">
  <input name="content-protector-captcha" value="1">
  <input name="content-protector-token" value="token">
  <input name="captcha_answer" value="">
  <input name="captcha_id" value="synthetic-captcha-id">
  <input name="altcha-payload" value="synthetic-proof">
</form>
"""

UNLOCKED_HTML = f"""
<div id="unlocked">
  <a href="{HOSTER_URL}">Download</a>
</div>
"""


class Response:
    status_code = 200

    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        return None


class Session:
    def __init__(self, get_html, post_html):
        self.get_html = get_html
        self.post_html = post_html
        self.post = Mock(side_effect=lambda *_args, **_kwargs: Response(post_html))

    def get(self, *_args, **_kwargs):
        return Response(self.get_html)


class HeCaptchaRoutingTests(unittest.TestCase):
    def test_standard_strategy_parks_active_captcha_without_posting(self):
        session = Session(CAPTCHA_FORM_HTML, UNLOCKED_HTML)

        with patch.object(he.requests, "Session", return_value=session):
            result = he._strategy_standard(SOURCE_URL, {"User-Agent": "test-agent"})

        self.assertEqual(
            {
                "links": [[SOURCE_URL, "he"]],
                "imdb_id": None,
                "protected": True,
            },
            result,
        )
        session.post.assert_not_called()

    def test_standard_strategy_keeps_automatic_unlock_path(self):
        session = Session(NORMAL_FORM_HTML, UNLOCKED_HTML)

        with patch.object(he.requests, "Session", return_value=session):
            result = he._strategy_standard(SOURCE_URL, {"User-Agent": "test-agent"})

        self.assertEqual(
            {"links": [[HOSTER_URL, "hoster"]], "imdb_id": None},
            result,
        )
        session.post.assert_called_once()

    def test_standard_strategy_parks_captcha_returned_after_post(self):
        session = Session(NORMAL_FORM_HTML, CAPTCHA_FORM_HTML)

        with patch.object(he.requests, "Session", return_value=session):
            result = he._strategy_standard(SOURCE_URL, {"User-Agent": "test-agent"})

        self.assertTrue(result["protected"])
        self.assertEqual([[SOURCE_URL, "he"]], result["links"])

    def test_standard_strategy_keeps_flaresolverr_fallback_after_form_submission_without_links(
        self,
    ):
        session = Session(NORMAL_FORM_HTML, "<html><body>No links</body></html>")

        with patch.object(he.requests, "Session", return_value=session):
            result = he._strategy_standard(SOURCE_URL, {"User-Agent": "test-agent"})

        self.assertEqual({"links": [], "imdb_id": None, "inconclusive": True}, result)
        session.post.assert_called_once()

    def test_flaresolverr_parks_captcha_returned_after_post(self):
        shared_state = SimpleNamespace()

        with (
            patch.object(he, "is_flaresolverr_available", return_value=True),
            patch.object(he, "flaresolverr_create_session", return_value="session"),
            patch.object(
                he, "flaresolverr_get", return_value=Response(NORMAL_FORM_HTML)
            ),
            patch.object(
                he, "flaresolverr_post", return_value=Response(CAPTCHA_FORM_HTML)
            ) as flaresolverr_post,
            patch.object(he, "flaresolverr_destroy_session"),
        ):
            result = he._strategy_flaresolverr_loop(shared_state, SOURCE_URL)

        self.assertTrue(result["protected"])
        self.assertEqual([[SOURCE_URL, "he"]], result["links"])
        flaresolverr_post.assert_called_once()

    def test_flaresolverr_keeps_automatic_unlock_path(self):
        shared_state = SimpleNamespace()

        with (
            patch.object(he, "is_flaresolverr_available", return_value=True),
            patch.object(he, "flaresolverr_create_session", return_value="session"),
            patch.object(
                he, "flaresolverr_get", return_value=Response(NORMAL_FORM_HTML)
            ),
            patch.object(he, "flaresolverr_post", return_value=Response(UNLOCKED_HTML)),
            patch.object(he, "flaresolverr_destroy_session"),
        ):
            result = he._strategy_flaresolverr_loop(shared_state, SOURCE_URL)

        self.assertEqual(
            {"links": [[HOSTER_URL, "hoster"]], "imdb_id": None},
            result,
        )

    def test_flaresolverr_parks_exhausted_form_submissions_without_links(self):
        shared_state = SimpleNamespace()

        with (
            patch.object(he, "is_flaresolverr_available", return_value=True),
            patch.object(he, "flaresolverr_create_session", return_value="session"),
            patch.object(
                he, "flaresolverr_get", return_value=Response(NORMAL_FORM_HTML)
            ),
            patch.object(
                he, "flaresolverr_post", return_value=Response(NORMAL_FORM_HTML)
            ) as flaresolverr_post,
            patch.object(he, "flaresolverr_destroy_session"),
        ):
            result = he._strategy_flaresolverr_loop(shared_state, SOURCE_URL)

        self.assertEqual(
            {
                "links": [[SOURCE_URL, "he"]],
                "imdb_id": None,
                "protected": True,
            },
            result,
        )
        self.assertEqual(2, flaresolverr_post.call_count)

    def test_flaresolverr_missing_initial_form_remains_failure(self):
        shared_state = SimpleNamespace()

        with (
            patch.object(he, "is_flaresolverr_available", return_value=True),
            patch.object(he, "flaresolverr_create_session", return_value="session"),
            patch.object(
                he,
                "flaresolverr_get",
                return_value=Response("<html><body>Blocked</body></html>"),
            ),
            patch.object(he, "flaresolverr_post") as flaresolverr_post,
            patch.object(he, "flaresolverr_destroy_session"),
        ):
            result = he._strategy_flaresolverr_loop(shared_state, SOURCE_URL)

        self.assertEqual({"links": [], "imdb_id": None}, result)
        flaresolverr_post.assert_not_called()

    def test_source_keeps_protected_page_despite_mirror_filter(self):
        protected_result = {
            "links": [[SOURCE_URL, "he"]],
            "imdb_id": None,
            "protected": True,
        }
        shared_state = SimpleNamespace(values={"user_agent": "test-agent"})

        with (
            patch.object(he, "_strategy_standard", return_value=protected_result),
            patch.object(he, "_strategy_flaresolverr_loop") as flaresolverr_loop,
        ):
            result = he.Source().get_download_links(
                shared_state,
                SOURCE_URL,
                ["hoster"],
                SYNTHETIC_TITLE,
                None,
            )

        self.assertEqual(protected_result, result)
        flaresolverr_loop.assert_not_called()

    def test_source_uses_flaresolverr_before_parking_inconclusive_standard_post(self):
        protected_result = {
            "links": [[SOURCE_URL, "he"]],
            "imdb_id": None,
            "protected": True,
        }
        shared_state = SimpleNamespace(values={"user_agent": "test-agent"})

        with (
            patch.object(he, "_strategy_standard", return_value=None),
            patch.object(
                he, "_strategy_flaresolverr_loop", return_value=protected_result
            ) as flaresolverr_loop,
        ):
            result = he.Source().get_download_links(
                shared_state,
                SOURCE_URL,
                ["hoster"],
                SYNTHETIC_TITLE,
                None,
            )

        self.assertEqual(protected_result, result)
        flaresolverr_loop.assert_called_once_with(shared_state, SOURCE_URL)

    def test_source_parks_inconclusive_standard_post_when_flaresolverr_unavailable(
        self,
    ):
        shared_state = SimpleNamespace(values={"user_agent": "test-agent"})
        inconclusive_result = {"links": [], "imdb_id": None, "inconclusive": True}

        with (
            patch.object(he, "_strategy_standard", return_value=inconclusive_result),
            patch.object(he, "is_flaresolverr_available", return_value=False),
            patch.object(he, "_strategy_flaresolverr_loop") as flaresolverr_loop,
        ):
            result = he.Source().get_download_links(
                shared_state,
                SOURCE_URL,
                ["hoster"],
                SYNTHETIC_TITLE,
                None,
            )

        self.assertTrue(result["protected"])
        self.assertEqual([[SOURCE_URL, "he"]], result["links"])
        flaresolverr_loop.assert_not_called()

    def test_source_parks_inconclusive_standard_post_when_flaresolverr_cannot_start(
        self,
    ):
        shared_state = SimpleNamespace(values={"user_agent": "test-agent"})
        inconclusive_result = {"links": [], "imdb_id": None, "inconclusive": True}

        with (
            patch.object(he, "_strategy_standard", return_value=inconclusive_result),
            patch.object(he, "is_flaresolverr_available", return_value=True),
            patch.object(
                he,
                "_strategy_flaresolverr_loop",
                return_value={"links": [], "imdb_id": None},
            ),
        ):
            result = he.Source().get_download_links(
                shared_state,
                SOURCE_URL,
                ["hoster"],
                SYNTHETIC_TITLE,
                None,
            )

        self.assertTrue(result["protected"])
        self.assertEqual([[SOURCE_URL, "he"]], result["links"])

    def test_process_links_stores_source_marked_protected(self):
        shared_state = SimpleNamespace(
            values={
                "external_address": "https://quasarr.invalid",
                "crypters_enabled": {},
            }
        )

        with (
            patch.object(
                downloads,
                "filter_offline_links",
                side_effect=lambda links, **_: links,
            ),
            patch.object(downloads, "handle_direct_links") as handle_direct,
            patch.object(downloads, "send_tracked_notification", return_value={}),
            patch.object(downloads, "store_protected_links") as store_protected,
        ):
            result = downloads.process_links(
                shared_state,
                {"links": [[SOURCE_URL, "he"]], "protected": True},
                SYNTHETIC_TITLE,
                None,
                "Quasarr_movies_0123456789abcdef0123456789abcdef",
                None,
                SOURCE_URL,
                1024,
                "HE",
            )

        self.assertTrue(result["success"])
        handle_direct.assert_not_called()
        self.assertEqual(
            [[SOURCE_URL, "he"]],
            store_protected.call_args.args[1],
        )


if __name__ == "__main__":
    unittest.main()
