# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

"""Bundled site templates: one module per two-letter source key.

Each module exposes ``TEMPLATE``, a definition in the same format users write
for their own sites, minus the hostname, which comes from the hostname
settings. Steps that selectors cannot express name a function of the same
module in ``TEMPLATE["hooks"]``. Templates are read-only; users copy one into a
custom source to change it.
"""

import copy
import importlib
import pkgutil

from quasarr.providers.log import error

_templates = {}


def get_template_keys():
    return sorted(
        name
        for _, name, _ in pkgutil.iter_modules(__path__)
        if not name.startswith("_")
    )


def _load(key):
    from quasarr.search.sources.helpers.custom_source import CustomSource

    module = importlib.import_module(f"{__name__}.{key}")
    definition = {**module.TEMPLATE, "key": key}
    hooks = {
        point: getattr(module, name)
        for point, name in (definition.get("hooks") or {}).items()
        if callable(getattr(module, name, None))
    }
    return CustomSource(definition, bundled=True, hooks=hooks)


def get_templates():
    """Compiled bundled templates keyed by source key."""
    if not _templates:
        for key in get_template_keys():
            try:
                _templates[key] = _load(key)
            except Exception as e:
                error(f"Bundled template {key.upper()} is invalid: {e}")
    return _templates


def get_template_definitions():
    """Read-only copies of the bundled definitions, to start a custom source."""
    return {
        key: copy.deepcopy(source.definition) for key, source in get_templates().items()
    }
