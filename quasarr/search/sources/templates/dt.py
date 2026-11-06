# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

FEEDS = {
    7000: "learning/",
    2000: "media/videos/",
    5000: "media/tv-show/",
    3000: "media/music/",
}
# DLE category ids searched per Quasarr category
SEARCH_CATEGORIES = {
    7000: ["100", "4", "35", "109"],
    2000: ["9", "107", "106", "104"],
    5000: ["64"],
    3000: ["66"],
}
SEARCH_URL = (
    "https://{host}/index.php?do=search&subaction=search&search_start=0&full_search=1"
    "&story={q}&CATLIST&sortby=date&resorder=desc&titleonly=3&searchuser="
    "&beforeafter=after&searchdate=0&replyless=0&replylimit=0&showposts=0"
)


def _articles(title_selector):
    return {
        "item": "article",
        "title": {"selector": title_selector},
        "link": {"selector": title_selector, "attr": "href"},
        "imdb": {"attr": "html"},
        "size": {"selector": "div.dt-text-clamp", "required": True},
        # the site shows CET without saying so: a calendar block of month,
        # day, year and clock in search results, "d.m.Y H:i" in the feed
        "date": [
            {
                "parts": [
                    "small.dt-fs-11",
                    "h4.m-0",
                    "h6.m-0",
                    "span:has(> i.bi-clock)",
                ],
                "utc_offset": 1,
                "required": True,
            },
            {"utc_offset": 1, "require_time": True, "required": True},
        ],
        "title_cleanup": "dots",
        "dedupe": False,
    }


TEMPLATE = {
    "name": "DT",
    "language": "en",
    "magazine_titles": True,
    "feeds": [
        {"category": category, "url": f"https://{{host}}/{path}"}
        for category, path in FEEDS.items()
    ],
    "list": _articles(".dt-flexible-title a"),
    "search": {
        "mode": "title",
        "phrase": True,
        "match": "query",
        "imdb_identity": "none",
        "categories": list(SEARCH_CATEGORIES),
        "urls": {
            category: [
                SEARCH_URL.replace(
                    "CATLIST", "&".join(f"catlist%5B%5D={cid}" for cid in ids)
                )
            ]
            for category, ids in SEARCH_CATEGORIES.items()
        },
    },
    "search_list": _articles("h1.font-weight-bold a"),
    "download": {
        "container": "div.full-story-body",
        "links": {"mirror": "domain"},
        "filter": "all",
        "exclude": ["imdb.com", "?ref="],
        "filter_mirrors": "url",
        "text_urls": "container",
        "empty_is_issue": False,
        "password": "hostname",
    },
}
