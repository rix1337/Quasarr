# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import json

import requests


def send_discord_captcha_alert(shared_state, title):
    if not shared_state.values.get("discord"):
        return False

    data = {
        'username': 'Quasarr',
        'avatar_url': 'https://i.imgur.com/UXBdr1h.png',
        'embeds': [{
            'title': title,
            'description': 'Links are protected. Please solve the CAPTCHA to continue downloading.',
            'fields': [
                {
                    'name': '',
                    'value': f'[Solve the CAPTCHA here!]({f"{shared_state.values['external_address']}/captcha"})',
                }

            ]
        }]
    }

    response = requests.post(shared_state.values["discord"], data=json.dumps(data),
                             headers={"Content-Type": "application/json"})
    if response.status_code != 204:
        print(f"Failed to send message to Discord webhook. Status code: {response.status_code}")
        return False

    return True
