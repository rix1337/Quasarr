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
    if case == "captcha":
        if shared_state.values.get("helper_active"):
            helper_text = f"Thanks for being a Sponsor! The CAPTCHA will be solved automatically asap."
        else:
            helper_text = f'[Become a sponsor and let SponsorsHelper decrypt links for you]({f"https://github.com/users/rix1337/sponsorship"})'

        description = 'Links are protected. Please solve the CAPTCHA to start downloading.'
        fields = [
            {
                'name': 'Automatically',
                'value': helper_text,
            },
            {
                'name': 'Manually',
                'value': f'[Solve the CAPTCHA here yourself]({f"{shared_state.values['external_address']}/captcha"})',
            }
        ]
    elif case == "solved":
        description = 'Links automatically decrypted by SponsorsHelper!'
        fields = None
    elif case == "deleted":
        description = 'SponsorsHelper failed to solve the CAPTCHA! Package deleted.'
        fields = None
    else:
        print(f"Unknown case: {case}")
        return False

    # Construct the data payload
    data = {
        'username': 'Quasarr',
        'avatar_url': 'https://raw.githubusercontent.com/rix1337/Quasarr/main/Quasarr.png',
        'embeds': [{
            'title': title,
            'description': description,
        }]
    }

    # Add fields if required
    if fields:
        data['embeds'][0]['fields'] = fields

    # Send the message to Discord webhook
    response = requests.post(shared_state.values["discord"], data=json.dumps(data),
                             headers={"Content-Type": "application/json"})
    if response.status_code != 204:
        print(f"Failed to send message to Discord webhook. Status code: {response.status_code}")
        return False

    return True
