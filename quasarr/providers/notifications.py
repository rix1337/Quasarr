# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import json

import requests

from quasarr.providers.imdb_metadata import get_imdb_id_from_title
from quasarr.providers.imdb_metadata import get_poster_link
from quasarr.providers.log import info


def send_discord_message(shared_state, title, case, imdb_id=None):
    """
    Sends a Discord message to the webhook provided in the shared state, based on the specified case.

    :param shared_state: Shared state object containing configuration.
    :param title: Title of the embed to be sent.
    :param case: A string representing the scenario (e.g., 'captcha', 'captcha_solved', 'package_deleted').
    :param imdb_id: A string starting with "tt" followed by at least 7 digits, representing an object on IMDb
    :return: True if the message was sent successfully, False otherwise.
    """
    if not shared_state.values.get("discord"):
        return False

    poster_object = None
    if case == "unprotected" or case == "captcha":
        if not imdb_id:
            imdb_id = get_imdb_id_from_title(shared_state, title)
        if imdb_id:
            poster_link = get_poster_link(shared_state, imdb_id)
            if poster_link:
                poster_object = {
                    'url': poster_link
                }

    # Decide the embed content based on the case
    if case == "unprotected":
        description = 'No CAPTCHA required. Links were added directly!'
        fields = None
    elif case == "solved":
        description = 'CAPTCHA solved by SponsorsHelper!'
        fields = None
    elif case == "deleted":
        description = 'SponsorsHelper failed to solve the CAPTCHA! Package deleted.'
        fields = None
    elif case == "captcha":
        description = 'Download will proceed, once the CAPTCHA has been solved.'
        fields = [
            {
                'name': 'Solve CAPTCHA',
                'value': f'Open [this link]({f"{shared_state.values['external_address']}/captcha"}) to solve the CAPTCHA.',
            }
        ]
        if not shared_state.values.get("helper_active"):
            fields.append({
                'name': 'SponsorsHelper',
                'value': f'[Become a Sponsor and let SponsorsHelper solve CAPTCHAs for you!]({f"https://github.com/users/rix1337/sponsorship"})',
            }, )
    else:
        info(f"Unknown notification case: {case}")
        return False

    data = {
        'username': 'Quasarr',
        'avatar_url': 'https://raw.githubusercontent.com/rix1337/Quasarr/main/Quasarr.png',
        'embeds': [{
            'title': title,
            'description': description,
        }]
    }

    if fields:
        data['embeds'][0]['fields'] = fields

    if poster_object:
        data['embeds'][0]['thumbnail'] = poster_object
        data['embeds'][0]['image'] = poster_object

    response = requests.post(shared_state.values["discord"], data=json.dumps(data),
                             headers={"Content-Type": "application/json"})
    if response.status_code != 204:
        info(f"Failed to send message to Discord webhook. Status code: {response.status_code}")
        return False

    return True
