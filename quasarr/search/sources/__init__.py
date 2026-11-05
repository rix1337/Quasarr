# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

from quasarr.search.sources.helpers.search_source import AbstractSearchSource


def get_sources() -> dict[str, AbstractSearchSource]:
    """Bundled site templates and the user's own sources, by source key."""
    from quasarr.search.sources.templates import get_templates
    from quasarr.storage.custom_sources import get_custom_sources

    return {**get_templates(), **get_custom_sources()}
