# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

"""Changes users make to built-in sites, stored apart from the shipped templates.

Each row holds the changed parts of one template. The template loader lays them
over the shipped definition, so deleting a row restores the shipped site. A
write stamps the same revision as custom sources, so every process reloads.
"""

import json

from quasarr.providers import shared_state
from quasarr.providers.log import error
from quasarr.storage.custom_sources import bump_revision

TABLE = "template_overrides"
# what a user may change on a built-in site; name, language, capabilities and
# the code hooks always come from the shipped template
EDITABLE_PARTS = (
    "flaresolverr",
    "urls",
    "feeds",
    "feed_validate",
    "magazine_titles",
    "search",
    "list",
    "search_list",
    "download",
)


def _override_db():
    from quasarr.storage.sqlite_database import DataBase

    return DataBase(TABLE)


def load_overrides():
    """Changed parts of built-in sites, keyed by source key."""
    overrides = {}
    if "dbfile" not in shared_state.values:
        return overrides
    for key, value in _override_db().retrieve_all_titles() or []:
        try:
            overrides[key] = json.loads(value)
        except Exception as e:
            error(f"Could not read the changes to {key.upper()}: {e}")
    return overrides


def save_override(key, changes):
    """Validate and store changed parts of a built-in site."""
    from quasarr.search.sources import templates

    key = str(key).lower()
    if key not in templates.get_template_keys():
        raise ValueError("Unknown built-in site")
    if not isinstance(changes, dict):
        raise ValueError("The changes must be an object")
    unknown = sorted(set(changes) - set(EDITABLE_PARTS))
    if unknown:
        raise ValueError(
            f"{', '.join(unknown)} cannot be changed; editable are "
            + ", ".join(EDITABLE_PARTS)
        )
    templates.build_template(key, changes)
    _override_db().update_store(key, json.dumps(changes))
    bump_revision()


def delete_override(key):
    key = str(key).lower()
    db = _override_db()
    if db.retrieve(key) is None:
        return False
    db.delete(key)
    bump_revision()
    return True
