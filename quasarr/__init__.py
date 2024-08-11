# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import argparse
import multiprocessing
import os
import socket
import sys
import tempfile
import time

from quasarr.arr import api
from quasarr.persistence.config import Config, get_clean_hostnames
from quasarr.persistence.sqlite_database import DataBase
from quasarr.providers import shared_state, version
from quasarr.providers.setup import path_config, hostnames_config, nx_credentials_config, jdownloader_config


def run():
    with multiprocessing.Manager() as manager:
        shared_state_dict = manager.dict()
        shared_state_lock = manager.Lock()
        shared_state.set_state(shared_state_dict, shared_state_lock)

        parser = argparse.ArgumentParser()
        parser.add_argument("--port", help="Desired Port, defaults to 8080")
        parser.add_argument("--internal_address", help="Must be provided when running in Docker")
        arguments = parser.parse_args()

        sys.stdout = Unbuffered(sys.stdout)

        print(f"""┌────────────────────────────────────┐
  Quasarr {version.get_version()} by RiX
  https://github.com/rix1337/Quasarr
└────────────────────────────────────┘""")

        port = int('8080')

        config_path = ""
        if os.environ.get('DOCKER'):
            config_path = "/config"
            if not arguments.internal_address:
                print(
                    "You must set the INTERNAL_ADDRESS variable to a locally reachable URL, e.g. http://localhost:8080")
                print("The local URL will be used by Radarr/Sonarr to connect to Quasarr")
                print("Stopping Quasarr...")
                sys.exit(1)
        else:
            if arguments.port:
                port = int(arguments.port)
            internal_address = f'http://{check_ip()}'

        if arguments.internal_address:
            internal_address = arguments.internal_address

        shared_state.set_connection_info(internal_address, port)

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
        shared_state.update("user_agent",
                            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

        print(f'Config path: "{config_path}"')

        shared_state.set_sites()

        if not get_clean_hostnames(shared_state):
            hostnames_config(shared_state)
            get_clean_hostnames(shared_state)

        if Config('Hostnames').get('nx'):
            user = Config('NX').get('user')
            password = Config('NX').get('password')
            if not user or not password:
                nx_credentials_config(shared_state)

        config = Config('JDownloader')
        user = config.get('user')
        password = config.get('password')
        device = config.get('device')

        if not user or not password or not device:
            jdownloader_config(shared_state)

        jdownloader = multiprocessing.Process(target=jdownloader_connection,
                                              args=(shared_state_dict, shared_state_lock))
        jdownloader.start()

        print(f'\nQuasarr API now running at "{shared_state.values["internal_address"]}"')
        print('Use this exact URL as "Newznab Indexer" and "SABnzbd Download Client" in Sonarr/Radarr')
        print("Leave settings at default and use this API key: 'quasarr'")

        protected = shared_state.get_db("protected").retrieve_all_titles()
        if protected:
            package_count = len(protected)
            print(f"\nCAPTCHA-Solution required for {package_count} package{'s' if package_count > 1 else ''} at "
                  f'{shared_state.values["internal_address"]}/captcha"!\n')

        try:
            api(shared_state_dict, shared_state_lock)
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
            print(f'Connection {i} to JDownloader failed. Device name: "{shared_state.values["device"]}"')
            time.sleep(60)
            shared_state.set_device_from_config()
            connection_established = shared_state.get_device() and shared_state.get_device().name
            if connection_established:
                break

    if connection_established:
        print(f'Connection to JDownloader successful. Device name: "{shared_state.get_device().name}"')
    else:
        print('Error connecting to JDownloader! Stopping Quasarr!')
        sys.exit(1)


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
