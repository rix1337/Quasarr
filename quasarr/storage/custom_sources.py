# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

"""Encrypted storage for user-defined sources, cached per process.

Each definition is one row in the ``custom_sources`` table. A write stores the
row and stamps ``custom_sources_rev`` in the shared state; every process keeps
its compiled sources and reloads them from the database only when that stamp
changes, so searches never touch the database.
"""

import json
import threading
import time

from quasarr.providers import shared_state
from quasarr.providers.hostname_issues import mark_hostname_issue
from quasarr.providers.log import error

TABLE = "custom_sources"
REVISION_KEY = "custom_sources_rev"
_NEXT_INDEX_KEY = "__next_index__"
_KEY_LETTERS = "cdefghijklmnopqrstuvwxyz"
SCHEMA_VERSION = 1

_cache_lock = threading.Lock()
_cache = {"revision": None, "sources": {}}


def _db():
    from quasarr.storage.sqlite_database import DataBase

    return DataBase(TABLE)


def _current_revision():
    try:
        return shared_state.values.get(REVISION_KEY) or 0
    except Exception:
        return 0


def _bump_revision():
    revision = time.time_ns()
    if shared_state.lock is None:
        shared_state.values[REVISION_KEY] = revision
    else:
        shared_state.update(REVISION_KEY, revision)


def _key_for_index(index):
    letter, digit = divmod(index, 9)
    if letter >= len(_KEY_LETTERS):
        raise ValueError("No custom source keys left")
    return f"{_KEY_LETTERS[letter]}{digit + 1}"


def _read_rows():
    from quasarr.storage.config import decrypt_secret

    definitions = {}
    for key, value in _db().retrieve_all_titles() or []:
        if key == _NEXT_INDEX_KEY:
            continue
        try:
            definitions[key] = json.loads(decrypt_secret(value))
        except Exception as e:
            # The row stays untouched so restoring the matching key recovers it.
            error(f"Could not read custom source {key.upper()}: {e}")
            mark_hostname_issue(key, "load", f"Stored definition unreadable: {e}")
    return definitions


def load_definitions():
    """Return every readable stored definition keyed by source key."""
    return _read_rows()


def get_custom_sources():
    """Compiled custom sources, reloaded only after another process saved."""
    from quasarr.search.sources.helpers.custom_source import CustomSource

    if "dbfile" not in shared_state.values:
        return {}
    revision = _current_revision()
    with _cache_lock:
        if _cache["revision"] == revision:
            return _cache["sources"]
        sources = {}
        try:
            definitions = _read_rows()
        except Exception as e:
            error(f"Could not load custom sources: {e}")
            return _cache["sources"]
        for key, definition in definitions.items():
            if not definition.get("enabled", True):
                continue
            try:
                sources[key] = CustomSource(definition)
            except Exception as e:
                error(f"Custom source {key.upper()} is invalid: {e}")
                mark_hostname_issue(key, "load", f"Stored definition invalid: {e}")
        _cache["revision"] = revision
        _cache["sources"] = sources
        return sources


def save_definition(definition):
    """Validate, encrypt and store a definition; assigns a key to new ones."""
    from quasarr.search.sources.helpers.custom_source import compile_definition
    from quasarr.storage.config import encrypt_secret

    definition = dict(definition)
    db = _db()
    if not definition.get("key"):
        index = int(db.retrieve(_NEXT_INDEX_KEY) or 0)
        definition["key"] = _key_for_index(index)
        # Keys are never reused: grabbed payloads carry them.
        db.update_store(_NEXT_INDEX_KEY, str(index + 1))
    elif db.retrieve(str(definition["key"]).lower()) is None:
        raise ValueError(f"Unknown custom source {definition['key']}")

    definition["key"] = str(definition["key"]).lower()
    definition["schema"] = SCHEMA_VERSION
    definition.setdefault("enabled", True)
    compile_definition(definition)
    db.update_store(definition["key"], encrypt_secret(json.dumps(definition)))
    _bump_revision()
    return definition


def delete_definition(key):
    key = str(key).lower()
    db = _db()
    if key == _NEXT_INDEX_KEY or db.retrieve(key) is None:
        return False
    db.delete(key)
    _bump_revision()
    return True
