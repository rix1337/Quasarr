# -*- coding: utf-8 -*-

import re
from urllib.parse import urlparse

from quasarr.constants import (
    MIRROR_TOKEN_ALIASES,
    SHARE_HOSTERS_LOWERCASE,
)

_MULTI_LABEL_SUFFIX_PREFIXES = frozenset(
    {"ac", "co", "com", "edu", "gov", "net", "org"}
)
_TOKEN_CLEAN_RE = re.compile(r"[^a-z0-9]+")


def _clean_token(value):
    return _TOKEN_CLEAN_RE.sub("", str(value or "").lower())


_CANONICAL_MIRROR_TOKENS = {_clean_token(hoster) for hoster in SHARE_HOSTERS_LOWERCASE}
_MIRROR_TOKEN_MAP = {
    _clean_token(alias): _clean_token(canonical)
    for alias, canonical in MIRROR_TOKEN_ALIASES.items()
}
for canonical_token in _CANONICAL_MIRROR_TOKENS:
    _MIRROR_TOKEN_MAP[canonical_token] = canonical_token


def normalize_mirror_token(value):
    """
    Normalize a mirror name, hostname, or URL to the canonical hoster token.

    Matching intentionally ignores TLDs and subdomains and focuses on the
    provider/root label of the final HTTP hostname.
    """
    host_or_name = _extract_host_or_name(value)
    if not host_or_name:
        return ""

    if "." in host_or_name:
        return _normalize_root_token(_extract_domain_root_token(host_or_name))

    return _normalize_root_token(host_or_name)


def mirror_priority_rank(value, mirrors):
    """Position of a mirror name, hostname, or URL in the ordered category mirrors."""
    token = normalize_mirror_token(value)
    ranked = [normalize_mirror_token(mirror) for mirror in (mirrors or [])]
    return ranked.index(token) if token and token in ranked else len(ranked)


def link_priority_rank(link, mirrors):
    """Rank a [url, mirror] link by its mirror label, its URL, or a label naming the mirror."""
    if isinstance(link, (list, tuple)):
        values = [value for value in link[:2] if value]
    else:
        values = [link]
    ranks = [mirror_priority_rank(value, mirrors) for value in values]
    for index, mirror in enumerate(mirrors or []):
        wanted = _clean_token(mirror)
        if wanted and any(wanted in _clean_token(value) for value in values):
            ranks.append(index)
    return min(ranks, default=len(mirrors or []))


def is_known_mirror(value):
    """Whether a mirror name, hostname, or URL names a known hoster."""
    return normalize_mirror_token(value) in _CANONICAL_MIRROR_TOKENS


def mirror_allowed(link, mirrors):
    """Whitelist check for a source link before decryption.

    A label or URL that names no known hoster, as a generic "filecrypt"
    container, is kept: its hoster is only known after decryption, where the
    final check applies the whitelist.
    """
    if not mirrors or link_priority_rank(link, mirrors) < len(mirrors):
        return True
    values = link[:2] if isinstance(link, (list, tuple)) else [link]
    return not any(is_known_mirror(value) for value in values if value)


def filter_final_download_urls(urls, mirrors):
    """Keep links of whitelisted mirrors, ordered by the category's mirror priority."""
    allowed_tokens = {
        normalize_mirror_token(mirror) for mirror in (mirrors or []) if mirror
    }
    allowed_tokens.discard("")

    normalized_urls = [str(url) for url in (urls or []) if url]
    if not allowed_tokens:
        return {
            "urls": normalized_urls,
            "allowed_tokens": allowed_tokens,
            "dropped": [],
            "kept_tokens": {
                normalize_mirror_token(url) for url in normalized_urls if url
            },
        }

    kept_urls = []
    dropped = []
    kept_tokens = set()

    for url in normalized_urls:
        token = normalize_mirror_token(url)
        if token and token in allowed_tokens:
            kept_urls.append(url)
            kept_tokens.add(token)
            continue
        dropped.append({"url": url, "token": token or "unknown"})

    # Every whitelisted mirror is kept for redundancy, highest priority first.
    kept_urls.sort(key=lambda url: mirror_priority_rank(url, mirrors))

    return {
        "urls": kept_urls,
        "allowed_tokens": allowed_tokens,
        "dropped": dropped,
        "kept_tokens": kept_tokens,
    }


def _extract_host_or_name(value):
    raw = str(value or "").strip().lower()
    if not raw:
        return ""

    if "://" in raw or raw.startswith("//"):
        parsed = urlparse(raw if "://" in raw else f"https:{raw}")
        return (parsed.hostname or "").lower().strip(".")

    raw = raw.split("/", 1)[0]
    raw = raw.rsplit("@", 1)[-1]
    raw = raw.split(":", 1)[0]
    return raw.lower().strip(".")


def _extract_domain_root_token(hostname):
    labels = [label for label in hostname.split(".") if label]
    if not labels:
        return ""
    if len(labels) == 1:
        return labels[0]
    if (
        len(labels) >= 3
        and len(labels[-1]) == 2
        and _clean_token(labels[-2]) in _MULTI_LABEL_SUFFIX_PREFIXES
    ):
        return labels[-3]
    return labels[-2]


def _normalize_root_token(token):
    cleaned = _clean_token(token)
    if not cleaned:
        return ""
    return _MIRROR_TOKEN_MAP.get(cleaned, cleaned)
