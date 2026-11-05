# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

from quasarr.downloads.sources.helpers.abstract_source import AbstractDownloadSource


def get_sources() -> dict[str, AbstractDownloadSource]:
    """Every source serves its own downloads: templates and the user's sources."""
    from quasarr.search.sources.templates import get_templates
    from quasarr.storage.custom_sources import get_custom_sources

    return {**get_templates(), **get_custom_sources()}
