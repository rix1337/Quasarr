# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import json
import os
import re
import time
from datetime import datetime, timedelta
from urllib import parse

from quasarr.providers.log import info, debug
from quasarr.providers.myjd_api import Myjdapi, TokenExpiredException, RequestTimeoutException, MYJDException, Jddevice
from quasarr.storage.config import Config
from quasarr.storage.sqlite_database import DataBase

values = {}
lock = None


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


def set_connection_info(internal_address, external_address, port):
    if internal_address.count(":") < 2:
        internal_address = f"{internal_address}:{port}"
    update("internal_address", internal_address)
    update("external_address", external_address)
    update("port", port)


def set_files(config_path):
    update("configfile", os.path.join(config_path, "Quasarr.ini"))
    update("dbfile", os.path.join(config_path, "Quasarr.db"))


def generate_api_key():
    api_key = os.urandom(24).hex()
    Config('API').save("key", api_key)
    info(f'API key replaced with: "{api_key}!"')
    return api_key


def extract_valid_hostname(url, shorthand):
    # Check if both characters from the shorthand appear in the url
    try:
        if '://' not in url:
            url = 'http://' + url
        result = parse.urlparse(url)
        domain = result.netloc

        # Check if both characters in the shorthand are in the domain
        if all(char in domain for char in shorthand):
            print(f'"{domain}" matches both characters from "{shorthand}". Continuing...')
            return domain
        else:
            print(f'Invalid domain "{domain}": Does not contain both characters from shorthand "{shorthand}"')
            return None
    except Exception as e:
        print(f"Error parsing URL {url}: {e}")
        return None


def connect_to_jd(jd, user, password, device_name):
    try:
        jd.connect(user, password)
        jd.update_devices()
        device = jd.get_device(device_name)
    except (TokenExpiredException, RequestTimeoutException, MYJDException) as e:
        info("Error connecting to JDownloader: " + str(e).strip())
        return False
    if not device or not isinstance(device, (type, Jddevice)):
        return False
    else:
        device.downloadcontroller.get_current_state()  # request forces direct_connection info update
        connection_info = device.check_direct_connection()
        if connection_info["status"]:
            info(f'Direct connection to JDownloader established: "{connection_info['ip']}"')
        else:
            info("Could not establish direct connection to JDownloader.")
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
            info(
                f"WARNING: {attempts} consecutive JDownloader connection errors. Please check your credentials!")
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
        info("Error connecting to JDownloader: " + str(e))
        return []


def set_device_settings():
    device = get_device()

    settings_to_enforce = [
        {
            "namespace": "org.jdownloader.settings.GeneralSettings",
            "storage": None,
            "setting": "AutoStartDownloadOption",
            "expected_value": "ALWAYS",
        },
        {
            "namespace": "org.jdownloader.settings.GeneralSettings",
            "storage": None,
            "setting": "IfFileExistsAction",
            "expected_value": "SKIP_FILE",
        },
        {
            "namespace": "org.jdownloader.settings.GeneralSettings",
            "storage": None,
            "setting": "CleanupAfterDownloadAction",
            "expected_value": "NEVER",
        },
        {
            "namespace": "org.jdownloader.settings.GraphicalUserInterfaceSettings",
            "storage": None,
            "setting": "BannerEnabled",
            "expected_value": False,
        },
        {
            "namespace": "org.jdownloader.settings.GraphicalUserInterfaceSettings",
            "storage": None,
            "setting": "DonateButtonState",
            "expected_value": "CUSTOM_HIDDEN",
        },
        {
            "namespace": "org.jdownloader.extensions.extraction.ExtractionConfig",
            "storage": "cfg/org.jdownloader.extensions.extraction.ExtractionExtension",
            "setting": "DeleteArchiveFilesAfterExtractionAction",
            "expected_value": "NULL",
        },
        {
            "namespace": "org.jdownloader.extensions.extraction.ExtractionConfig",
            "storage": "cfg/org.jdownloader.extensions.extraction.ExtractionExtension",
            "setting": "IfFileExistsAction",
            "expected_value": "OVERWRITE_FILE",
        },
        {
            "namespace": "org.jdownloader.extensions.extraction.ExtractionConfig",
            "storage": "cfg/org.jdownloader.extensions.extraction.ExtractionExtension",
            "setting": "DeleteArchiveDownloadlinksAfterExtraction",
            "expected_value": False,
        },
    ]

    for setting in settings_to_enforce:
        namespace = setting["namespace"]
        storage = setting["storage"] or "null"
        name = setting["setting"]
        expected_value = setting["expected_value"]

        settings = device.config.get(namespace, storage, name)

        if settings != expected_value:
            success = device.config.set(namespace, storage, name, expected_value)

            location = f"{namespace}/{storage}" if storage != "null" else namespace
            status = "Updated" if success else "Failed to update"
            info(f'{status} "{name}" in "{location}" to "{expected_value}".')

    settings_to_add = [
        {
            "namespace": "org.jdownloader.extensions.extraction.ExtractionConfig",
            "storage": "cfg/org.jdownloader.extensions.extraction.ExtractionExtension",
            "setting": "BlacklistPatterns",
            "expected_values": [
                '.*sample/.*',
                '.*Sample/.*',
                '.*\\.jpe?g',
                '.*\\.idx',
                '.*\\.sub',
                '.*\\.srt',
                '.*\\.nfo',
                '.*\\.sfv'
            ]
        },
        {
            "namespace": "org.jdownloader.controlling.filter.LinkFilterSettings",
            "storage": "null",
            "setting": "FilterList",
            "expected_values": [
                {
                    'conditionFilter':
                        {'conditions': [], 'enabled': False, 'matchType': 'IS_TRUE'},
                    'created': 0,
                    'enabled': True,
                    'filenameFilter': {'enabled': False, 'matchType': 'CONTAINS', 'regex': '', 'useRegex': False},
                    'filesizeFilter': {'enabled': False, 'from': 0, 'matchType': 'BETWEEN', 'to': 0},
                    'filetypeFilter': {'archivesEnabled': False, 'audioFilesEnabled': False, 'customs': None,
                                       'docFilesEnabled': False, 'enabled': False, 'exeFilesEnabled': False,
                                       'hashEnabled': False, 'imagesEnabled': False, 'matchType': 'IS',
                                       'subFilesEnabled': False, 'useRegex': False, 'videoFilesEnabled': False},
                    'hosterURLFilter': {'enabled': False, 'matchType': 'CONTAINS', 'regex': '', 'useRegex': False},
                    'matchAlwaysFilter': {'enabled': False}, 'name': 'Quasarr_Block_Offline',
                    'onlineStatusFilter': {'enabled': True, 'matchType': 'IS', 'onlineStatus': 'OFFLINE'},
                    'originFilter': {'enabled': False, 'matchType': 'IS', 'origins': []},
                    'packagenameFilter': {'enabled': False, 'matchType': 'CONTAINS', 'regex': '', 'useRegex': False},
                    'pluginStatusFilter': {'enabled': False, 'matchType': 'IS', 'pluginStatus': 'PREMIUM'},
                    'sourceURLFilter': {'enabled': False, 'matchType': 'CONTAINS', 'regex': '', 'useRegex': False},
                    'testUrl': ''},
                {'conditionFilter':
                     {'conditions': [], 'enabled': False, 'matchType': 'IS_TRUE'}, 'created': 0,
                 'enabled': True,
                 'filenameFilter': {'enabled': True, 'matchType': 'CONTAINS', 'regex': '*.sfv',
                                    'useRegex': False},
                 'filesizeFilter': {'enabled': False, 'from': 0, 'matchType': 'BETWEEN', 'to': 0},
                 'filetypeFilter': {'archivesEnabled': False, 'audioFilesEnabled': False, 'customs': None,
                                    'docFilesEnabled': False, 'enabled': False, 'exeFilesEnabled': False,
                                    'hashEnabled': False, 'imagesEnabled': False, 'matchType': 'IS',
                                    'subFilesEnabled': False, 'useRegex': False, 'videoFilesEnabled': False},
                 'hosterURLFilter': {'enabled': False, 'matchType': 'CONTAINS', 'regex': '', 'useRegex': False},
                 'matchAlwaysFilter': {'enabled': False}, 'name': 'Quasarr_Block_SFV',
                 'onlineStatusFilter': {'enabled': False, 'matchType': 'IS', 'onlineStatus': 'OFFLINE'},
                 'originFilter': {'enabled': False, 'matchType': 'IS', 'origins': []},
                 'packagenameFilter': {'enabled': False, 'matchType': 'CONTAINS', 'regex': '', 'useRegex': False},
                 'pluginStatusFilter': {'enabled': False, 'matchType': 'IS', 'pluginStatus': 'PREMIUM'},
                 'sourceURLFilter': {'enabled': False, 'matchType': 'CONTAINS', 'regex': '', 'useRegex': False},
                 'testUrl': ''}]
        },
    ]

    for setting in settings_to_add:
        namespace = setting["namespace"]
        storage = setting["storage"] or "null"
        name = setting["setting"]
        expected_values = setting["expected_values"]

        added_items = 0
        settings = device.config.get(namespace, storage, name)
        for item in expected_values:
            if item not in settings:
                settings.append(item)
                added_items += 1

        if added_items:
            success = device.config.set(namespace, storage, name, json.dumps(settings))

            location = f"{namespace}/{storage}" if storage != "null" else namespace
            status = "Added" if success else "Failed to add"
            info(f'{status} {added_items} items to "{name}" in "{location}".')


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


def sanitize_string(s):
    s = s.lower()

    # Remove dots / pluses
    s = s.replace('.', ' ')
    s = s.replace('+', ' ')

    # Umlauts
    s = re.sub(r'ä', 'ae', s)
    s = re.sub(r'ö', 'oe', s)
    s = re.sub(r'ü', 'ue', s)
    s = re.sub(r'ß', 'ss', s)

    # Remove special characters
    s = re.sub(r'[^a-zA-Z0-9\s]', '', s)

    # Remove season and episode patterns
    s = re.sub(r'\bs\d{1,3}(e\d{1,3})?\b', '', s)

    # Remove German and English articles
    articles = r'\b(?:der|die|das|ein|eine|einer|eines|einem|einen|the|a|an|and)\b'
    s = re.sub(articles, '', s, re.IGNORECASE)

    # Replace obsolete titles
    s = s.replace('navy cis', 'ncis')

    # Remove extra whitespace
    s = ' '.join(s.split())

    return s


def is_imdb_id(search_string):
    if bool(re.fullmatch(r"tt\d{7,}", search_string)):
        return search_string
    else:
        return None


def search_string_in_sanitized_title(search_string, title):
    sanitized_search_string = sanitize_string(search_string)
    sanitized_title = sanitize_string(title)

    # Use word boundaries to ensure full word/phrase match
    if re.search(rf'\b{re.escape(sanitized_search_string)}\b', sanitized_title):
        debug(f"Matched search string: {sanitized_search_string} with title: {sanitized_title}")
        return True
    else:
        debug(f"Skipping {title} as it doesn't match search string: {sanitized_search_string}")
        return False


def get_recently_searched(shared_state, context, timeout_seconds):
    recently_searched = shared_state.values.get(context, {})
    threshold = datetime.now() - timedelta(seconds=timeout_seconds)
    keys_to_remove = [key for key, value in recently_searched.items() if value["timestamp"] <= threshold]
    for key in keys_to_remove:
        debug(f"Removing '/{key}' from recently searched memory ({context})...")
        del recently_searched[key]
    return recently_searched


def download_package(links, title, password, package_id):
    device = get_device()
    downloaded = device.linkgrabber.add_links(params=[
        {
            "autostart": True,
            "links": json.dumps(links),
            "packageName": title,
            "extractPassword": password,
            "priority": "DEFAULT",
            "downloadPassword": password,
            "destinationFolder": "Quasarr/<jd:packagename>",
            "comment": package_id,
            "overwritePackagizerRules": True
        }
    ])
    return downloaded
