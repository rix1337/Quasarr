# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

TEMPLATE = {
    "name": "MB",
    "language": "de",
    "feeds": [
        {"category": 2000, "url": "https://{host}/category/neuerscheinungen/"},
        {"category": 5000, "url": "https://{host}/category/serie/"},
    ],
    "search": {
        "mode": "imdb",
        "url": "https://{host}/?s={q}&id=20&post_type=post",
        "categories": [2000, 5000],
        "filters": ["skip_xxx", "require_quality", "no_spaces"],
        "imdb_identity": False,
    },
    "list": {
        "item": "div.post",
        "title": {"selector": "h1 a"},
        "link": {"selector": "h1 a", "attr": "href"},
        "size": {"label": ["Größe", "Size"]},
        "date": {"selector": "p.date_x"},
        "title_cleanup": "none",
        "dedupe": False,
        "date_fallback": "hour_ago",
    },
    "download": {
        "links": {
            "selector": 'a[href*="filecrypt." i][href*="/Container/" i]',
            "mirror": "text",
        },
        "password": "hostname",
        "filter_mirrors": True,
    },
}
