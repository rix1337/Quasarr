# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

SECTIONS = {7000: "ebooks", 2000: "movies", 5000: "tv-shows", 3000: "music"}

TEMPLATE = {
    "name": "SL",
    "language": "en",
    "categories": [7000, 2000, 5000, 5070, 3000],
    "capabilities": {
        "requires_flaresolverr": True,
        "supports_date_numbering": True,
        "supports_phrase": True,
    },
    "magazine_titles": True,
    "feeds": [
        {"category": category, "url": f"https://{{host}}/{section}/feed/"}
        for category, section in SECTIONS.items()
    ],
    # the feed is RSS: every item carries its size and IMDb link in the text
    "list": {
        "item": "item",
        "title": {"selector": "title"},
        "link": {"selector": "permalink", "attr": "text"},
        "size": {"selector": "description", "label": "Size", "required": True},
        "date": {"selector": "pubdate", "required": True},
        "imdb": {"selector": "description"},
        "title_cleanup": "none",
        "dedupe": False,
    },
    "search": {
        "mode": "title",
        "phrase": True,
        "match": "query",
        "imdb_identity": "fill",
        "categories": list(SECTIONS),
        # series also live in the foreign section
        "urls": {
            category: [f"https://{{host}}/{section}/?s={{q}}"]
            + (["https://{host}/foreign/?s={q}"] if section == "tv-shows" else [])
            for category, section in SECTIONS.items()
        },
    },
    "search_list": {
        "item": "li.row",
        "title": {"selector": "span.title-start"},
        "link": {"selector": "div.title a", "attr": "href"},
        "size": {"selector": "span.m.size"},
        "date": {"selector": "span.date-short span.localtime", "attr": "data-lttime"},
        "title_cleanup": "none",
        "find_imdb": False,
    },
    "download": {
        "section": {"heading": "h2", "contains": "download"},
        "links": {"mirror": "host_label"},
        "hosts": ["nitroflare", "ddownload"],
        "filter_mirrors": "url",
        "text_urls": True,
        "imdb": True,
        "empty_is_issue": False,
        "password": "hostname",
    },
}
