# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import json

import requests


def send_discord_message(shared_state, title, case):
    """
    Sends a Discord message to the webhook provided in the shared state, based on the specified case.

    :param shared_state: Shared state object containing configuration.
    :param title: Title of the embed to be sent.
    :param case: A string representing the scenario (e.g., 'captcha', 'captcha_solved', 'package_deleted').
    :return: True if the message was sent successfully, False otherwise.
    """
    if not shared_state.values.get("discord"):
        return False

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
        if shared_state.values.get("helper_active"):
            helper_text = f"Just wait - SponsorsHelper will solve this CAPTCHA for you shortly."
        else:
            helper_text = f'[Become a Sponsor and let SponsorsHelper solve CAPTCHAs for you!]({f"https://github.com/users/rix1337/sponsorship"})'

        description = 'Links are protected by a CAPTCHA! Choose how to proceed below:'
        fields = [
            {
                'name': 'Automatically',
                'value': helper_text,
            },
            {
                'name': 'Manually',
                'value': f'Solve the CAPTCHA [here]({f"{shared_state.values['external_address']}/captcha"}) to start the download immediately.',
            }
        ]
    else:
        print(f"Unknown notification case: {case}")
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

    response = requests.post(shared_state.values["discord"], data=json.dumps(data),
                             headers={"Content-Type": "application/json"})
    if response.status_code != 204:
        print(f"Failed to send message to Discord webhook. Status code: {response.status_code}")
        return False

    return True
