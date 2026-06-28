# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

from dataclasses import replace

from quasarr.providers.log import info
from quasarr.providers.notifications.helpers import resolve_poster_url
from quasarr.providers.notifications.helpers.message_builder import (
    build_notification_message,
)
from quasarr.providers.notifications.helpers.notification_types import (
    NotificationType,
    normalize_notification_type,
)


def _get_notification_settings(shared_state):
    settings = shared_state.values.get("notification_settings")
    return settings if isinstance(settings, dict) else {}


def _provider_case_enabled(shared_state, provider, notification_type):
    toggles = _get_notification_settings(shared_state).get("toggles")
    if not isinstance(toggles, dict):
        return True

    provider_toggles = toggles.get(provider)
    if not isinstance(provider_toggles, dict):
        return True

    return bool(provider_toggles.get(notification_type.value, True))


def _provider_case_silent(shared_state, provider, notification_type):
    silent_settings = _get_notification_settings(shared_state).get("silent")
    if not isinstance(silent_settings, dict):
        return False

    provider_silent = silent_settings.get(provider)
    if not isinstance(provider_silent, dict):
        return False

    return bool(provider_silent.get(notification_type.value, False))


def _has_discord(notification_settings):
    return bool(notification_settings.get("discord_webhook"))


def _has_telegram(notification_settings):
    return bool(notification_settings.get("telegram_bot_token")) and bool(
        notification_settings.get("telegram_chat_id")
    )


def _build_message(
    shared_state,
    title,
    notification_type,
    imdb_id=None,
    details=None,
    source=None,
    include_poster=False,
    include_captcha_action=False,
):
    image_url = None
    if include_poster:
        image_url = resolve_poster_url(shared_state, title, imdb_id)

    message = build_notification_message(
        shared_state,
        title,
        notification_type,
        details=details,
        source=source,
        image_url=image_url,
    )
    if (
        message is not None
        and include_captcha_action
        and notification_type == NotificationType.DISABLED
    ):
        captcha_message = build_notification_message(
            shared_state,
            title,
            NotificationType.CAPTCHA,
        )
        captcha_entries = tuple(
            entry for entry in captcha_message.entries if entry.title == "Solve CAPTCHA"
        )
        message = replace(message, entries=captcha_entries + message.entries)
    return message


def send_notification(
    shared_state, title, case, imdb_id=None, details=None, source=None
):
    """
    Send a notification to all configured providers (Discord, Telegram).

    Each provider is attempted independently — a failure in one does not block others.

    :param shared_state: Shared state object containing configuration.
    :param title: Title of the notification.
    :param case: A string representing the scenario (e.g., 'captcha', 'failed', 'unprotected').
    :param imdb_id: A string starting with "tt" followed by at least 7 digits, representing an object on IMDb
    :param details: A dictionary containing additional details, such as version and link for updates.
    :param source: Optional source of the notification, sent as a field in the embed.
    :return: True if at least one provider sent successfully, False otherwise.
    """
    from quasarr.providers.notifications import discord, telegram

    notification_type = normalize_notification_type(case)
    if notification_type is None:
        info(f"Unknown notification case: {case}")
        return False

    notification_settings = _get_notification_settings(shared_state)
    has_discord = _has_discord(notification_settings)
    has_telegram = _has_telegram(notification_settings)

    if not has_discord and not has_telegram:
        return False

    message = _build_message(
        shared_state,
        title,
        notification_type,
        imdb_id=imdb_id,
        details=details,
        source=source,
        include_poster=notification_type
        in (NotificationType.UNPROTECTED, NotificationType.CAPTCHA),
    )
    if message is None:
        return False

    any_success = False

    if has_discord and _provider_case_enabled(
        shared_state, "discord", notification_type
    ):
        discord_silent = _provider_case_silent(
            shared_state, "discord", notification_type
        )
        try:
            if discord.send(shared_state, message, silent=discord_silent):
                any_success = True
        except Exception as e:
            info(f"Discord notification error: {e}")

    if has_telegram and _provider_case_enabled(
        shared_state, "telegram", notification_type
    ):
        telegram_silent = _provider_case_silent(
            shared_state, "telegram", notification_type
        )
        try:
            if telegram.send(shared_state, message, silent=telegram_silent):
                any_success = True
        except Exception as e:
            info(f"Telegram notification error: {e}")

    return any_success


def send_tracked_notification(
    shared_state, title, case, imdb_id=None, details=None, source=None
):
    """Send a notification and return provider references needed for later edits."""
    from quasarr.providers.notifications import discord, telegram

    notification_type = normalize_notification_type(case)
    if notification_type is None:
        info(f"Unknown notification case: {case}")
        return {}

    notification_settings = _get_notification_settings(shared_state)
    discord_enabled = _has_discord(notification_settings) and _provider_case_enabled(
        shared_state, "discord", notification_type
    )
    telegram_enabled = _has_telegram(notification_settings) and _provider_case_enabled(
        shared_state, "telegram", notification_type
    )

    if not discord_enabled and not telegram_enabled:
        return {}

    message = _build_message(
        shared_state,
        title,
        notification_type,
        imdb_id=imdb_id,
        details=details,
        source=source,
        include_poster=notification_type
        in (NotificationType.UNPROTECTED, NotificationType.CAPTCHA),
    )
    if message is None:
        return {}

    references = {}
    if discord_enabled:
        discord_silent = _provider_case_silent(
            shared_state, "discord", notification_type
        )
        try:
            reference = discord.send_tracked(
                shared_state,
                message,
                silent=discord_silent,
            )
            if reference:
                reference["case"] = notification_type.value
                references["discord"] = reference
        except Exception as e:
            info(f"Discord notification error: {e}")

    if telegram_enabled:
        telegram_silent = _provider_case_silent(
            shared_state, "telegram", notification_type
        )
        try:
            telegram.send(shared_state, message, silent=telegram_silent)
        except Exception as e:
            info(f"Telegram notification error: {e}")

    return references


def update_release_notification(shared_state, release, case, details=None):
    """Update a release and preserve configured silence transitions."""
    from quasarr.providers.notifications import discord, telegram

    notification_type = normalize_notification_type(case)
    if notification_type is None or not isinstance(release, dict):
        return False

    title = release.get("title") or "Unknown"
    source = release.get("original_url")
    imdb_id = release.get("imdb_id")
    notification_settings = _get_notification_settings(shared_state)
    any_success = False

    if _has_discord(notification_settings) and _provider_case_enabled(
        shared_state,
        "discord",
        notification_type,
    ):
        current_silent = _provider_case_silent(
            shared_state,
            "discord",
            notification_type,
        )
        references = release.get("notifications")
        discord_reference = (
            references.get("discord") if isinstance(references, dict) else None
        )
        outcome_message = None
        edit_succeeded = False
        if isinstance(discord_reference, dict):
            outcome_message = _build_message(
                shared_state,
                title,
                notification_type,
                imdb_id=imdb_id,
                details=details,
                source=source,
                include_poster=True,
                include_captcha_action=True,
            )
            try:
                if outcome_message:
                    edit_succeeded = bool(
                        discord.edit(
                            shared_state,
                            discord_reference,
                            outcome_message,
                        )
                    )
            except Exception as e:
                info(f"Discord notification edit error: {e}")

        if edit_succeeded:
            any_success = True
            previous_silent = bool(discord_reference.get("silent", False))
            advance_silence_state = not (previous_silent and not current_silent)
            if previous_silent and not current_silent:
                follow_up_message = _build_message(
                    shared_state,
                    title,
                    notification_type,
                    details=details,
                )
                try:
                    if follow_up_message and discord.send(
                        shared_state,
                        follow_up_message,
                        silent=False,
                    ):
                        any_success = True
                        advance_silence_state = True
                except Exception as e:
                    info(f"Discord notification follow-up error: {e}")

            discord_reference["case"] = notification_type.value
            if advance_silence_state:
                discord_reference["silent"] = current_silent
        else:
            if outcome_message is None:
                outcome_message = _build_message(
                    shared_state,
                    title,
                    notification_type,
                    imdb_id=imdb_id,
                    details=details,
                    source=source,
                    include_poster=True,
                    include_captcha_action=True,
                )
            try:
                if outcome_message and notification_type == NotificationType.DISABLED:
                    reference = discord.send_tracked(
                        shared_state,
                        outcome_message,
                        silent=current_silent,
                    )
                    if reference:
                        reference["case"] = notification_type.value
                        if not isinstance(release.get("notifications"), dict):
                            release["notifications"] = {}
                        release["notifications"]["discord"] = reference
                        any_success = True
                elif outcome_message and discord.send(
                    shared_state,
                    outcome_message,
                    silent=current_silent,
                ):
                    any_success = True
            except Exception as e:
                info(f"Discord notification fallback error: {e}")

    if _has_telegram(notification_settings) and _provider_case_enabled(
        shared_state, "telegram", notification_type
    ):
        telegram_message = _build_message(
            shared_state,
            title,
            notification_type,
            details=details,
        )
        telegram_silent = _provider_case_silent(
            shared_state, "telegram", notification_type
        )
        try:
            if telegram_message and telegram.send(
                shared_state,
                telegram_message,
                silent=telegram_silent,
            ):
                any_success = True
        except Exception as e:
            info(f"Telegram notification error: {e}")

    return any_success
