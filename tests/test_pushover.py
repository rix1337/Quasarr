import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import requests

from quasarr.providers.notifications import (
    send_notification,
    send_tracked_notification,
    update_release_notification,
)
from quasarr.providers.notifications.helpers.notification_message import (
    NotificationFact,
    NotificationFactsEntry,
    NotificationLinkEntry,
    NotificationMessage,
    NotificationTextEntry,
)
from quasarr.providers.notifications.helpers.notification_types import NotificationType
from quasarr.providers.notifications.pushover import (
    MAX_MESSAGE_LENGTH,
    MAX_TITLE_LENGTH,
    PushoverNotificationFormatter,
    _build_attachment,
    send,
)


class _StreamingRaw:
    def __init__(self, content, read_error=None):
        self.content = content
        self.read_error = read_error
        self.read_calls = []

    def read(self, limit, decode_content=False):
        self.read_calls.append((limit, decode_content))
        if self.read_error:
            raise self.read_error
        return self.content[:limit]


class _StreamingResponse:
    def __init__(self, content_type, content, status_code=200, read_error=None):
        self.headers = {"Content-Type": content_type}
        self.raw = _StreamingRaw(content, read_error=read_error)
        self.status_code = status_code
        self.closed = False

    @property
    def content(self):
        raise AssertionError("streaming poster must not access response.content")

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError("synthetic HTTP failure")

    def close(self):
        self.closed = True


class PushoverSenderTests(unittest.TestCase):
    def setUp(self):
        self.shared_state = SimpleNamespace(
            values={
                "notification_settings": {
                    "pushover_api_token": "synthetic-token",
                    "pushover_user_key": "synthetic-user",
                }
            }
        )
        self.message = NotificationMessage(
            title="Synthetic title",
            description="Synthetic description",
            entries=(
                NotificationLinkEntry(
                    title="Details",
                    text="Open details",
                    link_text="details",
                    url="https://notification.invalid/item",
                ),
                NotificationFactsEntry(
                    title="Facts",
                    facts=(NotificationFact("Kind", "test"),),
                ),
            ),
        )

    def test_formatter_uses_headings_and_named_links_without_repeating_title(self):
        rendered = PushoverNotificationFormatter().render_message(self.message)

        self.assertEqual(
            "Synthetic description\n\n<b>Details</b>\n"
            '<a href="https://notification.invalid/item">Open details</a>\n\n'
            "<b>Facts</b>\n<b>Kind:</b> test",
            rendered,
        )

    def test_missing_credentials_skips_request(self):
        self.shared_state.values["notification_settings"]["pushover_user_key"] = ""
        with patch("quasarr.providers.notifications.pushover.requests.post") as post:
            self.assertFalse(send(self.shared_state, self.message))
        post.assert_not_called()

    @patch("quasarr.providers.notifications.pushover.requests.post")
    def test_success_posts_bounded_payload_and_silent_priority(self, post):
        response = Mock(status_code=200)
        response.json.return_value = {"status": 1}
        post.return_value = response

        self.assertTrue(send(self.shared_state, self.message, silent=True))

        payload = post.call_args.kwargs["data"]
        self.assertEqual(-2, payload["priority"])
        self.assertEqual("synthetic-token", payload["token"])
        self.assertEqual("synthetic-user", payload["user"])
        self.assertEqual(1, payload["html"])
        self.assertEqual("Synthetic title", payload["title"])
        self.assertNotIn("Synthetic title", payload["message"])
        self.assertLessEqual(len(payload["title"]), MAX_TITLE_LENGTH)
        self.assertLessEqual(len(payload["message"]), MAX_MESSAGE_LENGTH)
        self.assertNotIn("url", payload)

    @patch("quasarr.providers.notifications.pushover.requests.get")
    @patch("quasarr.providers.notifications.pushover.requests.post")
    def test_image_is_uploaded_as_bounded_attachment(self, post, get):
        image_response = _StreamingResponse("image/jpeg", b"image")
        get.return_value = image_response
        api_response = Mock(status_code=200)
        api_response.json.return_value = {"status": 1}
        post.return_value = api_response
        message = NotificationMessage(
            title="Synthetic title",
            description="Synthetic description",
            image_url="https://notification.invalid/poster.jpg",
        )
        self.shared_state.values["user_agent"] = "Synthetic-Agent"

        self.assertTrue(send(self.shared_state, message))

        get.assert_called_once()
        self.assertEqual(
            "Synthetic-Agent", get.call_args.kwargs["headers"]["User-Agent"]
        )
        self.assertTrue(get.call_args.kwargs["stream"])
        self.assertEqual([(5 * 1024 * 1024 + 1, True)], image_response.raw.read_calls)
        self.assertTrue(image_response.closed)
        attachment = post.call_args.kwargs["files"]["attachment"]
        self.assertEqual("poster.jpg", attachment[0])
        self.assertEqual(b"image", attachment[1])
        self.assertEqual("image/jpeg", attachment[2])

    @patch("quasarr.providers.notifications.pushover.requests.get")
    @patch("quasarr.providers.notifications.pushover.requests.post")
    def test_no_image_skips_fetch_and_multipart_attachment(self, post, get):
        response = Mock(status_code=200)
        response.json.return_value = {"status": 1}
        post.return_value = response

        self.assertTrue(send(self.shared_state, self.message))

        get.assert_not_called()
        self.assertIsNone(post.call_args.kwargs["files"])

    @patch("quasarr.providers.notifications.pushover.requests.get")
    @patch("quasarr.providers.notifications.pushover.requests.post")
    def test_invalid_or_oversized_image_falls_back_to_text(self, post, get):
        api_response = Mock(status_code=200)
        api_response.json.return_value = {"status": 1}
        post.return_value = api_response
        invalid_response = _StreamingResponse("text/plain", b"body")
        oversized_response = _StreamingResponse(
            "image/jpeg", b"x" * (5 * 1024 * 1024 + 1)
        )

        for image_response in (invalid_response, oversized_response):
            get.return_value = image_response
            message = NotificationMessage(
                title="Synthetic title",
                description="Synthetic description",
                image_url="https://notification.invalid/poster.jpg",
            )
            self.assertTrue(send(self.shared_state, message))
            self.assertIsNone(post.call_args.kwargs["files"])
            self.assertTrue(image_response.closed)

    def test_attachment_stream_closes_all_response_paths(self):
        responses = (
            _StreamingResponse("image/jpeg", b"image"),
            _StreamingResponse("text/plain", b"body"),
            _StreamingResponse("image/jpeg", b""),
            _StreamingResponse("image/jpeg", b"x" * (5 * 1024 * 1024 + 1)),
            _StreamingResponse("image/jpeg", b"error", status_code=500),
        )

        for response in responses:
            with patch(
                "quasarr.providers.notifications.pushover.requests.get",
                return_value=response,
            ):
                valid = (
                    response.status_code == 200
                    and response.headers["Content-Type"] == "image/jpeg"
                    and response.raw.content == b"image"
                )
                if valid:
                    attachment = _build_attachment(
                        self.shared_state, "https://notification.invalid/poster.jpg"
                    )
                    self.assertEqual(b"image", attachment["attachment"][1])
                else:
                    with self.assertRaises((ValueError, requests.HTTPError)):
                        _build_attachment(
                            self.shared_state, "https://notification.invalid/poster.jpg"
                        )
                self.assertTrue(response.closed)

    def test_attachment_stream_read_failure_closes_response(self):
        response = _StreamingResponse(
            "image/jpeg", b"error", read_error=requests.RequestException("synthetic")
        )
        with patch(
            "quasarr.providers.notifications.pushover.requests.get",
            return_value=response,
        ):
            with self.assertRaises(requests.RequestException):
                _build_attachment(
                    self.shared_state, "https://notification.invalid/poster.jpg"
                )
        self.assertTrue(response.closed)

    @patch("quasarr.providers.notifications.pushover.requests.post")
    def test_links_are_inline_without_supplementary_url_fields(self, post):
        response = Mock(status_code=200)
        response.json.return_value = {"status": 1}
        post.return_value = response
        link = NotificationLinkEntry(
            title="Details",
            text="Open here to view details",
            link_text="here",
            url="https://notification.invalid/item",
        )
        message = NotificationMessage(
            "Synthetic title", "Synthetic description", (link,)
        )

        self.assertTrue(send(self.shared_state, message))
        payload = post.call_args.kwargs["data"]
        self.assertIn(
            '<a href="https://notification.invalid/item">Open here to view details</a>',
            payload["message"],
        )
        self.assertNotIn("url", payload)
        self.assertNotIn("url_title", payload)

    @patch("quasarr.providers.notifications.pushover.requests.post")
    def test_long_fields_are_bounded_and_valid_primary_link_is_preserved(self, post):
        response = Mock(status_code=200)
        response.json.return_value = {"status": 1}
        post.return_value = response
        long_message = NotificationMessage(
            title="T" * (MAX_TITLE_LENGTH + 20),
            description="D" * 100,
            entries=(
                NotificationLinkEntry(
                    title="Solve CAPTCHA",
                    text="Open CAPTCHA",
                    link_text="CAPTCHA",
                    url="https://notification.invalid/captcha",
                ),
                NotificationTextEntry("Details", "D" * (MAX_MESSAGE_LENGTH + 200)),
            ),
        )

        self.assertTrue(send(self.shared_state, long_message))

        payload = post.call_args.kwargs["data"]
        self.assertEqual(MAX_TITLE_LENGTH, len(payload["title"]))
        self.assertLessEqual(len(payload["message"]), MAX_MESSAGE_LENGTH)
        self.assertNotIn("url", payload)
        self.assertIn("<b>Solve CAPTCHA</b>", payload["message"])
        self.assertIn(
            '<a href="https://notification.invalid/captcha">', payload["message"]
        )

    @patch("quasarr.providers.notifications.pushover.requests.post")
    def test_oversized_link_is_omitted_instead_of_broken(self, post):
        response = Mock(status_code=200)
        response.json.return_value = {"status": 1}
        post.return_value = response
        oversized_url = "https://notification.invalid/" + "x" * MAX_MESSAGE_LENGTH
        message = NotificationMessage(
            title="Synthetic title",
            description="Synthetic description",
            entries=(
                NotificationLinkEntry("Details", "Open", oversized_url),
                self.message.entries[0],
            ),
        )

        self.assertTrue(send(self.shared_state, message))
        payload = post.call_args.kwargs["data"]
        self.assertNotIn(oversized_url, payload["message"])
        self.assertEqual(
            "Synthetic description\n\n<b>Details</b>\n"
            '<a href="https://notification.invalid/item">Open details</a>',
            payload["message"],
        )

    @patch("quasarr.providers.notifications.pushover.requests.post")
    def test_long_description_preserves_complete_entities_and_action_link(self, post):
        post.return_value = Mock(
            status_code=200, **{"json.return_value": {"status": 1}}
        )
        message = NotificationMessage(
            "Synthetic title", "&" * MAX_MESSAGE_LENGTH, (self.message.entries[0],)
        )

        self.assertTrue(send(self.shared_state, message))

        body = post.call_args.kwargs["data"]["message"]
        description, action = body.split("\n\n")
        self.assertEqual("", description.replace("&amp;", ""))
        self.assertEqual(
            '<b>Details</b>\n<a href="https://notification.invalid/item">Open details</a>',
            action,
        )
        self.assertLessEqual(len(body), MAX_MESSAGE_LENGTH)

    @patch("quasarr.providers.notifications.pushover.requests.post")
    def test_api_failure_and_http_failure_return_false(self, post):
        for response in (
            Mock(status_code=200, **{"json.return_value": {"status": 0}}),
            Mock(status_code=500),
        ):
            post.return_value = response
            self.assertFalse(send(self.shared_state, self.message, silent=False))
        self.assertEqual(0, post.call_args.kwargs["data"]["priority"])

    @patch("quasarr.providers.notifications.pushover.requests.post")
    def test_priority_matches_manual_fallback_only(self, post):
        response = Mock(status_code=200)
        response.json.return_value = {"status": 1}
        post.return_value = response
        for notification_type in (*NotificationType, None):
            for silent in (False, True):
                with self.subTest(notification_type=notification_type, silent=silent):
                    self.assertTrue(
                        send(
                            self.shared_state,
                            self.message,
                            silent=silent,
                            notification_type=notification_type,
                        )
                    )
                    expected = (
                        -2
                        if silent
                        else (
                            1 if notification_type == NotificationType.DISABLED else 0
                        )
                    )
                    self.assertEqual(
                        expected, post.call_args.kwargs["data"]["priority"]
                    )

    def test_formatter_escapes_dynamic_html(self):
        message = NotificationMessage(
            "<title>",
            "<description>&",
            (NotificationTextEntry("<heading>", "<value>&"),),
        )
        rendered = PushoverNotificationFormatter().render_message(message)
        self.assertEqual(
            "&lt;description&gt;&amp;\n\n<b>&lt;heading&gt;</b>\n&lt;value&gt;&amp;",
            rendered,
        )

    def test_link_escapes_label_and_url_attribute(self):
        link = NotificationLinkEntry(
            "Action", "Open <details>", 'https://notification.invalid/?a="x"&b=1'
        )
        self.assertEqual(
            '<b>Action</b>\n<a href="https://notification.invalid/?a=&quot;x&quot;'
            '&amp;b=1">Open &lt;details&gt;</a>',
            PushoverNotificationFormatter().render_link_entry(link),
        )

    @patch("quasarr.providers.notifications.pushover.requests.post")
    def test_malformed_json_result_returns_false(self, post):
        response = Mock(status_code=200)
        response.json.return_value = ["synthetic"]
        post.return_value = response

        self.assertFalse(send(self.shared_state, self.message))

    @patch("quasarr.providers.notifications.pushover.requests.post")
    def test_network_failure_returns_false(self, post):
        import requests

        post.side_effect = requests.RequestException("synthetic failure")
        self.assertFalse(send(self.shared_state, self.message))


class PushoverLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.shared_state = SimpleNamespace(
            values={
                "external_address": "https://quasarr.invalid",
                "notification_settings": {
                    "pushover_api_token": "synthetic-token",
                    "pushover_user_key": "synthetic-user",
                    "toggles": {"pushover": {"test": True}},
                    "silent": {"pushover": {"test": True}},
                },
            }
        )

    @patch("quasarr.providers.notifications.pushover.requests.post")
    def test_disabled_outcome_has_captcha_action_without_initial_alert(self, post):
        response = Mock(status_code=200)
        response.json.return_value = {"status": 1}
        post.return_value = response
        settings = self.shared_state.values["notification_settings"]
        settings["toggles"]["pushover"] = {"captcha": False, "disabled": True}
        release = {"title": "Synthetic title"}

        self.assertEqual(
            {},
            send_tracked_notification(self.shared_state, release["title"], "captcha"),
        )
        post.assert_not_called()
        self.assertTrue(
            update_release_notification(self.shared_state, release, "disabled")
        )
        payload = post.call_args.kwargs["data"]
        self.assertEqual(1, payload["priority"])
        self.assertNotIn("url", payload)
        self.assertIn("<b>Solve CAPTCHA</b>", payload["message"])
        self.assertIn('<a href="https://quasarr.invalid/captcha">', payload["message"])

    @patch("quasarr.providers.notifications.pushover.requests.post")
    def test_solved_outcome_does_not_add_captcha_action(self, post):
        response = Mock(status_code=200)
        response.json.return_value = {"status": 1}
        post.return_value = response

        self.assertTrue(
            update_release_notification(
                self.shared_state,
                {"title": "Synthetic title"},
                "solved",
                details={"method": "manual"},
            )
        )
        payload = post.call_args.kwargs["data"]
        self.assertNotIn("url", payload)
        self.assertNotIn("Solve CAPTCHA", payload["message"])

    @patch("quasarr.providers.notifications.pushover.send", return_value=True)
    def test_all_entrypoints_use_provider_toggle_and_silence(self, send_mock):
        release = {"title": "Synthetic title"}

        self.assertTrue(send_notification(self.shared_state, "Synthetic title", "test"))
        self.assertEqual(
            {}, send_tracked_notification(self.shared_state, "Synthetic title", "test")
        )
        self.assertTrue(update_release_notification(self.shared_state, release, "test"))

        self.assertEqual(3, send_mock.call_count)
        self.assertTrue(all(call.kwargs["silent"] for call in send_mock.call_args_list))
        self.assertTrue(
            all(
                call.kwargs["notification_type"] == NotificationType.TEST
                for call in send_mock.call_args_list
            )
        )

    @patch("quasarr.providers.notifications.pushover.send", return_value=True)
    def test_disabled_case_skips_provider_for_all_entrypoints(self, send_mock):
        self.shared_state.values["notification_settings"]["toggles"]["pushover"][
            NotificationType.TEST.value
        ] = False

        release = {"title": "Synthetic title"}
        self.assertFalse(
            send_notification(self.shared_state, "Synthetic title", "test")
        )
        self.assertEqual(
            {}, send_tracked_notification(self.shared_state, "Synthetic title", "test")
        )
        self.assertFalse(
            update_release_notification(self.shared_state, release, "test")
        )
        send_mock.assert_not_called()

    @patch(
        "quasarr.providers.notifications.pushover.send",
        side_effect=RuntimeError("synthetic"),
    )
    @patch("quasarr.providers.notifications.discord.send", return_value=True)
    def test_send_notification_isolates_pushover_failure(
        self, discord_send, pushover_send
    ):
        self.shared_state.values["notification_settings"].update(
            {"discord_webhook": "https://webhook.invalid/hook"}
        )

        self.assertTrue(send_notification(self.shared_state, "Synthetic title", "test"))
        discord_send.assert_called_once()
        pushover_send.assert_called_once()

    @patch(
        "quasarr.providers.notifications.pushover.send",
        side_effect=RuntimeError("synthetic"),
    )
    @patch(
        "quasarr.providers.notifications.discord.send_tracked",
        return_value={"message_id": "1"},
    )
    def test_tracked_notification_isolates_pushover_failure(
        self, discord_send, pushover_send
    ):
        self.shared_state.values["notification_settings"].update(
            {"discord_webhook": "https://webhook.invalid/hook"}
        )

        references = send_tracked_notification(
            self.shared_state, "Synthetic title", "test"
        )

        self.assertIn("discord", references)
        discord_send.assert_called_once()
        pushover_send.assert_called_once()

    @patch(
        "quasarr.providers.notifications.pushover.send",
        side_effect=RuntimeError("synthetic"),
    )
    @patch("quasarr.providers.notifications.discord.edit", return_value=True)
    def test_release_update_isolates_pushover_failure(
        self, discord_edit, pushover_send
    ):
        self.shared_state.values["notification_settings"].update(
            {"discord_webhook": "https://webhook.invalid/hook"}
        )
        release = {
            "title": "Synthetic title",
            "notifications": {"discord": {"message_id": "1", "case": "test"}},
        }

        self.assertTrue(update_release_notification(self.shared_state, release, "test"))
        discord_edit.assert_called_once()
        pushover_send.assert_called_once()


if __name__ == "__main__":
    unittest.main()
