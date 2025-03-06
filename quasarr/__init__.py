# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import argparse
import multiprocessing
import os
import re
import socket
import sys
import tempfile
import time
from urllib.parse import urlparse

import requests

from quasarr.api import get_api
from quasarr.providers import shared_state, version
from quasarr.providers.log import info, debug
from quasarr.storage.config import Config, get_clean_hostnames
from quasarr.storage.setup import path_config, hostnames_config, hostname_credentials_config, jdownloader_config
from quasarr.storage.sqlite_database import DataBase


def run():
    with multiprocessing.Manager() as manager:
        shared_state_dict = manager.dict()
        shared_state_lock = manager.Lock()
        shared_state.set_state(shared_state_dict, shared_state_lock)

        parser = argparse.ArgumentParser()
        parser.add_argument("--port", help="Desired Port, defaults to 8080")
        parser.add_argument("--internal_address", help="Must be provided when running in Docker")
        parser.add_argument("--external_address", help="External address for CAPTCHA notifications")
        parser.add_argument("--discord", help="Discord Webhook URL")
        parser.add_argument("--hostnames", help="Public HTTP(s) Link that contains hostnames definition.")
        arguments = parser.parse_args()

        sys.stdout = Unbuffered(sys.stdout)

        print(f"""┌────────────────────────────────────┐
  Quasarr {version.get_version()} by RiX
  https://github.com/rix1337/Quasarr
└────────────────────────────────────┘""")

        print("\n===== Recommended Services =====")
        print("- For automated CAPTCHA solutions use SponsorsHelper: https://github.com/users/rix1337/sponsorship")
        print("- For convenient universal premium downloads use: https://linksnappy.com/?ref=397097")

        print("\n===== Startup Info =====")

        port = int('8080')

        config_path = ""
        if os.environ.get('DOCKER'):
            config_path = "/config"
            if not arguments.internal_address:
                print(
                    "You must set the INTERNAL_ADDRESS variable to a locally reachable URL, e.g. http://192.168.1.1:8080")
                print("The local URL will be used by Radarr/Sonarr to connect to Quasarr")
                print("Stopping Quasarr...")
                sys.exit(1)
        else:
            if arguments.port:
                port = int(arguments.port)
            internal_address = f'http://{check_ip()}'

        if arguments.internal_address:
            internal_address = arguments.internal_address
        if arguments.external_address:
            external_address = arguments.external_address
        else:
            external_address = internal_address

        validate_address(internal_address, "--internal_address")
        validate_address(external_address, "--external_address")

        shared_state.set_connection_info(internal_address, external_address, port)

        if not config_path:
            config_path_file = "Quasarr.conf"
            if not os.path.exists(config_path_file):
                path_config(shared_state)
            with open(config_path_file, "r") as f:
                config_path = f.readline().strip()

        os.makedirs(config_path, exist_ok=True)

        try:
            temp_file = tempfile.TemporaryFile(dir=config_path)
            temp_file.close()
        except Exception as e:
            print(f'Could not access "{config_path}": {e}"'
                  f'Stopping Quasarr...')
            sys.exit(1)

        shared_state.set_files(config_path)
        shared_state.update("config", Config)
        shared_state.update("database", DataBase)
        supported_hostnames = extract_allowed_keys(Config._DEFAULT_CONFIG, 'Hostnames')
        shared_state.update("sites", [key.upper() for key in supported_hostnames])
        shared_state.update("user_agent",
                            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36")
        shared_state.update("helper_active", False)

        print(f'Config path: "{config_path}"')

        try:
            if arguments.hostnames:
                hostnames_link = make_raw_pastebin_link(arguments.hostnames)

                if is_valid_url(hostnames_link):
                    print(f"Extracting hostnames from {hostnames_link}...")
                    allowed_keys = supported_hostnames
                    max_keys = len(allowed_keys)
                    shorthand_list = ', '.join(
                        [f'"{key}"' for key in allowed_keys[:-1]]) + ' and ' + f'"{allowed_keys[-1]}"'
                    print(f'There are up to {max_keys} hostnames currently supported: {shorthand_list}')
                    data = requests.get(hostnames_link).text
                    results = extract_kv_pairs(data, allowed_keys)

                    extracted_hostnames = 0

                    if results:
                        hostnames = Config('Hostnames')
                        for shorthand, hostname in results.items():
                            valid_domain = shared_state.extract_valid_hostname(hostname, shorthand)
                            if valid_domain:
                                hostnames.save(shorthand, hostname)
                                extracted_hostnames += 1
                                print(f'Hostname for "{shorthand}" successfully set to "{hostname}"')
                            else:
                                print(f'Skipping invalid hostname for "{shorthand}" ("{hostname}")')
                        if extracted_hostnames == max_keys:
                            print(f'All {max_keys} hostnames successfully extracted!')
                            print('You can now remove the hostnames link from the command line / environment variable.')
                    else:
                        print(f'No Hostnames found at "{hostnames_link}". '
                              'Ensure to pass a plain hostnames list, not html or json!')
                else:
                    print(f"Invalid hostnames URL: {hostnames_link}")
        except Exception as e:
            print(f'Error parsing hostnames link: {e}')

        print("\n===== Configuration =====")
        api_key = Config('API').get('key')
        if not api_key:
            api_key = shared_state.generate_api_key()

        hostnames = get_clean_hostnames(shared_state)
        if not hostnames:
            hostnames_config(shared_state)
            hostnames = get_clean_hostnames(shared_state)
        print(f"You have [{len(hostnames)} of {len(Config._DEFAULT_CONFIG['Hostnames'])}] supported hostnames set up")
        print(f"For efficiency it is recommended to set up as few hostnames as needed.\n")

        dd = Config('Hostnames').get('dd')
        if dd:
            user = Config('DD').get('user')
            password = Config('DD').get('password')
            if not user or not password:
                hostname_credentials_config(shared_state, "DD", dd)

        nx = Config('Hostnames').get('nx')
        if nx:
            user = Config('NX').get('user')
            password = Config('NX').get('password')
            if not user or not password:
                hostname_credentials_config(shared_state, "NX", nx)

        config = Config('JDownloader')
        user = config.get('user')
        password = config.get('password')
        device = config.get('device')

        if not user or not password or not device:
            jdownloader_config(shared_state)

        discord_url = ""
        if arguments.discord:
            discord_webhook_pattern = r'^https://discord\.com/api/webhooks/\d+/[\w-]+$'
            if re.match(discord_webhook_pattern, arguments.discord):
                shared_state.update("webhook", arguments.discord)
                print(f"Using Discord Webhook URL for notifications.")
                discord_url = arguments.discord
            else:
                print(f"Invalid Discord Webhook URL provided: {arguments.discord}")
        else:
            print("No Discord Webhook URL provided")
        shared_state.update("discord", discord_url)

        jdownloader = multiprocessing.Process(target=jdownloader_connection,
                                              args=(shared_state_dict, shared_state_lock))
        jdownloader.start()

        print("\n===== API Information =====")
        print(f"Quasarr API now running at: {shared_state.values['internal_address']}")
        print('Use this exact URL as "Newznab Indexer" and "SABnzbd Download Client" in Radarr/Sonarr')
        print(f'Leave settings at default and use this API key: "{api_key}" (without quotes)')

        print("\n===== Quasarr Info Log =====")
        if os.getenv('DEBUG'):
            print("=====    / Debug Log   =====")

        protected = shared_state.get_db("protected").retrieve_all_titles()
        if protected:
            package_count = len(protected)
            info(f'CAPTCHA-Solution required for {package_count} package{'s' if package_count > 1 else ''} at: '
                 f'{shared_state.values["external_address"]}/captcha!')

        try:
            get_api(shared_state_dict, shared_state_lock)
        except KeyboardInterrupt:
            sys.exit(0)


def jdownloader_connection(shared_state_dict, shared_state_lock):
    shared_state.set_state(shared_state_dict, shared_state_lock)

    shared_state.set_device_from_config()

    connection_established = shared_state.get_device() and shared_state.get_device().name
    if not connection_established:
        i = 0
        while i < 10:
            i += 1
            info(f'Connection {i} to JDownloader failed. Device name: "{shared_state.values["device"]}"')
            time.sleep(60)
            shared_state.set_device_from_config()
            connection_established = shared_state.get_device() and shared_state.get_device().name
            if connection_established:
                break

    try:
        info(f'Connection to JDownloader successful. Device name: "{shared_state.get_device().name}"')
    except Exception as e:
        info(f'Error connecting to JDownloader: {e}! Stopping Quasarr!')
        sys.exit(1)

    try:
        shared_state.set_device_settings()
    except Exception as e:
        print(f"Error checking settings: {e}")

    try:
        shared_state.update_jdownloader()
    except Exception as e:
        print(f"Error updating jdownloader: {e}")

    try:
        shared_state.start_downloads()
    except Exception as e:
        print(f"Error starting downloads: {e}")


class Unbuffered(object):
    def __init__(self, stream):
        self.stream = stream

    def write(self, data):
        self.stream.write(data)
        self.stream.flush()

    def writelines(self, datas):
        self.stream.writelines(datas)
        self.stream.flush()

    def __getattr__(self, attr):
        return getattr(self.stream, attr)


def check_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('10.255.255.255', 0))
        ip = s.getsockname()[0]
    except:
        ip = '127.0.0.1'
    finally:
        s.close()
    return ip


def make_raw_pastebin_link(url):
    """
    Takes a Pastebin URL and ensures it is a raw link.
    If it's not a Pastebin URL, it returns the URL unchanged.
    """
    # Check if the URL is a Pastebin link
    pastebin_pattern = r"https?://(?:www\.)?pastebin\.com/(\w+)"
    match = re.match(pastebin_pattern, url)

    if match:
        paste_id = match.group(1)
        # Construct the raw Pastebin link
        print(f"The link you provided is not a raw Pastebin link. Attempting to convert it to a raw link from {url}...")
        return f"https://pastebin.com/raw/{paste_id}"
    else:
        # Return the URL unchanged if it's not a Pastebin link
        return url


def is_valid_url(url):
    if "https://pastebin.com/raw/eX4Mpl3" in url:
        print("Example URL detected. Please provide a valid URL found on pastebin or another public site!")
        return False

    parsed = urlparse(url)
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def validate_address(address, name):
    if not address.startswith("http"):
        sys.exit(f"Error: {name} '{address}' is invalid. It must start with 'http'.")

    colon_count = address.count(":")
    if colon_count < 1 or colon_count > 2:
        sys.exit(
            f"Error: {name} '{address}' is invalid. It must contain 1 or 2 colons, but it has {colon_count}.")


def extract_allowed_keys(config, section):
    """
    Extracts allowed keys from the specified section in the configuration.

    :param config: The configuration dictionary.
    :param section: The section from which to extract keys.
    :return: A list of allowed keys.
    """
    if section not in config:
        raise ValueError(f"Section '{section}' not found in configuration.")
    return [key for key, *_ in config[section]]


def extract_kv_pairs(input_text, allowed_keys):
    """
    Extracts key-value pairs from the given text where keys match allowed_keys.

    :param input_text: The input text containing key-value pairs.
    :param allowed_keys: A list of allowed two-letter shorthand keys.
    :return: A dictionary of extracted key-value pairs.
    """
    kv_pattern = re.compile(rf"^({'|'.join(map(re.escape, allowed_keys))})\s*=\s*(.*)$")
    kv_pairs = {}

    for line in input_text.splitlines():
        match = kv_pattern.match(line.strip())
        if match:
            key, value = match.groups()
            kv_pairs[key] = value
        else:
            print(f"Skipping line because it does not contain any supported hostname: {line}")

    return kv_pairs
