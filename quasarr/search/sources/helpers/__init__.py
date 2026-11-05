def get_hostnames():
    """Source keys with a hostname setting: one per bundled template."""
    from quasarr.search.sources.templates import get_template_keys

    return get_template_keys()


def get_login_required_hostnames():
    from quasarr.search.sources import get_sources

    return [
        source.initials for source in get_sources().values() if source.requires_login
    ]


def get_radarr_required_hostnames():
    from quasarr.search.sources import get_sources

    return [
        source.initials for source in get_sources().values() if source.requires_radarr
    ]


def get_sonarr_required_hostnames():
    from quasarr.search.sources import get_sources

    return [
        source.initials for source in get_sources().values() if source.requires_sonarr
    ]


def get_source_metadata():
    """Per-source capability metadata for the hostname editor UI.

    Keyed by lowercase initials; values expose the language and capability
    flags the editor renders as flags/chips. Categories come straight from each
    source's declared ``supported_categories``.
    """
    from quasarr.search.sources import get_sources

    metadata = {}
    for key, source in get_sources().items():
        metadata[key] = {
            "language": source.language,
            "categories": list(source.supported_categories),
            "supports_imdb": bool(source.supports_imdb),
            "requires_login": bool(source.requires_login),
            "requires_account": bool(getattr(source, "requires_account", False)),
            "invite_only": bool(getattr(source, "invite_only", False)),
            "requires_flaresolverr": bool(source.requires_flaresolverr),
            "requires_radarr": bool(source.requires_radarr),
            "requires_sonarr": bool(source.requires_sonarr),
        }
    return metadata
