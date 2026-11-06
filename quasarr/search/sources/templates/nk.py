# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

# Feed and search are the same form: an empty search lists the newest releases.
RELEASES = {
    "item": "div.article-right",
    "title": {"selector": "span.subtitle"},
    "link": {"selector": "a.release-details", "attr": "href"},
    "imdb": {"selector": "a.imdb", "attr": "href"},
    "size": {"selector": "ul.release-infos", "label": "Größe"},
    "date": {"selector": "p.meta"},
    "password": {"selector": "p.mirrors", "label": "Passwort", "adjacent": True},
    "title_cleanup": "none",
    "dedupe": False,
}

TEMPLATE = {
    "name": "NK",
    "language": "de",
    "feeds": [
        {
            "category": category,
            "url": "https://{host}/search",
            "method": "post",
            "body": "search=",
        }
        for category in (2000, 5000)
    ],
    "feed_validate": True,
    "list": RELEASES,
    "search": {
        "mode": "title",
        "method": "post",
        "url": "https://{host}/search",
        "body": "search={q}",
        "categories": [2000, 5000],
        "append_year": True,
        "episode_query": True,
    },
    "download": {
        "links": {"selector": "a.btn-orange", "mirror": "hoster_name"},
        "filter": "all",
        "mirror_names": ["rapidgator", "ddownload"],
        "filter_mirrors": "exact",
        # on-site /go/ links redirect to the crypter container
        "redirects": True,
        "redirect_targets": "crypter",
        "empty_is_issue": False,
        "password": "none",
    },
}
