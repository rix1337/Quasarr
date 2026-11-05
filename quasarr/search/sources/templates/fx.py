# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

# A post lists several releases, each one a crypter link with its own size.
SIZE_LABELS = ["Size", "Größe"]


def _release_list(item, **extra):
    return {
        "item": item,
        "title": {},
        "link": {"attr": "href"},
        "imdb": [
            {"within": "td", "selector": 'a[href*="imdb.com"]', "attr": "href"},
            {"within": "article", "selector": 'a[href*="imdb.com"]', "attr": "href"},
        ],
        "size": [
            {"within": "td", "label": SIZE_LABELS, "required": True},
            {"within": "article", "label": SIZE_LABELS, "required": True},
        ],
        "date": {
            "within": "article",
            "selector": "time[datetime]",
            "attr": "datetime",
            "pick": "last",
        },
        "title_cleanup": "sanitize",
        "dedupe": False,
        **extra,
    }


TEMPLATE = {
    "name": "FX",
    "language": "de",
    # the front page carries movies and series alike
    "feeds": [
        {"category": 2000, "url": "https://{host}/"},
        {"category": 5000, "url": "https://{host}/"},
    ],
    "list": _release_list(
        'article a[href*="filecrypt."], article a[href*="safe."]',
        source={"within": "article", "selector": "h2.entry-title a", "attr": "href"},
    ),
    "search": {
        "mode": "imdb",
        "url": "https://{host}/?s={q}",
        "categories": [2000, 5000],
        "imdb_identity": "strict_fill",
        # the search page links the post; the releases are on the post itself
        "follow": {"selector": "h2.entry-title a", "limit": 1},
    },
    "search_list": _release_list('article a[href*="filecrypt."]', source_is_page=True),
    "download": {"password": "site_name"},
}
