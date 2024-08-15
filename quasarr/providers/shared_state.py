# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import os
import time

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
    update("sites", ["FX", "NX"])


def set_connection_info(internal_address, port):
    if internal_address.count(":") < 2:
        internal_address = f"{internal_address}:{port}"
    update("internal_address", internal_address)
    update("port", port)


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


def convert_to_mb(item):
    size = float(item['size'])
    unit = item['sizeunit'].upper()

    if unit == 'B':
        size_b = size
    elif unit == 'KB':
        size_b = size * 1024
    elif unit == 'MB':
        size_b = size * 1024 * 1024
    elif unit == 'GB':
        size_b = size * 1024 * 1024 * 1024
    elif unit == 'TB':
        size_b = size * 1024 * 1024 * 1024 * 1024
    else:
        raise ValueError(f"Unsupported size unit {item['name']} {item['size']} {item['sizeunit']}")

    size_mb = size_b / (1024 * 1024)
    return int(size_mb)
