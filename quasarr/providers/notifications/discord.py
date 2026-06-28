# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import json
from hashlib import sha256
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

import requests

from quasarr.constants import (
    QUASARR_AVATAR,
    SESSION_REQUEST_TIMEOUT_SECONDS,
    SUPPRESS_NOTIFICATIONS,
)
from quasarr.providers.log import info
from quasarr.providers.notifications.helpers.abstract_notification_formatter import (
    AbstractNotificationFormatter,
)
from quasarr.providers.notifications.helpers.notification_message import (
    NotificationFactsEntry,
    NotificationLinkEntry,
    NotificationMessage,
    NotificationTextEntry,
    NotificationValueEntry,
)


class DiscordNotificationFormatter(AbstractNotificationFormatter):
    @staticmethod
    def _format_link(text, url, link_text=None):
        target_text = link_text or text
        if target_text and target_text in text:
            return text.replace(target_text, f"[{target_text}]({url})", 1)
        return f"[{text}]({url})"

    def render_text_entry(self, entry: NotificationTextEntry):
        return {"name": entry.title, "value": entry.text}

    def render_link_entry(self, entry: NotificationLinkEntry):
        return {
            "name": entry.title,
            "value": self._format_link(entry.text, entry.url, entry.link_text),
        }

    def render_facts_entry(self, entry: NotificationFactsEntry):
        return {
            "name": entry.title,
            "value": " | ".join(
                f"**{fact.label}:** {fact.value}" for fact in entry.facts
            ),
        }

    def render_value_entry(self, entry: NotificationValueEntry):
        return {"name": entry.title, "value": entry.value}

    def render_message(self, message: NotificationMessage):
        embed = {"title": message.title, "description": message.description}
        fields = self.render_entries(message.entries)
        if fields:
            embed["fields"] = fields

        if message.image_url:
            poster_object = {"url": message.image_url}
            embed["thumbnail"] = poster_object
            embed["image"] = poster_object
        elif message.thumbnail_url:
            embed["thumbnail"] = {"url": message.thumbnail_url}

        return embed


def _get_discord_webhook(shared_state):
    settings = shared_state.values.get("notification_settings")
    if not isinstance(settings, dict):
        return ""
    return str(settings.get("discord_webhook") or "").strip()


def _render_payload(message, silent):
    if not isinstance(message, NotificationMessage):
        info(f"Invalid Discord notification payload: {type(message).__name__}")
        return None

    embed = DiscordNotificationFormatter().render_message(message)
    data = {
        "username": "Quasarr",
        "avatar_url": QUASARR_AVATAR,
        "embeds": [embed],
    }

    if silent:
        data["flags"] = SUPPRESS_NOTIFICATIONS
    return data


def _build_webhook_url(webhook_url, message_id=None, wait=False):
    parts = urlsplit(webhook_url)
    path = parts.path.rstrip("/")
    if message_id is not None:
        path = f"{path}/messages/{quote(str(message_id), safe='')}"

    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query.pop("wait", None)
    if wait:
        query["wait"] = "true"

    return urlunsplit(
        (parts.scheme, parts.netloc, path, urlencode(query), parts.fragment)
    )


def _webhook_fingerprint(webhook_url):
    normalized_url = _build_webhook_url(webhook_url)
    return sha256(normalized_url.encode("utf-8")).hexdigest()


def _post(shared_state, message, silent, wait):
    webhook_url = _get_discord_webhook(shared_state)
    if not webhook_url:
        return None if wait else False

    data = _render_payload(message, silent)
    if data is None:
        return None if wait else False

    response = requests.post(
        _build_webhook_url(webhook_url, wait=wait),
        data=json.dumps(data),
        headers={"Content-Type": "application/json"},
        timeout=SESSION_REQUEST_TIMEOUT_SECONDS,
    )
    expected_status = 200 if wait else 204
    if response.status_code != expected_status:
        info(
            f"Failed to send message to Discord webhook. "
            f"Status code: {response.status_code}"
        )
        return None if wait else False

    if wait:
        try:
            response_data = response.json()
        except (TypeError, ValueError):
            info("Discord webhook did not return a valid message response.")
            return None

        message_id = (
            response_data.get("id") if isinstance(response_data, dict) else None
        )
        if not message_id:
            info("Discord webhook message response did not include an ID.")
            return None

        return {
            "message_id": str(message_id),
            "webhook_fingerprint": _webhook_fingerprint(webhook_url),
            "silent": bool(silent),
        }

    return True


def send(shared_state, message, silent=True):
    """Send a rendered Discord webhook notification. Returns True on success."""
    return _post(shared_state, message, silent, wait=False)


def send_tracked(shared_state, message, silent=True):
    """Send a Discord message and return its persisted edit reference."""
    return _post(shared_state, message, silent, wait=True)


def edit(shared_state, reference, message):
    """Edit a tracked Discord webhook message. Returns True on success."""
    webhook_url = _get_discord_webhook(shared_state)
    if not webhook_url or not isinstance(reference, dict):
        return False

    message_id = reference.get("message_id")
    webhook_fingerprint = reference.get("webhook_fingerprint")
    if not message_id or webhook_fingerprint != _webhook_fingerprint(webhook_url):
        return False

    data = _render_payload(message, silent=False)
    if data is None:
        return False
    data.pop("username", None)
    data.pop("avatar_url", None)

    response = requests.patch(
        _build_webhook_url(webhook_url, message_id=message_id),
        data=json.dumps(data),
        headers={"Content-Type": "application/json"},
        timeout=SESSION_REQUEST_TIMEOUT_SECONDS,
    )
    if response.status_code != 200:
        info(
            f"Failed to edit Discord webhook message. "
            f"Status code: {response.status_code}"
        )
        return False
    return True
