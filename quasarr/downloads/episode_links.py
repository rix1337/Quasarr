# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

"""Trim a single-episode package down to the episode that was requested.

Grabbing one episode can still hand Quasarr the links of a whole season.
Crypter containers are season wide; Filecrypt only narrows them down when the
decrypting side asks for it explicitly (`get_filecrypt_links` does, via the
season/episode parameters it derives from the release title). Paths that read
a container as a whole - most notably the userscript flow - return every
episode. JDownloader then holds a full season under a package whose name names
exactly one episode, and the *arr client imports one file while the rest is
downloaded for nothing.

Link URLs carry no file names, so the mismatch is invisible until JDownloader
has collected the package. That makes the linkgrabber the earliest - and only -
place where it can be corrected.

The package name is authoritative: `download_package` sets it to the release
title and passes `overwritePackagizerRules`, so JDownloader cannot rename it.

Safety first: whenever the links cannot be mapped to episodes unambiguously,
the package is left untouched. Downloading too much is wasteful; downloading
too little breaks the import.
"""

import re

from quasarr.providers.log import info

# Season/episode token in release titles and archive file names, e.g.
# "Pack.S01.German..." (no episode part) or "pack.s01e05.german...part03.rar".
# Ranges like "S01E01-E03" are captured whole and expanded by the parser.
_SEASON_TOKEN = re.compile(
    r"(?<![a-z0-9])S(?P<season>\d{1,4})(?P<episodes>(?:E\d{1,4})+(?:-E?\d{1,4})?)?(?![a-z0-9])",
    re.IGNORECASE,
)


def parse_season_episodes(name):
    """Parse the first season/episode token from a title or file name.

    Returns ``(season, episode_numbers)`` where ``episode_numbers`` is a set
    (empty for a season pack without an episode component), or ``None`` when
    the name carries no season token at all.
    """
    match = _SEASON_TOKEN.search(name or "")
    if not match:
        return None
    season = int(match.group("season"))
    episode_part = match.group("episodes") or ""
    numbers = [int(n) for n in re.findall(r"\d{1,4}", episode_part)]
    if not numbers:
        return season, set()
    if (
        "-" in episode_part
        and len(numbers) == 2
        and numbers[0] < numbers[1]
        and numbers[1] - numbers[0] <= 100
    ):
        return season, set(range(numbers[0], numbers[1] + 1))
    return season, set(numbers)


def plan_link_removals(package_name, links):
    """Split links into (keep_ids, remove_ids), or None to keep the package as is.

    ``links`` are linkgrabber link dicts carrying ``uuid`` and ``name``.
    Returns ``None`` - keep everything - when the package name names no single
    episode (a season pack was requested), when any link cannot be mapped to an
    episode of that season, or when filtering would remove nothing or keep
    nothing.
    """
    parsed_package = parse_season_episodes(package_name)
    if not parsed_package:
        return None
    season, requested = parsed_package
    if not requested:
        return None  # season pack: every episode belongs to this grab

    keep, remove = [], []
    for link in links:
        uuid = link.get("uuid")
        if uuid is None:
            return None
        parsed_link = parse_season_episodes(link.get("name") or "")
        if not parsed_link or not parsed_link[1] or parsed_link[0] != season:
            return None  # unmapped link -> never risk an incomplete download
        if parsed_link[1] & requested:
            keep.append(uuid)
        else:
            remove.append(uuid)

    if not keep or not remove:
        return None
    return keep, remove


def trim_to_requested_episodes(shared_state, package_name, package_links):
    """Remove links of other episodes from a single-episode package.

    Returns True when links were removed, so the caller can postpone the start
    until JDownloader's state has settled. Once trimmed, a later pass finds
    nothing to remove and the package starts normally.
    """
    plan = plan_link_removals(package_name, package_links)
    if plan is None:
        return False

    keep, remove = plan
    try:
        # package_ids must stay empty: passing the package id would remove the
        # whole package instead of only the filtered links.
        shared_state.get_device().linkgrabber.remove_links(remove, [])
    except Exception as e:
        info(f"Could not trim '{package_name}' to the requested episode: {e}")
        return False

    info(
        f"Removed <g>{len(remove)}</g> link(s) belonging to other episodes from "
        f"'{package_name}', keeping <g>{len(keep)}</g>"
    )
    return True
