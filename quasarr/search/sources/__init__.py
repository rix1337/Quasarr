# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import importlib
import inspect
import pkgutil

from quasarr.providers.log import error, warn
from quasarr.search.sources.helpers.search_source import AbstractSearchSource

_sources = {}
_source_module_names = []


def get_source_module_names() -> list[str]:
    global _source_module_names

    if _source_module_names:
        return _source_module_names

    discovered = []
    for _, module_name, _ in pkgutil.iter_modules(__path__):
        if module_name in ("helpers", "templates") or module_name.startswith("_"):
            continue
        discovered.append(module_name)

    _source_module_names = sorted(discovered)
    return _source_module_names


def get_sources() -> dict[str, AbstractSearchSource]:
    from quasarr.search.sources.templates import get_templates

    templates = get_templates()
    if not _sources:
        for module_name in get_source_module_names():
            if module_name in templates:
                continue
            try:
                mod = importlib.import_module(f"{__name__}.{module_name}")
            except Exception as e:
                error(f"Error importing {module_name.upper()}: {e}")
                continue

            if hasattr(mod, "Source"):
                if inspect.isclass(mod.Source) and issubclass(
                    mod.Source, AbstractSearchSource
                ):
                    try:
                        _sources[module_name] = mod.Source()
                    except Exception as e:
                        error(f"Error instantiating {module_name.upper()}: {e}")
                else:
                    error(
                        f"Source '{module_name.upper()}.Source' does not implement AbstractSearchSource"
                    )
            else:
                warn(f"Source '{module_name.upper()}' does not expose a Source class")
    from quasarr.storage.custom_sources import get_custom_sources

    return {**_sources, **templates, **get_custom_sources()}
