# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import json
import os
import time
from urllib import parse

import quasarr
from quasarr.constants import (
    LINK_PROTECTION_NAMES,
    SHARE_HOSTERS_LOWERCASE,
)
from quasarr.providers.log import debug, error, info, warn
from quasarr.providers.myjd_api import (
    Jddevice,
    Myjdapi,
    MYJDException,
    RequestTimeoutException,
    TokenExpiredException,
)
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
    api_key = os.urandom(32).hex()
    Config("API").save("key", api_key)
    info(f'API Key replaced with: "{api_key}!"')
    return api_key


def extract_valid_hostname(url, shorthand):
    try:
        if "://" not in url:
            url = "http://" + url
        result = parse.urlparse(url)
        domain = result.netloc
        parts = domain.split(".")

        if domain.startswith(".") or domain.endswith(".") or "." not in domain[1:-1]:
            message = f'Error: "{domain}" must contain a "." somewhere in the middle – you need to provide a full domain name!'
            domain = None

        elif any(name in parts for name in LINK_PROTECTION_NAMES):
            offending = next(part for part in parts if part in LINK_PROTECTION_NAMES)
            message = (
                f'Error: "{domain}" is a link protection service ({LINK_PROTECTION_NAMES[offending]}) '
                "and cannot be used as a hostname. Provide the site that links to it instead."
            )
            domain = None

        elif any(hoster in parts for hoster in SHARE_HOSTERS_LOWERCASE):
            offending = next(host for host in parts if host in SHARE_HOSTERS_LOWERCASE)
            message = (
                f'Error: "{domain}" is a file‑hosting domain and cannot be used here directly! '
                f'Instead please provide a valid hostname that serves direct file links (including "{offending}").'
            )
            domain = None

        elif all(char in domain for char in shorthand):
            message = f'"{domain}" contains both characters from shorthand "{shorthand}". Continuing...'

        else:
            message = f'Error: "{domain}" does not contain both characters from shorthand "{shorthand}".'
            domain = None
    except Exception as e:
        message = f"Error: {e}. Please provide a valid URL."
        domain = None

    debug(message)
    return {"domain": domain, "message": message}


def connect_to_jd(jd, user, password, device_name):
    try:
        jd.connect(user, password)
        jd.update_devices()
        device = jd.get_device(device_name)
    except (TokenExpiredException, RequestTimeoutException, MYJDException) as e:
        info("Error connecting to JDownloader: " + str(e).strip())
        return False
    if not device or not isinstance(device, (type, Jddevice)):
        info(
            f'Device "{device_name}" not found. Available devices may differ or be offline.'
        )
        return False
    else:
        device.downloadcontroller.get_current_state()  # request forces direct_connection info update
        connection_info = device.check_direct_connection()
        if connection_info["status"]:
            info(
                f"Direct connection to JDownloader established: <g>{connection_info['ip']}</g>"
            )
        else:
            info("Could not establish direct connection to JDownloader.")
        update("device", device)
        return True


def set_device(user, password, device):
    jd = Myjdapi()
    jd.set_app_key("Quasarr")
    return connect_to_jd(jd, user, password, device)


def set_device_from_config():
    config = Config("JDownloader")
    user = str(config.get("user"))
    password = str(config.get("password"))
    device = str(config.get("device"))

    update("device", device)

    if user and password and device:
        jd = Myjdapi()
        jd.set_app_key("Quasarr")
        return connect_to_jd(jd, user, password, device)
    return False


def check_device(device):
    try:
        if not isinstance(device, (type, Jddevice)):
            return False

        # Trigger a network request to verify connectivity
        # get_current_state() performs an API call to JDownloader
        state = device.downloadcontroller.get_current_state()

        if state:
            return True
        return False
    except Exception:
        return False


def connect_device():
    config = Config("JDownloader")
    user = str(config.get("user"))
    password = str(config.get("password"))
    device = str(config.get("device"))

    jd = Myjdapi()
    jd.set_app_key("Quasarr")

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
        except (
            AttributeError,
            KeyError,
            TokenExpiredException,
            RequestTimeoutException,
            MYJDException,
        ):
            pass
        attempts += 1

        update("device", False)

        # Determine sleep time based on failure count
        if attempts <= 10:
            # First 10 failures: 3 seconds
            sleep_time = 3
            if attempts == 10:
                warn(
                    f"WARNING: {attempts} consecutive JDownloader connection errors. Switching to 1-minute intervals."
                )
        elif attempts <= 15:
            # Next 5 failures (11-15): 1 minute
            sleep_time = 60
            if attempts % 10 == 0:
                warn(
                    f"WARNING: {attempts} consecutive JDownloader connection errors. Please check your credentials!"
                )
            if attempts == 15:
                warn(
                    f"WARNING: Still failing after {attempts} attempts. Switching to 5-minute intervals."
                )
        else:
            # After 15 failures: 5 minutes
            sleep_time = 300
            if attempts % 10 == 0:
                warn(
                    f"WARNING: {attempts} consecutive JDownloader connection errors. Please check your credentials!"
                )

        if connect_device():
            break

        time.sleep(sleep_time)

    return values["device"]


def run_device_request(request_name, request_fn, default=None):
    """
    Execute a JDownloader request with one graceful reconnect+retry on
    auth/timeout errors.

    Args:
        request_name: Human-readable operation label for logs
        request_fn: Callable accepting a connected device
        default: Value returned if both attempts fail
    """
    try:
        return request_fn(get_device())
    except (TokenExpiredException, RequestTimeoutException, MYJDException) as e:
        warn(
            f'JDownloader request "{request_name}" failed ({type(e).__name__}). Retrying once after reconnect...'
        )

    update("device", False)
    if not connect_device():
        error(
            f'JDownloader reconnect failed while handling "{request_name}". Returning fallback result.'
        )
        return default

    try:
        return request_fn(values["device"])
    except (TokenExpiredException, RequestTimeoutException, MYJDException) as e:
        error(
            f'JDownloader request "{request_name}" failed after retry ({type(e).__name__}). Returning fallback result.'
        )
        return default


def get_devices(user, password):
    jd = Myjdapi()
    jd.set_app_key("Quasarr")
    try:
        jd.connect(user, password)
        jd.update_devices()
        devices = jd.list_devices()
        return devices
    except (TokenExpiredException, RequestTimeoutException, MYJDException) as e:
        error("Error connecting to JDownloader: " + str(e))
        return []


def set_device_settings():
    device = get_device()

    settings_to_enforce = [
        {
            "namespace": "org.jdownloader.settings.GeneralSettings",
            "storage": None,
            "setting": "AutoStartDownloadOption",
            "expected_value": "ALWAYS",  # Downloads must start automatically for Quasarr to work
        },
        {
            "namespace": "org.jdownloader.settings.GeneralSettings",
            "storage": None,
            "setting": "IfFileExistsAction",
            "expected_value": "SKIP_FILE",  # Prevents popups during download
        },
        {
            "namespace": "org.jdownloader.settings.GeneralSettings",
            "storage": None,
            "setting": "CleanupAfterDownloadAction",
            "expected_value": "NEVER",  # Links must be kept after download for Quasarr to work
        },
        {
            "namespace": "org.jdownloader.settings.GraphicalUserInterfaceSettings",
            "storage": None,
            "setting": "BannerEnabled",
            "expected_value": False,  # Removes UI clutter in JDownloader
        },
        {
            "namespace": "org.jdownloader.settings.GraphicalUserInterfaceSettings",
            "storage": None,
            "setting": "DonateButtonState",
            "expected_value": "CUSTOM_HIDDEN",  # Removes UI clutter in JDownloader
        },
        {
            "namespace": "org.jdownloader.extensions.extraction.ExtractionConfig",
            "storage": "cfg/org.jdownloader.extensions.extraction.ExtractionExtension",
            "setting": "DeleteArchiveFilesAfterExtractionAction",
            "expected_value": "NULL",  # "NULL" is the ENUM for "Delete files from Harddisk"
        },
        {
            "namespace": "org.jdownloader.extensions.extraction.ExtractionConfig",
            "storage": "cfg/org.jdownloader.extensions.extraction.ExtractionExtension",
            "setting": "IfFileExistsAction",
            "expected_value": "OVERWRITE_FILE",  # Prevents popups during extraction
        },
        {
            "namespace": "org.jdownloader.extensions.extraction.ExtractionConfig",
            "storage": "cfg/org.jdownloader.extensions.extraction.ExtractionExtension",
            "setting": "DeleteArchiveDownloadlinksAfterExtraction",
            "expected_value": False,  # Links must be kept after extraction for Quasarr to work
        },
        {
            "namespace": "org.jdownloader.gui.views.linkgrabber.addlinksdialog.LinkgrabberSettings",
            "storage": None,
            "setting": "OfflinePackageEnabled",
            "expected_value": False,  # Don't move offline links to extra package
        },
        {
            "namespace": "org.jdownloader.gui.views.linkgrabber.addlinksdialog.LinkgrabberSettings",
            "storage": None,
            "setting": "HandleOfflineOnConfirmLatestSelection",
            "expected_value": "INCLUDE_OFFLINE",  # Offline links must always be kept for Quasarr to handle packages
        },
        {
            "namespace": "org.jdownloader.gui.views.linkgrabber.addlinksdialog.LinkgrabberSettings",
            "storage": None,
            "setting": "AutoConfirmManagerHandleOffline",
            "expected_value": "INCLUDE_OFFLINE",  # Offline links must always be kept for Quasarr to handle packages
        },
        {
            "namespace": "org.jdownloader.gui.views.linkgrabber.addlinksdialog.LinkgrabberSettings",
            "storage": None,
            "setting": "DefaultOnAddedOfflineLinksAction",
            "expected_value": "INCLUDE_OFFLINE",  # Offline links must always be kept for Quasarr to handle packages
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
                ".*sample/.*",
                ".*Sample/.*",
                ".*\\.jpe?g",
                ".*\\.idx",
                ".*\\.sub",
                ".*\\.srt",
                ".*\\.nfo",
                ".*\\.bat",
                ".*\\.txt",
                ".*\\.exe",
                ".*\\.sfv",
            ],
        },
        {
            "namespace": "org.jdownloader.controlling.filter.LinkFilterSettings",
            "storage": "null",
            "setting": "FilterList",
            "expected_values": [
                {
                    "conditionFilter": {
                        "conditions": [],
                        "enabled": False,
                        "matchType": "IS_TRUE",
                    },
                    "created": 0,
                    "enabled": True,
                    "filenameFilter": {
                        "enabled": True,
                        "matchType": "CONTAINS",
                        "regex": ".*\\.(sfv|jpe?g|idx|srt|nfo|bat|txt|exe)$",
                        "useRegex": True,
                    },
                    "filesizeFilter": {
                        "enabled": False,
                        "from": 0,
                        "matchType": "BETWEEN",
                        "to": 0,
                    },
                    "filetypeFilter": {
                        "archivesEnabled": False,
                        "audioFilesEnabled": False,
                        "customs": None,
                        "docFilesEnabled": False,
                        "enabled": False,
                        "exeFilesEnabled": False,
                        "hashEnabled": False,
                        "imagesEnabled": False,
                        "matchType": "IS",
                        "subFilesEnabled": False,
                        "useRegex": False,
                        "videoFilesEnabled": False,
                    },
                    "hosterURLFilter": {
                        "enabled": False,
                        "matchType": "CONTAINS",
                        "regex": "",
                        "useRegex": False,
                    },
                    "matchAlwaysFilter": {"enabled": False},
                    "name": "Quasarr_Block_Files",
                    "onlineStatusFilter": {
                        "enabled": False,
                        "matchType": "IS",
                        "onlineStatus": "OFFLINE",
                    },
                    "originFilter": {
                        "enabled": False,
                        "matchType": "IS",
                        "origins": [],
                    },
                    "packagenameFilter": {
                        "enabled": False,
                        "matchType": "CONTAINS",
                        "regex": "",
                        "useRegex": False,
                    },
                    "pluginStatusFilter": {
                        "enabled": False,
                        "matchType": "IS",
                        "pluginStatus": "PREMIUM",
                    },
                    "sourceURLFilter": {
                        "enabled": False,
                        "matchType": "CONTAINS",
                        "regex": "",
                        "useRegex": False,
                    },
                    "testUrl": "",
                }
            ],
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


def update_jdownloader():
    try:
        if not get_device():
            set_device_from_config()
        device = get_device()

        if device:
            try:
                current_state = device.downloadcontroller.get_current_state()
                is_collecting = device.linkgrabber.is_collecting()
                update_available = device.update.update_available()

                if (current_state.lower() == "idle") and (
                    not is_collecting and update_available
                ):
                    info("JDownloader update ready. Starting update...")
                    device.update.restart_and_update()
            except quasarr.providers.myjd_api.TokenExpiredException:
                return False
            return True
        else:
            return False
    except quasarr.providers.myjd_api.MYJDException as e:
        info(f"Error updating JDownloader: {e}")
        return False


def start_downloads():
    try:
        if not get_device():
            set_device_from_config()
        device = get_device()

        if device:
            try:
                return device.downloadcontroller.start_downloads()
            except quasarr.providers.myjd_api.TokenExpiredException:
                return False
        else:
            return False
    except quasarr.providers.myjd_api.MYJDException as e:
        info(f"Error starting Downloads: {e}")
        return False


def get_db(table):
    return DataBase(table)
