# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

from urllib.parse import urlparse

import requests

from quasarr.constants import SESSION_REQUEST_TIMEOUT_SECONDS
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

PUSHOVER_API_URL = "https://api.pushover.net/1/messages.json"
MAX_TITLE_LENGTH = 250
MAX_MESSAGE_LENGTH = 1024
MAX_URL_LENGTH = 512
MAX_URL_TITLE_LENGTH = 100
MAX_ATTACHMENT_BYTES = 5 * 1024 * 1024


def _get_pushover_credentials(shared_state):
    settings = shared_state.values.get("notification_settings")
    if not isinstance(settings, dict):
        return "", ""
    api_token = str(settings.get("pushover_api_token") or "").strip()
    user_key = str(settings.get("pushover_user_key") or "").strip()
    return api_token, user_key


def _get_photo_request_headers(shared_state, image_url):
    headers = {"Accept": "image/*,*/*;q=0.8"}
    user_agent = shared_state.values.get("user_agent")
    if user_agent:
        headers["User-Agent"] = user_agent

    hostname = (urlparse(image_url).hostname or "").lower()
    if hostname.endswith("media-amazon.com") or hostname.endswith("media-imdb.com"):
        headers["Referer"] = "https://www.imdb.com/"
    return headers


def _build_attachment(shared_state, image_url):
    response = None
    try:
        response = requests.get(
            image_url,
            headers=_get_photo_request_headers(shared_state, image_url),
            timeout=SESSION_REQUEST_TIMEOUT_SECONDS,
            stream=True,
        )
        response.raise_for_status()

        content_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip()
        if not content_type.startswith("image/"):
            raise ValueError("Unexpected poster content type")

        image_bytes = response.raw.read(MAX_ATTACHMENT_BYTES + 1, decode_content=True)
        if not image_bytes:
            raise ValueError("Poster download returned an empty response")
        if len(image_bytes) > MAX_ATTACHMENT_BYTES:
            raise ValueError("Poster exceeds Pushover attachment limit")

        filename = urlparse(image_url).path.rsplit("/", 1)[-1] or "poster.jpg"
        if "." not in filename:
            filename += ".jpg"
        return {"attachment": (filename, image_bytes, content_type)}
    finally:
        if response is not None:
            response.close()


class PushoverNotificationFormatter(AbstractNotificationFormatter):
    @staticmethod
    def _render_titled_entry(title, value):
        return f"{title}\n{value}"

    def render_text_entry(self, entry: NotificationTextEntry):
        return self._render_titled_entry(entry.title, entry.text)

    def render_link_entry(self, entry: NotificationLinkEntry):
        return self._render_titled_entry(entry.title, f"{entry.text}\n{entry.url}")

    def render_facts_entry(self, entry: NotificationFactsEntry):
        facts_text = " | ".join(f"{fact.label}: {fact.value}" for fact in entry.facts)
        return self._render_titled_entry(entry.title, facts_text)

    def render_value_entry(self, entry: NotificationValueEntry):
        return self._render_titled_entry(entry.title, entry.value)

    def render_message(self, message: NotificationMessage):
        parts = [message.title, message.description]
        parts.extend(self.render_entries(message.entries))
        return "\n\n".join(str(part) for part in parts if part)


def _first_link(message):
    for entry in message.entries:
        if isinstance(entry, NotificationLinkEntry) and entry.url:
            return entry
    return None


def send(shared_state, message, silent=True):
    """Send one Pushover notification. Return True only on API success."""
    api_token, user_key = _get_pushover_credentials(shared_state)
    if not api_token or not user_key:
        return False

    if not isinstance(message, NotificationMessage):
        info(f"Invalid Pushover notification payload: {type(message).__name__}")
        return False

    formatter = PushoverNotificationFormatter()
    payload = {
        "token": api_token,
        "user": user_key,
        "title": str(message.title)[:MAX_TITLE_LENGTH],
        "message": formatter.render_message(message)[:MAX_MESSAGE_LENGTH],
        "priority": -1 if silent else 0,
    }
    link = _first_link(message)
    if link and len(str(link.url)) <= MAX_URL_LENGTH:
        payload["url"] = str(link.url)
        payload["url_title"] = str(link.link_text or link.text)[:MAX_URL_TITLE_LENGTH]

    files = None
    if message.image_url:
        try:
            files = _build_attachment(shared_state, message.image_url)
        except Exception:
            info("Pushover poster unavailable; sending notification without attachment")

    try:
        response = requests.post(
            PUSHOVER_API_URL,
            data=payload,
            files=files,
            timeout=SESSION_REQUEST_TIMEOUT_SECONDS,
        )
        if response.status_code != 200:
            info("Pushover notification failed with HTTP error")
            return False
        try:
            result = response.json()
        except ValueError:
            result = {}
        if not isinstance(result, dict) or result.get("status") != 1:
            info("Pushover notification failed with API error")
            return False
        return True
    except requests.RequestException:
        info("Pushover notification request failed")
        return False
