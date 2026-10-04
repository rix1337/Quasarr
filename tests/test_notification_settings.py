# -*- coding: utf-8 -*-

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from quasarr.storage.setup import notifications


class FakeConfig:
    values = {
        "discord_webhook": "",
        "telegram_bot_token": "",
        "telegram_chat_id": "",
        "pushover_api_token": "",
        "pushover_user_key": "",
    }

    def __init__(self, section):
        self.section = section

    def get(self, key):
        return self.values.get(key, "")

    def save(self, key, value):
        self.values[key] = value


class FakeDatabase:
    values = {}

    def __init__(self, table):
        self.table = table

    def retrieve(self, key):
        return self.values.get(key)

    def update_store(self, key, value):
        self.values[key] = value


class NotificationSettingsTests(unittest.TestCase):
    def setUp(self):
        FakeConfig.values = {
            "discord_webhook": "",
            "telegram_bot_token": "",
            "telegram_chat_id": "",
            "pushover_api_token": "",
            "pushover_user_key": "",
        }
        FakeDatabase.values = {}
        self.shared_state = SimpleNamespace(values={})

        def update(key, value):
            self.shared_state.values[key] = value

        self.shared_state.update = update
        self.providers = ("discord", "telegram", "pushover")

    def _patch_storage(self):
        return patch.multiple(
            notifications,
            Config=FakeConfig,
            DataBase=FakeDatabase,
            NOTIFICATION_PROVIDERS=self.providers,
        )

    def _save_payload(self, **overrides):
        payload = {
            "discord_webhook": "",
            "telegram_bot_token": "",
            "telegram_chat_id": "",
            "pushover_api_token": "",
            "pushover_user_key": "",
            "toggles": {},
            "silent": {},
        }
        payload.update(overrides)
        return payload

    def test_refresh_includes_pushover_credentials_and_defaults(self):
        with self._patch_storage():
            settings = notifications.refresh_notification_settings(self.shared_state)

        self.assertEqual("", settings["pushover_api_token"])
        self.assertEqual("", settings["pushover_user_key"])
        self.assertTrue(settings["toggles"]["pushover"])
        self.assertTrue(
            all(value is False for value in settings["silent"]["pushover"].values())
        )

    def test_save_persists_pushover_credentials_and_settings(self):
        payload = self._save_payload(
            pushover_api_token="A" * 30,
            pushover_user_key="B" * 30,
            toggles={"pushover": {"captcha": False}},
            silent={"pushover": {"captcha": True}},
        )
        with (
            self._patch_storage(),
            patch(
                "quasarr.storage.setup.notifications.request",
                SimpleNamespace(json=payload),
            ),
        ):
            result = notifications.save_notification_settings(self.shared_state)

        self.assertTrue(result["success"])
        self.assertEqual("A" * 30, FakeConfig.values["pushover_api_token"])
        self.assertEqual("B" * 30, FakeConfig.values["pushover_user_key"])
        self.assertFalse(result["settings"]["toggles"]["pushover"]["captcha"])
        self.assertTrue(result["settings"]["silent"]["pushover"]["captcha"])

    def test_save_preserves_missing_toggle_values(self):
        FakeDatabase.values["pushover_captcha"] = "false"
        FakeDatabase.values["pushover_captcha_silent"] = "true"
        payload = self._save_payload(
            pushover_api_token="A" * 30,
            pushover_user_key="B" * 30,
        )
        with (
            self._patch_storage(),
            patch(
                "quasarr.storage.setup.notifications.request",
                SimpleNamespace(json=payload),
            ),
        ):
            result = notifications.save_notification_settings(self.shared_state)

        self.assertFalse(result["settings"]["toggles"]["pushover"]["captcha"])
        self.assertTrue(result["settings"]["silent"]["pushover"]["captcha"])

    def test_save_rejects_partial_or_malformed_pushover_credentials(self):
        cases = (
            ({"pushover_api_token": "A" * 30}, "both API token and user key"),
            (
                {
                    "pushover_api_token": "A" * 29,
                    "pushover_user_key": "B" * 30,
                },
                "API token format",
            ),
            (
                {
                    "pushover_api_token": "A" * 30,
                    "pushover_user_key": "B" * 29 + "!",
                },
                "user key format",
            ),
        )
        for values, expected in cases:
            with (
                self.subTest(expected=expected),
                self._patch_storage(),
                patch(
                    "quasarr.storage.setup.notifications.request",
                    SimpleNamespace(json=self._save_payload(**values)),
                ),
            ):
                result = notifications.save_notification_settings(self.shared_state)
            self.assertFalse(result["success"])
            self.assertIn(expected, result["message"])

    def test_pushover_test_handler_reports_success_and_failure(self):
        payload = {"provider": "pushover"}
        message = object()
        with (
            self._patch_storage(),
            patch(
                "quasarr.storage.setup.notifications.request",
                SimpleNamespace(json=payload),
            ),
            patch(
                "quasarr.storage.setup.notifications.build_notification_message",
                return_value=message,
            ),
            patch(
                "quasarr.providers.notifications.pushover.send", return_value=True
            ) as send_mock,
        ):
            FakeConfig.values["pushover_api_token"] = "A" * 30
            FakeConfig.values["pushover_user_key"] = "B" * 30
            result = notifications.send_notification_test(self.shared_state)

        self.assertTrue(result["success"])
        self.assertEqual("Pushover test message sent", result["message"])
        self.assertFalse(send_mock.call_args.kwargs["silent"])

        with (
            self._patch_storage(),
            patch(
                "quasarr.storage.setup.notifications.request",
                SimpleNamespace(json=payload),
            ),
            patch(
                "quasarr.storage.setup.notifications.build_notification_message",
                return_value=message,
            ),
            patch("quasarr.providers.notifications.pushover.send", return_value=False),
        ):
            FakeConfig.values["pushover_api_token"] = "A" * 30
            FakeConfig.values["pushover_user_key"] = "B" * 30
            result = notifications.send_notification_test(self.shared_state)

        self.assertFalse(result["success"])
        self.assertEqual("Failed to send Pushover test message", result["message"])

    def test_legacy_discord_and_telegram_test_handlers_remain_available(self):
        message = object()
        for provider, field, module_name, label in (
            ("discord", "discord_webhook", "discord", "Discord"),
            ("telegram", "telegram_bot_token", "telegram", "Telegram"),
        ):
            with (
                self.subTest(provider=provider),
                self._patch_storage(),
                patch(
                    "quasarr.storage.setup.notifications.request",
                    SimpleNamespace(json={"provider": provider}),
                ),
                patch(
                    "quasarr.storage.setup.notifications.build_notification_message",
                    return_value=message,
                ),
                patch(
                    f"quasarr.providers.notifications.{module_name}.send",
                    return_value=True,
                ) as send_mock,
            ):
                FakeConfig.values[field] = "synthetic-value"
                if provider == "telegram":
                    FakeConfig.values["telegram_chat_id"] = "synthetic-chat"
                result = notifications.send_notification_test(self.shared_state)

            self.assertTrue(result["success"])
            self.assertEqual(f"{label} test message sent", result["message"])
            send_mock.assert_called_once()


if __name__ == "__main__":
    unittest.main()
