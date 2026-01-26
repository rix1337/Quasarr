# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import json
import os

import requests

from quasarr.providers.imdb_metadata import get_imdb_id_from_title, get_poster_link
from quasarr.providers.log import info

# Discord message flag for suppressing notifications
SUPPRESS_NOTIFICATIONS = 1 << 12  # 4096

silent = False
if os.getenv("SILENT"):
    silent = True


def send_discord_message(
    shared_state, title, case, imdb_id=None, details=None, source=None
):
    """
    Sends a Discord message to the webhook provided in the shared state, based on the specified case.

    :param shared_state: Shared state object containing configuration.
    :param title: Title of the embed to be sent.
    :param case: A string representing the scenario (e.g., 'captcha', 'failed', 'unprotected').
    :param imdb_id: A string starting with "tt" followed by at least 7 digits, representing an object on IMDb
    :param details: A dictionary containing additional details, such as version and link for updates.
    :param source: Optional source of the notification, sent as a field in the embed.
    :return: True if the message was sent successfully, False otherwise.
    """
    if not shared_state.values.get("discord"):
        return False

    poster_object = None
    if case == "unprotected" or case == "captcha":
        if (
            not imdb_id and " " not in title
        ):  # this should prevent imdb_search for ebooks and magazines
            imdb_id = get_imdb_id_from_title(shared_state, title)
        if imdb_id:
            poster_link = get_poster_link(shared_state, imdb_id)
            if poster_link:
                poster_object = {"url": poster_link}

    # Decide the embed content based on the case
    if case == "unprotected":
        description = "No CAPTCHA required. Links were added directly!"
        fields = None
    elif case == "solved":
        description = "CAPTCHA solved by SponsorsHelper!"
        fields = None
    elif case == "failed":
        description = "SponsorsHelper failed to solve the CAPTCHA! Package marked as failed for deletion."
        fields = None
    elif case == "disabled":
        description = "SponsorsHelper failed to solve the CAPTCHA! Please solve it manually to proceed."
        fields = None
    elif case == "captcha":
        description = "Download will proceed, once the CAPTCHA has been solved."
        fields = [
            {
                "name": "Solve CAPTCHA",
                "value": f"Open [this link]({f'{shared_state.values["external_address"]}/captcha'}) to solve the CAPTCHA.",
            }
        ]
        if not shared_state.values.get("helper_active"):
            fields.append(
                {
                    "name": "SponsorsHelper",
                    "value": f"[Sponsors get automated CAPTCHA solutions!](https://github.com/rix1337/Quasarr?tab=readme-ov-file#sponsorshelper)",
                }
            )
    elif case == "quasarr_update":
        description = f"Please update to {details['version']} as soon as possible!"
        if details:
            fields = [
                {
                    "name": "Release notes at: ",
                    "value": f"[GitHub.com: rix1337/Quasarr/{details['version']}]({details['link']})",
                }
            ]
        else:
            fields = None
    else:
        info(f"Unknown notification case: {case}")
        return False

    data = {
        "username": "Quasarr",
        "avatar_url": "https://raw.githubusercontent.com/rix1337/Quasarr/main/Quasarr.png",
        "embeds": [
            {
                "title": title,
                "description": description,
            }
        ],
    }

    if source and source.startswith("http"):
        if not fields:
            fields = []
        fields.append(
            {
                "name": "Source",
                "value": f"[View release details here]({source})",
            }
        )

    if fields:
        data["embeds"][0]["fields"] = fields

    if poster_object:
        data["embeds"][0]["thumbnail"] = poster_object
        data["embeds"][0]["image"] = poster_object
    elif case == "quasarr_update":
        data["embeds"][0]["thumbnail"] = {
            "url": "https://raw.githubusercontent.com/rix1337/Quasarr/main/Quasarr.png"
        }

    # Apply silent mode: suppress notifications for all cases except 'deleted'
    if silent and case not in ["failed", "quasarr_update", "disabled"]:
        data["flags"] = SUPPRESS_NOTIFICATIONS

    response = requests.post(
        shared_state.values["discord"],
        data=json.dumps(data),
        headers={"Content-Type": "application/json"},
    )
    if response.status_code != 204:
        info(
            f"Failed to send message to Discord webhook. Status code: {response.status_code}"
        )
        return False

    return True
