# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import os
import time
from urllib.parse import urlparse

from quasarr.persistence.config import Config
from quasarr.persistence.sqlite_database import DataBase
from quasarr.providers.myjd_api import Myjdapi, TokenExpiredException, RequestTimeoutException, MYJDException, Jddevice

values = {}
lock = None
logger = None


def set_state(manager_dict, manager_lock):
    global values
    global lock
    values = manager_dict
    lock = manager_lock


def update(key, value):
    global values
    global lock
    lock.acquire()
    try:
        values[key] = value
    finally:
        lock.release()


def set_sites():
    update("sites", ["NX"])


def set_connection_info(internal_address, port, external_address):
    parsed_url = urlparse(f"http://{internal_address}")
    if not parsed_url.port:
        internal_address = f"{internal_address}:{port}"
    if not external_address:
        external_address = internal_address
    update("internal_address", internal_address)
    update("port", port)
    update("external_address", external_address)


def set_files(config_path):
    update("configfile", os.path.join(config_path, "Quasarr.ini"))
    update("dbfile", os.path.join(config_path, "Quasarr.db"))


def connect_to_jd(jd, user, password, device_name):
    try:
        jd.connect(user, password)
        jd.update_devices()
        device = jd.get_device(device_name)
    except (TokenExpiredException, RequestTimeoutException, MYJDException) as e:
        print("Error connecting to JDownloader: " + str(e))
        return False
    if not device or not isinstance(device, (type, Jddevice)):
        return False
    else:
        device.downloadcontroller.get_current_state()  # request forces direct_connection info update
        connection_info = device.check_direct_connection()
        if connection_info["status"]:
            print(f'Direct connection to JDownloader established: "{connection_info['ip']}"')
        else:
            print("Could not establish direct connection to JDownloader.")
        update("device", device)
        return True


def set_device(user, password, device):
    jd = Myjdapi()
    jd.set_app_key('Quasarr')
    return connect_to_jd(jd, user, password, device)


def set_device_from_config():
    config = Config('JDownloader')
    user = str(config.get('user'))
    password = str(config.get('password'))
    device = str(config.get('device'))

    update("device", device)

    if user and password and device:
        jd = Myjdapi()
        jd.set_app_key('Quasarr')
        return connect_to_jd(jd, user, password, device)
    return False


def check_device(device):
    try:
        valid = isinstance(device,
                           (type, Jddevice)) and device.downloadcontroller.get_current_state()
    except (AttributeError, KeyError, TokenExpiredException, RequestTimeoutException, MYJDException):
        valid = False
    return valid


def connect_device():
    config = Config('JDownloader')
    user = str(config.get('user'))
    password = str(config.get('password'))
    device = str(config.get('device'))

    jd = Myjdapi()
    jd.set_app_key('Quasarr')

    if user and password and device:
        try:
            jd.connect(user, password)
            jd.update_devices()
            device = jd.get_device(device)
        except (TokenExpiredException, RequestTimeoutException, MYJDException):
            pass

    if check_device(device):
        update("device", device)
        return True
    else:
        return False


def get_device():
    attempts = 0

    while True:
        try:
            if check_device(values["device"]):
                break
        except (AttributeError, KeyError, TokenExpiredException, RequestTimeoutException, MYJDException):
            pass
        attempts += 1

        update("device", False)

        if attempts % 10 == 0:
            print(
                f"WARNUNG: {attempts} aufeinanderfolgende JDownloader Verbindungsfehler. Bitte prüfen und ggf. neu starten!")
        time.sleep(3)

        if connect_device():
            break

    return values["device"]


def get_devices(user, password):
    jd = Myjdapi()
    jd.set_app_key('Quasarr')
    try:
        jd.connect(user, password)
        jd.update_devices()
        devices = jd.list_devices()
        return devices
    except (TokenExpiredException, RequestTimeoutException, MYJDException) as e:
        print("Error connecting to JDownloader: " + str(e))
        return []


def get_db(table):
    return DataBase(table)


def sanitize_external_address(external_address):
    try:
        parsed_url = urlparse(external_address)
        if not parsed_url.scheme or not parsed_url.hostname:
            return None
        scheme = parsed_url.scheme
        hostname = parsed_url.hostname
        url_port = f":{parsed_url.port}" if parsed_url.port else ""
        result = f"{scheme}://{hostname}{url_port}/"
        return result
    except Exception as Error:
        print(f"Error sanitizing base URL: {Error}")
        return None
