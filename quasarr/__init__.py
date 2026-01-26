# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import argparse
import multiprocessing
import os
import re
import sys
import tempfile
import time

import requests

import quasarr.providers.web_server
from quasarr.api import get_api
from quasarr.providers import shared_state, version
from quasarr.providers.log import debug, info
from quasarr.providers.notifications import send_discord_message
from quasarr.providers.utils import (
    FALLBACK_USER_AGENT,
    Unbuffered,
    check_flaresolverr,
    check_ip,
    extract_allowed_keys,
    extract_kv_pairs,
    is_valid_url,
    validate_address,
)
from quasarr.storage.config import Config, get_clean_hostnames
from quasarr.storage.setup import (
    flaresolverr_config,
    hostname_credentials_config,
    hostnames_config,
    jdownloader_config,
    path_config,
)
from quasarr.storage.sqlite_database import DataBase


def run():
    with multiprocessing.Manager() as manager:
        shared_state_dict = manager.dict()
        shared_state_lock = manager.Lock()
        shared_state.set_state(shared_state_dict, shared_state_lock)

        parser = argparse.ArgumentParser()
        parser.add_argument("--port", help="Desired Port, defaults to 8080")
        parser.add_argument(
            "--internal_address", help="Must be provided when running in Docker"
        )
        parser.add_argument(
            "--external_address", help="External address for CAPTCHA notifications"
        )
        parser.add_argument("--discord", help="Discord Webhook URL")
        parser.add_argument(
            "--hostnames",
            help="Public HTTP(s) Link that contains hostnames definition.",
        )
        arguments = parser.parse_args()

        sys.stdout = Unbuffered(sys.stdout)

        print(f"""┌────────────────────────────────────┐
  Quasarr {version.get_version()} by RiX
  https://github.com/rix1337/Quasarr
└────────────────────────────────────┘""")

        print("\n===== Recommended Services =====")
        print(
            'For convenient universal premium downloads use: "https://linksnappy.com/?ref=397097"'
        )
        print(
            'Sponsors get automated CAPTCHA solutions: "https://github.com/rix1337/Quasarr?tab=readme-ov-file#sponsorshelper"'
        )

        print("\n===== Startup Info =====")
        port = int("8080")
        config_path = ""
        if os.environ.get("DOCKER"):
            config_path = "/config"
            if not arguments.internal_address:
                print(
                    "You must set the INTERNAL_ADDRESS variable to a locally reachable URL, e.g. http://192.168.1.1:8080"
                )
                print(
                    "The local URL will be used by Radarr/Sonarr to connect to Quasarr"
                )
                print("Stopping Quasarr...")
                sys.exit(1)
        else:
            if arguments.port:
                port = int(arguments.port)
            internal_address = f"http://{check_ip()}:{port}"

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
            print(f'Could not access "{config_path}": {e}"Stopping Quasarr...')
            sys.exit(1)

        shared_state.set_files(config_path)
        shared_state.update("config", Config)
        shared_state.update("database", DataBase)
        supported_hostnames = extract_allowed_keys(Config._DEFAULT_CONFIG, "Hostnames")
        shared_state.update("sites", [key.upper() for key in supported_hostnames])
        # Set fallback user agent immediately so it's available while background check runs
        shared_state.update("user_agent", FALLBACK_USER_AGENT)
        shared_state.update("helper_active", False)

        print(f'Config path: "{config_path}"')

        print("\n===== Hostnames =====")
        try:
            if arguments.hostnames:
                hostnames_link = arguments.hostnames
                if is_valid_url(hostnames_link):
                    # Store the hostnames URL for later use in web UI
                    Config("Settings").save("hostnames_url", hostnames_link)
                    print(f"Extracting hostnames from {hostnames_link}...")
                    allowed_keys = supported_hostnames
                    max_keys = len(allowed_keys)
                    shorthand_list = (
                        ", ".join([f'"{key}"' for key in allowed_keys[:-1]])
                        + " and "
                        + f'"{allowed_keys[-1]}"'
                    )
                    print(
                        f"There are up to {max_keys} hostnames currently supported: {shorthand_list}"
                    )
                    data = requests.get(hostnames_link).text
                    results = extract_kv_pairs(data, allowed_keys)

                    extracted_hostnames = 0

                    if results:
                        hostnames = Config("Hostnames")
                        for shorthand, hostname in results.items():
                            domain_check = shared_state.extract_valid_hostname(
                                hostname, shorthand
                            )
                            valid_domain = domain_check.get("domain", None)
                            if valid_domain:
                                hostnames.save(shorthand, hostname)
                                extracted_hostnames += 1
                                print(
                                    f'Hostname for "{shorthand}" successfully set to "{hostname}"'
                                )
                            else:
                                print(
                                    f'Skipping invalid hostname for "{shorthand}" ("{hostname}")'
                                )
                        if extracted_hostnames == max_keys:
                            print(f"All {max_keys} hostnames successfully extracted!")
                            print(
                                "You can now remove the hostnames link from the command line / environment variable."
                            )
                    else:
                        print(
                            f'No Hostnames found at "{hostnames_link}". '
                            "Ensure to pass a plain hostnames list, not html or json!"
                        )
                else:
                    print(f'Invalid hostnames URL: "{hostnames_link}"')
        except Exception as e:
            print(f'Error parsing hostnames link: "{e}"')

        hostnames = get_clean_hostnames(shared_state)
        if not hostnames:
            hostnames_config(shared_state)
            hostnames = get_clean_hostnames(shared_state)
        print(
            f"You have [{len(hostnames)} of {len(Config._DEFAULT_CONFIG['Hostnames'])}] supported hostnames set up"
        )
        print(f"For efficiency it is recommended to set up as few hostnames as needed.")

        # Check credentials for login-required hostnames
        skip_login_db = DataBase("skip_login")
        login_required_sites = ["al", "dd", "dl", "nx"]

        quasarr.providers.web_server.temp_server_success = False

        for site in login_required_sites:
            hostname = Config("Hostnames").get(site)
            if hostname:
                site_config = Config(site.upper())
                user = site_config.get("user")
                password = site_config.get("password")
                if not user or not password:
                    skip_val = skip_login_db.retrieve(site)
                    if skip_val and str(skip_val).lower() == "true":
                        info(f'"{site.upper()}" login skipped by user preference')
                    else:
                        info(
                            f'"{site.upper()}" credentials missing. Launching setup...'
                        )
                        quasarr.providers.web_server.temp_server_success = False
                        hostname_credentials_config(
                            shared_state, site.upper(), hostname
                        )

        # Check FlareSolverr configuration
        skip_flaresolverr_db = DataBase("skip_flaresolverr")
        flaresolverr_skipped = skip_flaresolverr_db.retrieve("skipped")
        flaresolverr_url = Config("FlareSolverr").get("url")

        if not flaresolverr_url and not flaresolverr_skipped:
            flaresolverr_config(shared_state)

        config = Config("JDownloader")
        user = config.get("user")
        password = config.get("password")
        device = config.get("device")

        if not user or not password or not device:
            jdownloader_config(shared_state)

        print("\n===== Notifications =====")
        discord_url = ""
        if arguments.discord:
            discord_webhook_pattern = r"^https://discord\.com/api/webhooks/\d+/[\w-]+$"
            if re.match(discord_webhook_pattern, arguments.discord):
                shared_state.update("webhook", arguments.discord)
                print(f"Using Discord Webhook URL for notifications.")
                discord_url = arguments.discord
            else:
                print(f"Invalid Discord Webhook URL provided: {arguments.discord}")
        else:
            print("No Discord Webhook URL provided")
        shared_state.update("discord", discord_url)

        print("\n===== API Information =====")
        api_key = Config("API").get("key")
        if not api_key:
            api_key = shared_state.generate_api_key()

        print(
            'Setup instructions: "https://github.com/rix1337/Quasarr?tab=readme-ov-file#instructions"'
        )
        print(f'URL: "{shared_state.values["internal_address"]}"')
        print(f'API Key: "{api_key}" (without quotes)')

        if external_address != internal_address:
            print(f'External URL: "{shared_state.values["external_address"]}"')

        print("\n===== Quasarr Info Log =====")
        if os.getenv("DEBUG"):
            print("=====    / Debug Log   =====")

        protected = shared_state.get_db("protected").retrieve_all_titles()
        if protected:
            package_count = len(protected)
            info(
                f"CAPTCHA-Solution required for {package_count} package{'s' if package_count > 1 else ''} at: "
                f'"{shared_state.values["external_address"]}/captcha"!'
            )

        flaresolverr = multiprocessing.Process(
            target=flaresolverr_checker,
            args=(shared_state_dict, shared_state_lock),
            daemon=True,
        )
        flaresolverr.start()

        jdownloader = multiprocessing.Process(
            target=jdownloader_connection,
            args=(shared_state_dict, shared_state_lock),
            daemon=True,
        )
        jdownloader.start()

        updater = multiprocessing.Process(
            target=update_checker,
            args=(shared_state_dict, shared_state_lock),
            daemon=True,
        )
        updater.start()

        try:
            get_api(shared_state_dict, shared_state_lock)
        except KeyboardInterrupt:
            sys.exit(0)


def flaresolverr_checker(shared_state_dict, shared_state_lock):
    try:
        shared_state.set_state(shared_state_dict, shared_state_lock)

        # Check if FlareSolverr was previously skipped
        skip_flaresolverr_db = DataBase("skip_flaresolverr")
        flaresolverr_skipped = skip_flaresolverr_db.retrieve("skipped")

        flaresolverr_url = Config("FlareSolverr").get("url")

        # If FlareSolverr is not configured and not skipped, it means it's the first run
        # and the user needs to be prompted via the WebUI.
        # This background process should NOT block or prompt the user.
        # It should only check and log the status.
        if not flaresolverr_url and not flaresolverr_skipped:
            info("FlareSolverr URL not configured. Please configure it via the WebUI.")
            info("Some sites (AL) will not work without FlareSolverr.")
            return  # Exit the checker, it will be re-checked if user configures it later

        if flaresolverr_skipped:
            info("FlareSolverr setup skipped by user preference")
            info(
                "Some sites (AL) will not work without FlareSolverr. Configure it later in the web UI."
            )
        elif flaresolverr_url:
            info(f'Checking FlareSolverr at URL: "{flaresolverr_url}"')
            flaresolverr_check = check_flaresolverr(shared_state, flaresolverr_url)
            if flaresolverr_check:
                info(
                    f'FlareSolverr connection successful. Using User-Agent: "{shared_state.values["user_agent"]}"'
                )
            else:
                info("FlareSolverr check failed - using fallback user agent")
                # Fallback user agent is already set in main process, but we log it
                info(f'User Agent (fallback): "{FALLBACK_USER_AGENT}"')

    except KeyboardInterrupt:
        pass
    except Exception as e:
        info(f"An unexpected error occurred in FlareSolverr checker: {e}")


def update_checker(shared_state_dict, shared_state_lock):
    try:
        shared_state.set_state(shared_state_dict, shared_state_lock)

        message = "!!! UPDATE AVAILABLE !!!"
        link = "https://github.com/rix1337/Quasarr/releases/latest"

        shared_state.update("last_checked_version", f"v.{version.get_version()}")

        while True:
            try:
                update_available = version.newer_version_available()
            except Exception as e:
                info(f"Error getting latest version: {e}")
                info(f'Please manually check: "{link}" for more information!')
                update_available = None

            if (
                update_available
                and shared_state.values["last_checked_version"] != update_available
            ):
                shared_state.update("last_checked_version", update_available)
                info(message)
                info(f"Please update to {update_available} as soon as possible!")
                info(f'Release notes at: "{link}"')
                update_available = {"version": update_available, "link": link}
                send_discord_message(
                    shared_state, message, "quasarr_update", details=update_available
                )

            # wait one hour before next check
            time.sleep(60 * 60)
    except KeyboardInterrupt:
        pass


def jdownloader_connection(shared_state_dict, shared_state_lock):
    try:
        shared_state.set_state(shared_state_dict, shared_state_lock)

        shared_state.set_device_from_config()

        connection_established = (
            shared_state.get_device() and shared_state.get_device().name
        )
        if not connection_established:
            i = 0
            while i < 10:
                i += 1
                info(
                    f'Connection {i} to JDownloader failed. Device name: "{shared_state.values["device"]}"'
                )
                time.sleep(60)
                shared_state.set_device_from_config()
                connection_established = (
                    shared_state.get_device() and shared_state.get_device().name
                )
                if connection_established:
                    break

        try:
            info(
                f'Connection to JDownloader successful. Device name: "{shared_state.get_device().name}"'
            )
        except Exception as e:
            info(f"Error connecting to JDownloader: {e}! Stopping Quasarr!")
            sys.exit(1)

        try:
            shared_state.set_device_settings()
        except Exception as e:
            print(f"Error checking settings: {e}")

        try:
            shared_state.update_jdownloader()
        except Exception as e:
            print(f"Error updating JDownloader: {e}")

        try:
            shared_state.start_downloads()
        except Exception as e:
            print(f"Error starting downloads: {e}")

    except KeyboardInterrupt:
        pass
