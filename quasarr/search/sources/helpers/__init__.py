import importlib.util
import pkgutil


def get_hostnames():
    spec = importlib.util.find_spec("quasarr.search.sources")
    if not spec or not spec.submodule_search_locations:
        return []

    hostnames = []
    for _, module_name, _ in pkgutil.iter_modules(spec.submodule_search_locations):
        if module_name == "helpers" or module_name.startswith("_"):
            continue
        hostnames.append(module_name)

    return sorted(hostnames)


def get_login_required_hostnames():
    from quasarr.search.sources import get_sources

    return [
        source.initials for source in get_sources().values() if source.requires_login
    ]


def get_radarr_required_hostnames():
    from quasarr.search.sources import get_sources

    return [
        source.initials
        for source in get_sources().values()
        if source.feed_requires_radarr
    ]


def get_sonarr_required_hostnames():
    from quasarr.search.sources import get_sources

    return [
        source.initials
        for source in get_sources().values()
        if source.feed_requires_sonarr
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
            "feed_requires_radarr": bool(source.feed_requires_radarr),
            "feed_requires_sonarr": bool(source.feed_requires_sonarr),
        }
    return metadata
