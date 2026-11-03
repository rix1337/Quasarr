# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

from bottle import request, response

from quasarr.constants import CRYPTER_ENABLED_TABLE, LINK_PROTECTION_NAMES
from quasarr.providers.log import info
from quasarr.storage.sqlite_database import DataBase


def _coerce_bool(value, default=False):
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
    return bool(value)


def _read_crypters_enabled():
    crypter_db = DataBase(CRYPTER_ENABLED_TABLE)
    return {
        key: _coerce_bool(crypter_db.retrieve(key), default=True)
        for key in LINK_PROTECTION_NAMES
    }


def refresh_crypter_settings(shared_state):
    value = _read_crypters_enabled()
    shared_state.update("crypters_enabled", value)
    return value


def initialize_crypter_settings(shared_state):
    return refresh_crypter_settings(shared_state)


def get_crypter_settings_data(shared_state):
    response.content_type = "application/json"
    return {"success": True, "enabled": refresh_crypter_settings(shared_state)}


def save_crypter_settings(shared_state):
    response.content_type = "application/json"

    data = request.json
    if not isinstance(data, dict) or not isinstance(data.get("enabled"), dict):
        return {"success": False, "message": "Invalid JSON payload"}

    crypter_db = DataBase(CRYPTER_ENABLED_TABLE)
    current = _read_crypters_enabled()
    for key in LINK_PROTECTION_NAMES:
        next_value = _coerce_bool(data["enabled"].get(key), current[key])
        crypter_db.update_store(key, "true" if next_value else "false")

    value = refresh_crypter_settings(shared_state)
    disabled = [LINK_PROTECTION_NAMES[key] for key, on in value.items() if not on]
    if disabled:
        info(f"Crypters turned off: <r>{', '.join(disabled)}</r>")
    else:
        info("All crypters are on")

    return {"success": True, "message": "Saved", "enabled": value}
