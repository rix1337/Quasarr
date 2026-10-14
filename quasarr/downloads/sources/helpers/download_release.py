# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

from typing import TypedDict


class DownloadRelease(TypedDict, total=False):
    """
    Normalized result shape returned by download sources.

    - `links`: list of [url, mirror] or [url, mirror, state_url]
    - `title` / `password` / `imdb_id`: optional source overrides
    - `protected`: source page requires manual decryption
    - `terminal` / `error`: final failure persisted without trying another source
    """

    links: list[list[str]]
    title: str
    password: str
    imdb_id: str
    protected: bool
    terminal: bool
    error: str
