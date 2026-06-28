# -*- coding: utf-8 -*-

import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit

from quasarr.constants import SUPPRESS_NOTIFICATIONS
from quasarr.downloads import store_protected_links
from quasarr.providers.notifications import (
    discord,
    send_tracked_notification,
    update_release_notification,
)
from quasarr.providers.notifications.helpers.message_builder import (
    build_notification_message,
)
from quasarr.providers.notifications.helpers.notification_types import NotificationType


class NotificationMessageBuilderTests(unittest.TestCase):
    def setUp(self):
        self.shared_state = SimpleNamespace(values={})

    def test_failed_notification_includes_reason_entry(self):
        message = build_notification_message(
            self.shared_state,
            "Example.Release",
            NotificationType.FAILED,
            details={"reason": "All final download links were rejected."},
        )

        self.assertIsNotNone(message)
        self.assertEqual("Package marked as failed.", message.description)
        self.assertEqual(1, len(message.entries))
        self.assertEqual("Reason", message.entries[0].title)
        self.assertEqual(
            "All final download links were rejected.",
            message.entries[0].value,
        )

    def test_disabled_notification_uses_error_as_reason(self):
        message = build_notification_message(
            self.shared_state,
            "Example.Release",
            NotificationType.DISABLED,
            details={"error": "SponsorsHelper hit its retry limit."},
        )

        self.assertIsNotNone(message)
        self.assertEqual(1, len(message.entries))
        self.assertEqual("Reason", message.entries[0].title)
        self.assertEqual(
            "SponsorsHelper hit its retry limit.",
            message.entries[0].value,
        )

    def test_manual_solved_notification_does_not_claim_sponsors_helper(self):
        message = build_notification_message(
            self.shared_state,
            "Example.Release",
            NotificationType.SOLVED,
            details={"method": "manual"},
        )

        self.assertEqual("CAPTCHA solved manually!", message.description)


class DiscordNotificationTests(unittest.TestCase):
    def setUp(self):
        self.webhook_url = (
            "https://webhook.invalid/api/webhooks/123/token?thread_id=456"
        )
        self.shared_state = SimpleNamespace(
            values={
                "external_address": "https://quasarr.invalid",
                "notification_settings": {
                    "discord_webhook": self.webhook_url,
                    "telegram_bot_token": "",
                    "telegram_chat_id": "",
                    "toggles": {"discord": {}},
                    "silent": {"discord": {}},
                },
            }
        )
        self.message = build_notification_message(
            self.shared_state,
            "Example.Release",
            NotificationType.TEST,
        )

    @patch("quasarr.providers.notifications.discord.requests.post")
    def test_tracked_send_requests_message_and_returns_edit_reference(self, mock_post):
        response = Mock(status_code=200)
        response.json.return_value = {"id": "789"}
        mock_post.return_value = response

        reference = discord.send_tracked(
            self.shared_state,
            self.message,
            silent=True,
        )

        request_url = mock_post.call_args.args[0]
        self.assertEqual(
            {"thread_id": ["456"], "wait": ["true"]},
            parse_qs(urlsplit(request_url).query),
        )
        payload = json.loads(mock_post.call_args.kwargs["data"])
        self.assertEqual(SUPPRESS_NOTIFICATIONS, payload["flags"])
        self.assertEqual("789", reference["message_id"])
        self.assertTrue(reference["silent"])
        self.assertNotIn("token", json.dumps(reference))

    @patch("quasarr.providers.notifications.discord.requests.patch")
    def test_edit_uses_saved_message_id_without_creation_only_fields(self, mock_patch):
        mock_patch.return_value = Mock(status_code=200)
        reference = {
            "message_id": "789",
            "webhook_fingerprint": discord._webhook_fingerprint(self.webhook_url),
        }

        self.assertTrue(discord.edit(self.shared_state, reference, self.message))

        request_url = mock_patch.call_args.args[0]
        split_url = urlsplit(request_url)
        self.assertTrue(split_url.path.endswith("/messages/789"))
        self.assertEqual({"thread_id": ["456"]}, parse_qs(split_url.query))
        payload = json.loads(mock_patch.call_args.kwargs["data"])
        self.assertNotIn("flags", payload)
        self.assertNotIn("username", payload)
        self.assertNotIn("avatar_url", payload)

    @patch("quasarr.providers.notifications.discord.requests.patch")
    def test_edit_rejects_reference_from_changed_webhook(self, mock_patch):
        reference = {
            "message_id": "789",
            "webhook_fingerprint": "different-webhook",
        }

        self.assertFalse(discord.edit(self.shared_state, reference, self.message))
        mock_patch.assert_not_called()


class ReleaseNotificationLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.shared_state = SimpleNamespace(
            values={
                "external_address": "https://quasarr.invalid",
                "notification_settings": {
                    "discord_webhook": "https://webhook.invalid/api/webhooks/123/token",
                    "telegram_bot_token": "",
                    "telegram_chat_id": "",
                    "toggles": {"discord": {}},
                    "silent": {
                        "discord": {
                            "captcha": True,
                            "solved": True,
                            "disabled": False,
                            "failed": False,
                        }
                    },
                },
            }
        )
        self.release = {
            "title": "Example.Release",
            "original_url": "https://release.invalid/item/123",
            "notifications": {
                "discord": {
                    "message_id": "789",
                    "webhook_fingerprint": "fingerprint",
                    "case": "captcha",
                    "silent": True,
                }
            },
        }

    @patch("quasarr.providers.notifications.resolve_poster_url", return_value=None)
    @patch("quasarr.providers.notifications.discord.send_tracked")
    def test_initial_captcha_send_returns_discord_reference(
        self,
        mock_send_tracked,
        mock_resolve_poster,
    ):
        reference = {
            "message_id": "789",
            "webhook_fingerprint": "fingerprint",
            "silent": True,
        }
        mock_send_tracked.return_value = reference

        references = send_tracked_notification(
            self.shared_state,
            "Example.Release",
            NotificationType.CAPTCHA,
        )

        self.assertEqual("captcha", references["discord"]["case"])
        self.assertTrue(references["discord"]["silent"])

    @patch("quasarr.providers.notifications.resolve_poster_url")
    @patch("quasarr.providers.notifications.discord.send_tracked")
    @patch("quasarr.providers.notifications.telegram.send")
    def test_tracked_send_skips_message_when_all_provider_cases_are_disabled(
        self,
        mock_telegram_send,
        mock_discord_send_tracked,
        mock_resolve_poster,
    ):
        notification_settings = self.shared_state.values["notification_settings"]
        notification_settings["telegram_bot_token"] = "synthetic-token"
        notification_settings["telegram_chat_id"] = "synthetic-chat"
        notification_settings["toggles"] = {
            "discord": {"captcha": False},
            "telegram": {"captcha": False},
        }

        self.assertEqual(
            {},
            send_tracked_notification(
                self.shared_state,
                "Example.Release",
                NotificationType.CAPTCHA,
            ),
        )

        mock_resolve_poster.assert_not_called()
        mock_discord_send_tracked.assert_not_called()
        mock_telegram_send.assert_not_called()

    @patch("quasarr.providers.notifications.resolve_poster_url", return_value=None)
    @patch("quasarr.providers.notifications.discord.send")
    @patch("quasarr.providers.notifications.discord.edit", return_value=True)
    def test_success_edits_original_without_follow_up(
        self,
        mock_edit,
        mock_send,
        mock_resolve_poster,
    ):
        self.assertTrue(
            update_release_notification(
                self.shared_state,
                self.release,
                NotificationType.SOLVED,
                details={"method": "manual"},
            )
        )

        mock_edit.assert_called_once()
        edited_message = mock_edit.call_args.args[2]
        self.assertEqual("CAPTCHA solved manually!", edited_message.description)
        mock_send.assert_not_called()
        self.assertEqual("solved", self.release["notifications"]["discord"]["case"])
        self.assertTrue(self.release["notifications"]["discord"]["silent"])

    @patch("quasarr.providers.notifications.resolve_poster_url", return_value=None)
    @patch("quasarr.providers.notifications.discord.send")
    @patch("quasarr.providers.notifications.discord.edit")
    def test_disabled_case_does_not_edit_or_advance_state(
        self,
        mock_edit,
        mock_send,
        mock_resolve_poster,
    ):
        self.shared_state.values["notification_settings"]["toggles"]["discord"][
            "solved"
        ] = False

        self.assertFalse(
            update_release_notification(
                self.shared_state,
                self.release,
                NotificationType.SOLVED,
                details={"method": "manual"},
            )
        )

        mock_edit.assert_not_called()
        mock_send.assert_not_called()
        self.assertEqual("captcha", self.release["notifications"]["discord"]["case"])
        self.assertTrue(self.release["notifications"]["discord"]["silent"])

    @patch("quasarr.providers.notifications.resolve_poster_url", return_value=None)
    @patch("quasarr.providers.notifications.discord.send", return_value=True)
    @patch("quasarr.providers.notifications.discord.edit", return_value=True)
    def test_silent_to_non_silent_success_sends_follow_up(
        self,
        mock_edit,
        mock_send,
        mock_resolve_poster,
    ):
        self.shared_state.values["notification_settings"]["silent"]["discord"][
            "solved"
        ] = False

        self.assertTrue(
            update_release_notification(
                self.shared_state,
                self.release,
                NotificationType.SOLVED,
                details={"method": "manual"},
            )
        )

        mock_edit.assert_called_once()
        mock_send.assert_called_once()
        self.assertFalse(mock_send.call_args.kwargs["silent"])
        self.assertFalse(self.release["notifications"]["discord"]["silent"])

    @patch("quasarr.providers.notifications.resolve_poster_url", return_value=None)
    @patch("quasarr.providers.notifications.discord.send", return_value=True)
    @patch("quasarr.providers.notifications.discord.edit", return_value=True)
    def test_dynamic_state_advances_after_silent_to_loud_disable(
        self,
        mock_edit,
        mock_send,
        mock_resolve_poster,
    ):
        self.assertTrue(
            update_release_notification(
                self.shared_state,
                self.release,
                NotificationType.DISABLED,
                details={"reason": "Synthetic solver failure."},
            )
        )

        mock_edit.assert_called_once()
        mock_send.assert_called_once()
        self.assertFalse(mock_send.call_args.kwargs["silent"])
        edited_message = mock_edit.call_args.args[2]
        self.assertEqual("Solve CAPTCHA", edited_message.entries[0].title)
        alert_message = mock_send.call_args.args[1]
        self.assertNotIn(
            "Solve CAPTCHA",
            [entry.title for entry in alert_message.entries],
        )
        self.assertEqual("disabled", self.release["notifications"]["discord"]["case"])
        self.assertFalse(self.release["notifications"]["discord"]["silent"])

        update_release_notification(
            self.shared_state,
            self.release,
            NotificationType.SOLVED,
            details={"method": "manual"},
        )

        self.assertEqual(2, mock_edit.call_count)
        self.assertEqual(1, mock_send.call_count)
        self.assertEqual("solved", self.release["notifications"]["discord"]["case"])

    @patch("quasarr.providers.notifications.resolve_poster_url", return_value=None)
    @patch(
        "quasarr.providers.notifications.discord.send",
        side_effect=[False, True],
    )
    @patch("quasarr.providers.notifications.discord.edit", return_value=True)
    def test_failed_loud_follow_up_preserves_silent_state_for_retry(
        self,
        mock_edit,
        mock_send,
        mock_resolve_poster,
    ):
        self.shared_state.values["notification_settings"]["silent"]["discord"][
            "solved"
        ] = False

        self.assertTrue(
            update_release_notification(
                self.shared_state,
                self.release,
                NotificationType.DISABLED,
                details={"reason": "Synthetic solver failure."},
            )
        )

        self.assertEqual("disabled", self.release["notifications"]["discord"]["case"])
        self.assertTrue(self.release["notifications"]["discord"]["silent"])

        self.assertTrue(
            update_release_notification(
                self.shared_state,
                self.release,
                NotificationType.SOLVED,
                details={"method": "manual"},
            )
        )

        self.assertEqual(2, mock_edit.call_count)
        self.assertEqual(2, mock_send.call_count)
        self.assertEqual("solved", self.release["notifications"]["discord"]["case"])
        self.assertFalse(self.release["notifications"]["discord"]["silent"])

    @patch("quasarr.providers.notifications.resolve_poster_url", return_value=None)
    @patch("quasarr.providers.notifications.discord.send", return_value=True)
    @patch(
        "quasarr.providers.notifications.discord.edit",
        return_value=False,
    )
    def test_failed_edit_sends_full_outcome_fallback(
        self,
        mock_edit,
        mock_send,
        mock_resolve_poster,
    ):
        self.assertTrue(
            update_release_notification(
                self.shared_state,
                self.release,
                NotificationType.FAILED,
                details={"reason": "Synthetic terminal failure."},
            )
        )

        mock_edit.assert_called_once()
        mock_send.assert_called_once()
        self.assertFalse(mock_send.call_args.kwargs["silent"])
        alert_message = mock_send.call_args.args[1]
        self.assertEqual("Package marked as failed.", alert_message.description)
        self.assertEqual("Reason", alert_message.entries[0].title)
        self.assertEqual(
            "Synthetic terminal failure.",
            alert_message.entries[0].value,
        )
        self.assertIn("Source", [entry.title for entry in alert_message.entries])

    @patch("quasarr.providers.notifications.resolve_poster_url", return_value=None)
    @patch("quasarr.providers.notifications.discord.send", return_value=False)
    @patch("quasarr.providers.notifications.discord.edit", return_value=False)
    def test_failed_edit_and_fallback_do_not_advance_state(
        self,
        mock_edit,
        mock_send,
        mock_resolve_poster,
    ):
        self.assertFalse(
            update_release_notification(
                self.shared_state,
                self.release,
                NotificationType.FAILED,
                details={"reason": "Synthetic terminal failure."},
            )
        )

        mock_edit.assert_called_once()
        mock_send.assert_called_once()
        self.assertEqual("captcha", self.release["notifications"]["discord"]["case"])
        self.assertTrue(self.release["notifications"]["discord"]["silent"])

    @patch("quasarr.providers.notifications.resolve_poster_url", return_value=None)
    @patch("quasarr.providers.notifications.discord.send")
    @patch("quasarr.providers.notifications.discord.send_tracked")
    @patch("quasarr.providers.notifications.discord.edit", return_value=False)
    def test_failed_disabled_edit_replaces_tracked_reference(
        self,
        mock_edit,
        mock_send_tracked,
        mock_send,
        mock_resolve_poster,
    ):
        replacement = {
            "message_id": "replacement-message",
            "webhook_fingerprint": "replacement-fingerprint",
            "silent": False,
        }
        mock_send_tracked.return_value = replacement

        self.assertTrue(
            update_release_notification(
                self.shared_state,
                self.release,
                NotificationType.DISABLED,
                details={"reason": "Synthetic solver failure."},
            )
        )

        mock_edit.assert_called_once()
        mock_send.assert_not_called()
        mock_send_tracked.assert_called_once()
        self.assertEqual(
            "replacement-message",
            self.release["notifications"]["discord"]["message_id"],
        )
        self.assertEqual(
            "disabled",
            self.release["notifications"]["discord"]["case"],
        )


class ProtectedReleaseNotificationStorageTests(unittest.TestCase):
    def test_discord_reference_is_stored_in_existing_protected_release(self):
        protected_db = Mock()
        requested_tables = []

        def database(table):
            requested_tables.append(table)
            return protected_db

        shared_state = SimpleNamespace(
            values={
                "database": database,
                "external_address": "https://quasarr.invalid",
            }
        )
        reference = {
            "discord": {
                "message_id": "789",
                "webhook_fingerprint": "fingerprint",
                "case": "captcha",
                "silent": True,
            }
        }

        store_protected_links(
            shared_state,
            [["https://container.invalid/item", "container"]],
            "Example.Release",
            "",
            "Quasarr_tv_deadbeefdeadbeefdeadbeefdeadbeef",
            original_url="https://release.invalid/item/123",
            imdb_id="tt0000001",
            notifications=reference,
        )

        self.assertEqual(["protected"], requested_tables)
        stored_json = protected_db.update_store.call_args.args[1]
        stored_release = json.loads(stored_json)
        self.assertEqual(reference, stored_release["notifications"])
        self.assertEqual("tt0000001", stored_release["imdb_id"])


if __name__ == "__main__":
    unittest.main()
