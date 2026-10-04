# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import re

from bottle import request, response

from quasarr.constants import NOTIFICATION_PROVIDERS, QUASARR_AVATAR
from quasarr.providers.log import info
from quasarr.providers.notifications.helpers.message_builder import (
    build_notification_message,
)
from quasarr.providers.notifications.helpers.notification_types import (
    NotificationType,
    get_user_configurable_notification_types,
)
from quasarr.storage.config import Config
from quasarr.storage.sqlite_database import DataBase

NOTIFICATION_TYPES = get_user_configurable_notification_types()
NOTIFICATION_SETTINGS_TABLE = "notification_settings"


def _notification_toggle_key(provider, notification_type):
    return f"{provider}_{notification_type.value}"


def _notification_silent_key(provider, notification_type):
    return f"{provider}_{notification_type.value}_silent"


def _coerce_bool(value, default=False):
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
    return bool(value)


def _read_notification_setting(notification_settings_db, key, default=True):
    stored_value = notification_settings_db.retrieve(key)
    return _coerce_bool(stored_value, default)


def _read_notification_toggle(notification_settings_db, key):
    return _read_notification_setting(notification_settings_db, key, default=True)


def _read_notification_silent(notification_settings_db, key):
    return _read_notification_setting(notification_settings_db, key, default=False)


def _read_notification_settings():
    notification_config = Config("Notifications")
    notification_settings_db = DataBase(NOTIFICATION_SETTINGS_TABLE)

    settings = {
        "discord_webhook": notification_config.get("discord_webhook") or "",
        "telegram_bot_token": notification_config.get("telegram_bot_token") or "",
        "telegram_chat_id": notification_config.get("telegram_chat_id") or "",
        "pushover_api_token": notification_config.get("pushover_api_token") or "",
        "pushover_user_key": notification_config.get("pushover_user_key") or "",
        "toggles": {provider: {} for provider in NOTIFICATION_PROVIDERS},
        "silent": {provider: {} for provider in NOTIFICATION_PROVIDERS},
    }

    for provider in NOTIFICATION_PROVIDERS:
        for notification_type in NOTIFICATION_TYPES:
            case_key = notification_type.value
            settings["toggles"][provider][case_key] = _read_notification_toggle(
                notification_settings_db,
                _notification_toggle_key(provider, notification_type),
            )
            settings["silent"][provider][case_key] = _read_notification_silent(
                notification_settings_db,
                _notification_silent_key(provider, notification_type),
            )

    return settings


def _validate_notification_provider_credentials(
    discord_webhook,
    telegram_bot_token,
    telegram_chat_id,
    pushover_api_token,
    pushover_user_key,
):
    discord_webhook_pattern = r"^https://discord\.com/api/webhooks/\d+/[\w-]+$"
    telegram_token_pattern = r"^\d+:[A-Za-z0-9_-]{35,}$"
    pushover_credential_pattern = r"^[A-Za-z0-9]{30}$"

    if discord_webhook and not re.match(discord_webhook_pattern, discord_webhook):
        return "Invalid Discord Webhook URL"

    if telegram_bot_token or telegram_chat_id:
        if not telegram_bot_token or not telegram_chat_id:
            return "Telegram setup requires both bot token and chat ID"
        if not re.match(telegram_token_pattern, telegram_bot_token):
            return "Invalid Telegram bot token format"

    if pushover_api_token or pushover_user_key:
        if not pushover_api_token or not pushover_user_key:
            return "Pushover setup requires both API token and user key"
        if not re.match(pushover_credential_pattern, pushover_api_token):
            return "Invalid Pushover API token format"
        if not re.match(pushover_credential_pattern, pushover_user_key):
            return "Invalid Pushover user key format"

    return None


def refresh_notification_settings(shared_state, backfill_defaults=False):
    del backfill_defaults

    settings = _read_notification_settings()

    shared_state.update("notification_settings", settings)

    return settings


def initialize_notification_settings(shared_state):
    return refresh_notification_settings(shared_state)


def get_notification_settings_data(shared_state):
    response.content_type = "application/json"
    settings = refresh_notification_settings(shared_state)
    return {"success": True, "settings": settings}


def save_notification_settings(shared_state):
    response.content_type = "application/json"

    data = request.json
    if not isinstance(data, dict):
        return {"success": False, "message": "Invalid JSON payload"}

    discord_webhook = str(data.get("discord_webhook", "")).strip()
    telegram_bot_token = str(data.get("telegram_bot_token", "")).strip()
    telegram_chat_id = str(data.get("telegram_chat_id", "")).strip()
    pushover_api_token = str(data.get("pushover_api_token", "")).strip()
    pushover_user_key = str(data.get("pushover_user_key", "")).strip()
    toggles = data.get("toggles") if isinstance(data.get("toggles"), dict) else {}
    silent = data.get("silent") if isinstance(data.get("silent"), dict) else {}

    validation_error = _validate_notification_provider_credentials(
        discord_webhook,
        telegram_bot_token,
        telegram_chat_id,
        pushover_api_token,
        pushover_user_key,
    )
    if validation_error:
        return {"success": False, "message": validation_error}

    notification_config = Config("Notifications")
    notification_config.save("discord_webhook", discord_webhook)
    notification_config.save("telegram_bot_token", telegram_bot_token)
    notification_config.save("telegram_chat_id", telegram_chat_id)
    notification_config.save("pushover_api_token", pushover_api_token)
    notification_config.save("pushover_user_key", pushover_user_key)
    notification_settings_db = DataBase(NOTIFICATION_SETTINGS_TABLE)

    for provider in NOTIFICATION_PROVIDERS:
        provider_toggles = toggles.get(provider)
        provider_silent = silent.get(provider)
        for notification_type in NOTIFICATION_TYPES:
            enabled_key = _notification_toggle_key(provider, notification_type)
            current_enabled = _read_notification_toggle(
                notification_settings_db,
                enabled_key,
            )
            if (
                isinstance(provider_toggles, dict)
                and notification_type.value in provider_toggles
            ):
                next_enabled = _coerce_bool(
                    provider_toggles.get(notification_type.value),
                    current_enabled,
                )
            else:
                next_enabled = current_enabled
            notification_settings_db.update_store(
                enabled_key, "true" if next_enabled else "false"
            )

            silent_key = _notification_silent_key(provider, notification_type)
            current_silent = _read_notification_silent(
                notification_settings_db,
                silent_key,
            )
            if (
                isinstance(provider_silent, dict)
                and notification_type.value in provider_silent
            ):
                next_silent = _coerce_bool(
                    provider_silent.get(notification_type.value),
                    current_silent,
                )
            else:
                next_silent = current_silent
            notification_settings_db.update_store(
                silent_key, "true" if next_silent else "false"
            )

    settings = refresh_notification_settings(shared_state)

    return {
        "success": True,
        "message": "Notification settings saved successfully",
        "settings": settings,
    }


def send_notification_test(shared_state):
    response.content_type = "application/json"

    data = request.json
    if not isinstance(data, dict):
        return {"success": False, "message": "Invalid JSON payload"}

    provider = str(data.get("provider", "")).strip().lower()
    if provider not in NOTIFICATION_PROVIDERS:
        return {"success": False, "message": "Unknown provider"}

    settings = refresh_notification_settings(shared_state)
    title = "Quasarr Notification Test"
    test_image_url = QUASARR_AVATAR

    if provider == "discord":
        if not settings["discord_webhook"]:
            return {
                "success": False,
                "message": "Discord webhook is not configured",
            }
        from quasarr.providers.notifications import discord

        message = build_notification_message(
            shared_state,
            title=title,
            case=NotificationType.TEST,
            details={"provider": "Discord"},
            image_url=test_image_url,
        )
        if message is None:
            return {"success": False, "message": "Failed to build Discord test message"}

        try:
            sent = discord.send(shared_state, message, silent=False)
        except Exception as e:
            info(f"Discord test notification error: {e}")
            return {
                "success": False,
                "message": f"Failed to send Discord test message: {e}",
            }
        if sent:
            return {"success": True, "message": "Discord test message sent"}
        return {
            "success": False,
            "message": "Failed to send Discord test message",
        }

    if provider == "pushover":
        if not settings["pushover_api_token"] or not settings["pushover_user_key"]:
            return {
                "success": False,
                "message": "Pushover API token and user key are required",
            }
        from quasarr.providers.notifications import pushover

        message = build_notification_message(
            shared_state,
            title=title,
            case=NotificationType.TEST,
            details={"provider": "Pushover"},
            image_url=test_image_url,
        )
        if message is None:
            return {
                "success": False,
                "message": "Failed to build Pushover test message",
            }

        try:
            sent = pushover.send(shared_state, message, silent=False)
        except Exception as e:
            info(f"Pushover test notification error: {e}")
            return {
                "success": False,
                "message": f"Failed to send Pushover test message: {e}",
            }
        if sent:
            return {"success": True, "message": "Pushover test message sent"}
        return {
            "success": False,
            "message": "Failed to send Pushover test message",
        }

    if not settings["telegram_bot_token"] or not settings["telegram_chat_id"]:
        return {
            "success": False,
            "message": "Telegram bot token and chat ID are required",
        }

    from quasarr.providers.notifications import telegram

    message = build_notification_message(
        shared_state,
        title=title,
        case=NotificationType.TEST,
        details={"provider": "Telegram"},
        image_url=test_image_url,
    )
    if message is None:
        return {"success": False, "message": "Failed to build Telegram test message"}

    try:
        sent = telegram.send(shared_state, message, silent=False)
        if not sent:
            telegram_destination = telegram.inspect_destination(shared_state)
    except Exception as e:
        info(f"Telegram test notification error: {e}")
        return {
            "success": False,
            "message": f"Failed to send Telegram test message: {e}",
        }
    if sent:
        return {"success": True, "message": "Telegram test message sent"}

    destination_message = telegram_destination.get("message")
    if destination_message:
        return {
            "success": False,
            "message": f"Failed to send Telegram test message: {destination_message}",
        }
    return {"success": False, "message": "Failed to send Telegram test message"}
