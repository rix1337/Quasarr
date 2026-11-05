# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

"""Bundled site templates: one module per two-letter source key.

Each module exposes ``TEMPLATE``, a definition in the same format users write
for their own sites, minus the hostname, which comes from the hostname
settings. Steps that selectors cannot express name a hook in
``TEMPLATE["hooks"]``: a function of the same module, or for a template
package the module beside it (``search`` or ``download``) whose ``Source``
runs that step. That code reads the site's addresses from ``TEMPLATE["urls"]``. Users may change the data parts of a template; their
changes are stored apart and laid over the shipped template, so removing them
restores it.
"""

import copy
import importlib
import inspect
import pkgutil

from quasarr.providers.log import error

_shipped = {}
_state = {"revision": None, "templates": {}, "modified": set()}


def get_template_keys():
    return sorted(
        name
        for _, name, _ in pkgutil.iter_modules(__path__)
        if not name.startswith("_")
    )


def shipped_definition(key):
    module = importlib.import_module(f"{__name__}.{key}")
    return {**copy.deepcopy(module.TEMPLATE), "key": key}


def build_template(key, changes=None):
    """The template of one site, with the user's changes laid over it."""
    from quasarr.search.sources.helpers.custom_source import CustomSource

    module = importlib.import_module(f"{__name__}.{key}")
    definition = shipped_definition(key)
    definition.update(copy.deepcopy(changes or {}))
    hooks = {
        point: _hook(module, point, name)
        for point, name in (definition.get("hooks") or {}).items()
    }
    return CustomSource(definition, bundled=True, hooks=hooks)


def _hook(module, point, name):
    """A function of the template module, or a step of the site code beside it."""
    target = getattr(module, name, None)
    if callable(target):
        return target
    source = importlib.import_module(f"{module.__name__}.{name}").Source
    if point == "feed":
        return lambda site, *args: source().feed(*args)
    if point == "download":
        return lambda site, *args: source().get_download_links(*args)
    if point == "package_identity":
        return lambda site, url: source().get_package_identity(url)
    # only searches that understand date-numbered episodes are told the date
    takes_date = "episode_date" in inspect.signature(source.search).parameters

    def search(site, *args, episode_date=None):
        extra = {"episode_date": episode_date} if takes_date else {}
        return source().search(*args, **extra)

    return search


def _load(key):
    return build_template(key)


def get_templates():
    """Compiled bundled templates keyed by source key, with the user's changes."""
    from quasarr.storage.custom_sources import current_revision
    from quasarr.storage.template_overrides import load_overrides

    if not _shipped:
        for key in get_template_keys():
            try:
                _shipped[key] = _load(key)
            except Exception as e:
                error(f"Bundled template {key.upper()} is invalid: {e}")
    revision = current_revision()
    if _state["revision"] != revision or not _state["templates"]:
        templates = dict(_shipped)
        modified = set()
        try:
            overrides = load_overrides()
        except Exception as e:
            error(f"Could not load changes to built-in sites: {e}")
            overrides = {}
        for key, changes in overrides.items():
            if key not in _shipped:
                continue
            try:
                templates[key] = build_template(key, changes)
                modified.add(key)
            except Exception as e:
                error(
                    f"Your changes to {key.upper()} are invalid, using the shipped one: {e}"
                )
        _state.update(revision=revision, templates=templates, modified=modified)
    return _state["templates"]


def is_modified(key):
    """Whether the user changed this built-in site."""
    get_templates()
    return str(key).lower() in _state["modified"]


def site_url(shared_state, key, name, **values):
    """A named address of a built-in site, as its template states it now."""
    host = shared_state.values["config"]("Hostnames").get(key)
    return get_templates()[key].url(name, host=host, **values)
