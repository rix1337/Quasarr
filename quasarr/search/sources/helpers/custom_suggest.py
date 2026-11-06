# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

"""Selector suggestions that guide users through defining a custom source.

Every candidate is generated from the page structure and then scored with the
same extraction code the source runs, so a suggestion's coverage is exactly
what the saved definition will achieve.
"""

import html
import re
import secrets
from collections import Counter
from urllib.parse import urljoin, urlparse

import soupsieve
from bs4 import BeautifulSoup, Tag

from quasarr.constants import CODEC_REGEX, RESOLUTION_REGEX, SEASON_EP_REGEX
from quasarr.search.sources.helpers.custom_source import (
    _SIZE_REGEX,
    _compile_field,
    _is_known_link,
    _mirror_name,
    _resolve_link,
    describe_report,
    extract_field,
    find_release_name,
    is_feed_markup,
    is_on_host,
    normalize_feed_markup,
    parse_date,
    parse_imdb_id,
    parse_listing,
    parse_size,
)

MIN_ITEMS = 3
_ISO_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{1,2}:\d{2}")
_ACCOUNT_FIELD = re.compile(r"login|user|pass|mail|name", re.I)
_RELEASE_TAGS = {
    "german",
    "english",
    "dubbed",
    "subbed",
    "dl",
    "ml",
    "web",
    "webrip",
    "web-dl",
    "bluray",
    "hdtv",
    "remux",
    "complete",
    "uncut",
    "repack",
    "proper",
    "multi",
}
# share of search results that must name the query; a page listing
# hundreds of releases with one match did not search
MIN_SEARCH_PRECISION = 0.02
# share of results that must name the distinctive query search discovery sends:
# fuzzy searches answer 1 of 10, a box of 20 recent posts on an unrelated page 1 of 20
# ponytail: a ratio, not proof; confirming with a second query would be stronger
DISCOVERY_PRECISION = 0.1
COMMON_SEARCH_TEMPLATES = (
    "https://{host}/?s={q}",
    "https://{host}/search?q={q}",
    "https://{host}/?q={q}",
    "https://{host}/search/{q}",
    # DataLife Engine sites
    "https://{host}/index.php?do=search&subaction=search&story={q}",
)
SAMPLE_ITEMS = 25
MAX_CANDIDATES = 3
_NOISE_TAGS = {"nav", "footer", "aside", "menu"}
_UNSTABLE_CLASS = re.compile(
    r"\d{3,}|^[a-z0-9]{14,}$|^(?:css|sc|jsx|emotion)-|[a-z][A-Z].*\d|^\w{1,2}\d+$"
)
_HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
_SCENE_GROUP = re.compile(r"-[A-Za-z0-9]{2,}$")
_SCENE_YEAR = re.compile(r"[.\s](?:19|20)\d{2}(?:[.\s]|$)")
_LABEL_TAIL = re.compile(r"([^\W\d_][\w\s\[\]()/.-]{1,24}?)\s*[:\]]+\s*$")


# --- Selectors ---------------------------------------------------------------


def stable_classes(element):
    return [c for c in element.get("class") or [] if not _UNSTABLE_CLASS.search(c)]


def _simple_selector(element):
    classes = stable_classes(element)
    if classes:
        return element.name + "".join(f".{_escape(c)}" for c in classes)
    return element.name


def _escape(identifier):
    return soupsieve.escape(identifier)


def _attribute_selector(element):
    href = element.get("href") if element.name == "a" else None
    if href:
        if "imdb.com/title" in href:
            return 'a[href*="imdb.com/title"]'
        host = urlparse(href).hostname
        if host and _is_known_link(href):
            root = host.removeprefix("www.").split(".")[0]
            return f'a[href*="{root}."]'
    if element.name == "time" and element.get("datetime"):
        return "time[datetime]"
    return None


def _matches_first(selector, root, element):
    try:
        return soupsieve.select_one(selector, root) is element
    except Exception:
        return False


def build_selector(element, root):
    """Shortest stable CSS selector, relative to root, whose first match is element."""
    if element is root:
        return ""
    own = [_attribute_selector(element), _simple_selector(element)]
    classes = stable_classes(element)
    own += [f"{element.name}.{_escape(c)}" for c in classes]
    for selector in own:
        if selector and _matches_first(selector, root, element):
            return selector

    path = []
    node = element
    while node is not None and node is not root:
        path.insert(0, node)
        node = node.parent
    # extend the chain upward until the element is the first match
    tail = _attribute_selector(element) or _simple_selector(element)
    for ancestor in reversed(path[:-1]):
        tail = f"{_simple_selector(ancestor)} {tail}"
        if _matches_first(tail, root, element):
            return tail

    steps = []
    for node in path:
        siblings = [s for s in node.parent.find_all(node.name, recursive=False)]
        index = siblings.index(node) + 1
        steps.append(f"{node.name}:nth-of-type({index})")
    return " > ".join(steps)


def _is_noise(element):
    """Navigation and footers; class names are too unreliable to judge by."""
    return any(
        isinstance(node, Tag) and node.name in _NOISE_TAGS
        for node in [element, *element.parents]
    )


# --- Text heuristics ---------------------------------------------------------


def release_likeness(text):
    """0..4: how much text looks like a release name."""
    text = (text or "").strip()
    if not 6 <= len(text) <= 300:
        return 0
    score = 0
    if RESOLUTION_REGEX.search(text) or CODEC_REGEX.search(text):
        score += 2
    if SEASON_EP_REGEX.search(text) or _SCENE_YEAR.search(text):
        score += 1
    if text.count(".") >= 3 and " " not in text.strip():
        score += 1
    if _SCENE_GROUP.search(text):
        score += 1
    return min(score, 4)


def _own_text(element):
    return " ".join(
        str(s).strip() for s in element.find_all(string=True, recursive=False)
    ).strip()


def _previous_text(node):
    for previous in node.find_all_previous(string=True, limit=6):
        if str(previous).strip():
            return str(previous)
    return ""


def _label_before(node, pattern=None):
    """A label like "Size:" right before a value, in the same or a prior node."""
    text = str(node)
    match = pattern.search(text) if pattern else None
    candidates = [text[: match.start()] if match else "", _previous_text(node)]
    for candidate in candidates:
        label = _LABEL_TAIL.search(candidate.strip(" \u00a0|-…."))
        if label:
            return label.group(1).strip(" .…[]")
    return None


# --- Item containers ---------------------------------------------------------


def _release_anchors(soup, page_url, hostname, min_items=MIN_ITEMS):
    """Links that most likely open one release each, keyed by their target."""
    anchors = []
    for anchor in soup.find_all("a", href=True):
        if "imdb.com" in anchor["href"] or _is_noise(anchor):
            continue
        text = anchor.get_text(" ", strip=True) or anchor.get("title") or ""
        link = _resolve_link(page_url, anchor["href"], hostname)
        if link and text:
            anchors.append((anchor, link, release_likeness(text)))
    # a tag or category link ("720p") repeats across releases; a release
    # link shows up once or twice (headline, comments)
    repeats = Counter(a[1] for a in anchors)
    anchors = [a for a in anchors if repeats[a[1]] < 3]
    strong = [a for a in anchors if a[2] >= 2]
    if len({a[1] for a in strong}) >= min_items:
        return strong
    # sites without release names: links in headings or title elements
    return [
        a
        for a in anchors
        if any(
            p.name in _HEADING_TAGS or "title" in " ".join(p.get("class") or [])
            for p in [a[0], *a[0].parents][:4]
            if isinstance(p, Tag)
        )
    ]


def _container_selectors(element):
    classes = stable_classes(element)[:6]
    selectors = [f"{element.name}.{_escape(c)}" for c in classes]
    if len(classes) > 1:
        selectors.append(_simple_selector(element))
    selectors.append(element.name)
    return selectors


def _top_level(elements):
    chosen = set(map(id, elements))
    return [e for e in elements if not any(id(p) in chosen for p in e.parents)]


def _score_containers(selector, soup, link_of):
    try:
        containers = _top_level(
            [c for c in soupsieve.select(selector, soup) if not _is_noise(c)]
        )
    except Exception:
        return None
    one = multi = zero = 0
    for container in containers:
        links = {link_of[id(a)] for a in container.find_all("a") if id(a) in link_of}
        if len(links) == 1:
            one += 1
        elif links:
            multi += 1
        else:
            zero += 1
    return containers, one, multi, zero


def suggest_items(soup, page_url, hostname, min_items=MIN_ITEMS):
    """Containers holding exactly one release link each, best first."""
    anchors = _release_anchors(soup, page_url, hostname, min_items)
    link_of = {id(a): link for a, link, _ in anchors}
    depth_of = {}
    for anchor, _, _ in anchors:
        for depth, ancestor in enumerate(anchor.parents, start=1):
            if ancestor.name in ("body", "html", "[document]") or depth > 8:
                break
            for selector in _container_selectors(ancestor):
                depth_of[selector] = max(depth_of.get(selector, 0), depth)

    candidates = []
    for selector, depth in depth_of.items():
        scored = _score_containers(selector, soup, link_of)
        if not scored:
            continue
        containers, one, multi, zero = scored
        if one < min_items:
            continue
        selector = _narrow(selector, containers, soup, link_of, (one, multi, zero))
        quality = one - 3 * multi - 0.25 * zero
        candidates.append(
            {
                "selector": selector,
                "count": one,
                "mixed": multi,
                "empty": zero,
                "score": round(quality + 0.1 * depth, 2),
            }
        )
    candidates.sort(key=lambda c: c["score"], reverse=True)
    unique, seen = [], set()
    for candidate in candidates:
        # blocks that hold the same releases, nested or not, are one choice
        found = frozenset(
            link_of[id(a)]
            for block in soupsieve.select(candidate["selector"], soup)
            for a in block.find_all("a")
            if id(a) in link_of
        )
        if found not in seen:
            seen.add(found)
            unique.append(candidate)
    return unique


def _likely_items(candidates, min_items):
    """The release blocks worth offering: repeated, and close to the best one.

    A search for one title may find a single release, so only listing pages
    require the block to repeat.
    """
    least = 2 if min_items > 1 else 1
    repeated = [c for c in candidates if c["count"] + c["mixed"] + c["empty"] >= least]
    if not repeated:
        return []
    top = repeated[0]["score"]
    return [c for c in repeated if c["score"] >= top / 2][:MAX_CANDIDATES]


def _narrow(selector, containers, soup, link_of, counts):
    """Prefix the selector with an ancestor when that drops empty matches."""
    one, multi, zero = counts
    if not zero:
        return selector
    best = selector
    for ancestor in list(containers[0].parents)[:4]:
        if ancestor.name in ("body", "html", "[document]"):
            break
        for prefix in _container_selectors(ancestor)[:-1] or [ancestor.name]:
            narrowed = f"{prefix} {selector}"
            scored = _score_containers(narrowed, soup, link_of)
            if scored and scored[1] == one and scored[3] < zero:
                best, zero = narrowed, scored[3]
    return best


# --- Fields ------------------------------------------------------------------


def _evaluate(items, spec, kind, page_url, hostname):
    """Score a field spec with the runtime extractor across all items."""
    try:
        field = _compile_field(spec, kind, "href" if kind == "link" else "text")
    except Exception:
        return None
    values = []
    for item in items:
        try:
            raw = extract_field(item, field)
        except Exception:
            raw = None
        if kind == "size":
            value = parse_size(raw, field["unit"]) if raw else None
        elif kind == "date":
            value = parse_date(raw, field["format"]) if raw else None
        elif kind == "imdb":
            value = parse_imdb_id(raw)
        elif kind == "link":
            value = _resolve_link(page_url, raw, hostname) if raw else None
        else:
            value = raw
        values.append(value)
    found = [v for v in values if v not in (None, "")]
    if not found:
        return None
    distinct = len(set(map(str, found))) / len(found)
    return {
        "spec": spec
        if isinstance(spec, list)
        else {k: v for k, v in spec.items() if v},
        "coverage": round(len(found) / len(items), 2),
        "distinct": round(distinct, 2),
        "samples": [str(v) for v in found[:3]],
        # per item, to tell candidates that read the same values apart
        "_values": values,
    }


def _first_way(spec):
    """A field read several ways is judged by its first way."""
    return spec[0] if isinstance(spec, list) else spec


def _rank(results, prefer=None, individual=False):
    results = [r for r in results if r]
    if individual and any(r["distinct"] == 1 for r in results):
        # every release has its own name and link; a repeated one is an author or tag
        results = [r for r in results if r["distinct"] == 1]
    ranked = sorted(
        results,
        key=lambda r: (
            r.get("release", False),
            r["coverage"] * (r["distinct"] if prefer == "distinct" else 1),
            r.get("bonus", 0)
            # position paths break on the next layout tweak
            - 3 * (":nth-of-type" in str(_first_way(r["spec"]).get("selector", ""))),
        ),
        reverse=True,
    )
    kept, seen = [], []
    for result in ranked:
        values = result.pop("_values")
        # the same values under another selector are no second choice
        if any(
            all(v is None or v == k for v, k in zip(values, other, strict=True))
            for other in seen
        ):
            continue
        kept.append(result)
        seen.append(values)
    return kept[:MAX_CANDIDATES]


def _count_selectors(items, finder):
    counts = Counter()
    for item in items:
        seen = set()
        for element in finder(item):
            selector = build_selector(element, item)
            if selector not in seen:
                seen.add(selector)
                counts[selector] += 1
    return [s for s, _ in counts.most_common(8)]


def suggest_title_link(items, page_url, hostname):
    def anchors(item):
        return [
            a
            for a in item.find_all("a", href=True)
            if a.get_text(strip=True)
            and _resolve_link(page_url, a["href"], hostname)
            and "imdb.com" not in a["href"]
        ]

    def scored(item):
        found = anchors(item)
        return sorted(
            found,
            key=lambda a: (
                release_likeness(a.get_text(" ", strip=True))
                + 2 * bool(set(p.name for p in a.parents) & _HEADING_TAGS)
                + bool("title" in " ".join(a.parent.get("class") or []))
            ),
            reverse=True,
        )[:2]

    link_results = []
    title_results = []
    for selector in _count_selectors(items, scored):
        link = _evaluate(
            items, {"selector": selector, "attr": "href"}, "link", page_url, hostname
        )
        title = _evaluate(items, {"selector": selector}, "title", page_url, hostname)
        for result in (link, title):
            if result:
                result["bonus"] = sum(release_likeness(s) for s in result["samples"])
        link_results.append(link)
        title_results.append(title)
        if title:
            title_attr = _evaluate(
                items,
                {"selector": selector, "attr": "title"},
                "title",
                page_url,
                hostname,
            )
            if title_attr:
                title_attr["bonus"] = sum(
                    release_likeness(s) for s in title_attr["samples"]
                )
                # the shorter one of text and title attribute is the cleaner name
                pairs = list(zip(title["samples"], title_attr["samples"], strict=False))
                if all(a != t and a in t for t, a in pairs):
                    title_attr["bonus"] += 1
                elif all(a != t and t in a for t, a in pairs):
                    title["bonus"] += 1
                title_results.append(title_attr)

    # a release name shown outside the link
    def named(item):
        return [e for e in item.find_all(True) if release_likeness(_own_text(e)) >= 3][
            :2
        ]

    for selector in _count_selectors(items, named):
        result = _evaluate(items, {"selector": selector}, "title", page_url, hostname)
        if result:
            result["bonus"] = sum(release_likeness(s) for s in result["samples"])
        title_results.append(result)

    # a release name at the start of a longer text, as a post body under a headline
    def holding(item):
        return [
            e
            for e in item.find_all(True)
            if (found := find_release_name(e.get_text(" ", strip=True)))
            and release_likeness(found) >= 3
            and found != e.get_text(" ", strip=True)
        ][:2]

    for selector in _count_selectors(items, holding):
        result = _evaluate(
            items,
            {"selector": selector, "find": "release"},
            "title",
            page_url,
            hostname,
        )
        if result:
            result["bonus"] = sum(release_likeness(s) for s in result["samples"]) + 1
        title_results.append(result)

    # a whole block of text is no name; a name that reads as a release comes first
    title_results = [
        r
        for r in title_results
        if r and sum(map(len, r["samples"])) / len(r["samples"]) <= 150
    ]
    for result in title_results:
        samples = result["samples"]
        result["release"] = (
            sum(release_likeness(s) for s in samples) / len(samples) >= 2
        )
    # release names in some posts only: the headline names the others
    inside = [r for r in title_results if r["spec"].get("find") and r["coverage"] < 1]
    headline = [r for r in title_results if not r["release"]]
    if inside and headline:
        best_inside = max(inside, key=lambda r: r["coverage"])
        best_headline = max(headline, key=lambda r: r["coverage"])
        both = _evaluate(
            items,
            [best_inside["spec"], best_headline["spec"]],
            "title",
            page_url,
            hostname,
        )
        if both and both["coverage"] > best_inside["coverage"]:
            both["release"] = True
            both["bonus"] = best_inside.get("bonus", 0) + 1
            title_results.append(both)
        # a whole block of text is not a release name
        if sum(map(len, samples)) / len(samples) > 120:
            result["bonus"] -= 3
        for other in title_results:
            pairs = list(zip(samples, other["samples"], strict=False))
            if other is not result and all(a != b and a in b for a, b in pairs):
                result["bonus"] += 1
    return {
        "title": _rank(title_results, prefer="distinct", individual=True),
        "link": _rank(link_results, prefer="distinct", individual=True),
    }


def suggest_size(items, page_url, hostname):
    labels = Counter()
    holders = []
    for item in items:
        for node in item.find_all(string=_SIZE_REGEX):
            label = _label_before(node, _SIZE_REGEX)
            if label:
                labels[label] += 1
            holders.append((item, node.parent))
    specs = [{"label": label} for label, _ in labels.most_common(3)]
    selectors = Counter(build_selector(parent, item) for item, parent in holders)
    specs += [{"selector": s} for s, _ in selectors.most_common(3)]
    specs.append({})  # first size anywhere in the item
    results = []
    for index, spec in enumerate(specs):
        result = _evaluate(items, spec, "size", page_url, hostname)
        if result:
            result["bonus"] = -index
        results.append(result)
    return _rank(results)


def suggest_date(items, page_url, hostname):
    specs = []
    if any(item.find("time", datetime=True) for item in items):
        specs.append({"selector": "time[datetime]", "attr": "datetime"})
    # machine-readable timestamps in attributes carry the time the text omits
    attributes = Counter()
    for item in items[:5]:
        for element in item.find_all(True):
            for name, value in element.attrs.items():
                if name in ("class", "href", "src", "data-q") or not isinstance(
                    value, str
                ):
                    continue
                if _ISO_TIMESTAMP.match(value.strip()):
                    attributes[(build_selector(element, item), name)] += 1
    for (selector, name), _ in attributes.most_common(2):
        specs.insert(
            0, {"selector": selector, "attr": name} if selector else {"attr": name}
        )
    labels = Counter()
    selectors = Counter()
    for item in items:
        for node in item.find_all(string=True):
            text = str(node).strip()
            if not text or len(text) > 80 or not parse_date(text):
                continue
            if not re.search(r"\d", text):
                continue
            selectors[build_selector(node.parent, item)] += 1
            label = _label_before(node)
            if label:
                labels[label] += 1
    specs += [{"label": label} for label, _ in labels.most_common(2)]
    specs += [{"selector": s} for s, _ in selectors.most_common(3)]
    results = []
    for index, spec in enumerate(specs):
        result = _evaluate(items, spec, "date", page_url, hostname)
        if result:
            result["bonus"] = -index
        results.append(result)
    return _rank(results, prefer="distinct")


def suggest_imdb(items, page_url, hostname):
    found = sum(
        1
        for item in items
        if any(parse_imdb_id(a["href"]) for a in item.find_all("a", href=True))
    )
    if found:
        return [
            {
                "spec": None,
                "coverage": round(found / len(items), 2),
                "samples": [],
                "note": "IMDb links are found automatically",
            }
        ]
    return []


def suggest_listing(
    markup,
    page_url,
    hostname,
    item_selector=None,
    min_items=MIN_ITEMS,
    query=None,
    avoid_links=None,
):
    """Item and field suggestions for one listing page, best first.

    Search result pages may hold a single release, so the search step passes
    ``min_items=1``.
    """
    if is_feed_markup(markup):
        return _suggest_feed_listing(markup, page_url, hostname)
    soup = BeautifulSoup(markup, "html.parser")
    item_candidates = _likely_items(
        suggest_items(soup, page_url, hostname, min_items), min_items
    )
    if item_selector:
        chosen = [{"selector": item_selector}]
    else:
        chosen = item_candidates[:MAX_CANDIDATES]

    best = None
    for candidate in chosen:
        try:
            items = soupsieve.select(candidate["selector"], soup)
        except Exception:
            continue
        items = items[:SAMPLE_ITEMS]
        if not items:
            continue
        fields = suggest_title_link(items, page_url, hostname)
        fields["size"] = suggest_size(items, page_url, hostname)
        fields["date"] = suggest_date(items, page_url, hostname)
        fields["imdb"] = suggest_imdb(items, page_url, hostname)
        quality = sum(
            fields[f][0]["coverage"] * weight
            for f, weight in (("title", 2), ("link", 2), ("size", 1), ("date", 1))
            if fields[f]
        )
        # a widget of post titles next to the releases reads as well, but its
        # names are no release names
        if fields["title"]:
            samples = fields["title"][0]["samples"]
            quality += (
                2
                * sum(release_likeness(t) >= 2 for t in samples)
                / max(len(samples), 1)
            )
            # on a results page, the results name what was searched for; a list
            # of recent posts beside them does not
            words = [
                w.lower()
                for w in re.split(r"[\W_]+", query or "")
                if len(w) > 2 and not re.fullmatch(r"tt\d+", w.lower())
            ]
            if words:
                quality += (
                    4
                    * sum(all(w in t.lower() for w in words) for t in samples)
                    / max(len(samples), 1)
                )
        # a "recent posts" box lists the feed again; results are other releases.
        # Feeds may link short addresses, so the names count as well.
        if avoid_links and fields["link"]:
            links = fields["link"][0]["samples"]
            names = fields["title"][0]["samples"] if fields["title"] else []
            again = [
                link in avoid_links or _plain(name) in avoid_links
                for link, name in zip(links, names + [""] * len(links), strict=False)
            ]
            quality -= 6 * sum(again) / max(len(again), 1)
        if best is None or quality > best["quality"]:
            best = {"item": candidate["selector"], "fields": fields, "quality": quality}

    return {
        "items": item_candidates,
        "best": best,
        "search": suggest_search_url(soup, page_url, hostname),
    }


def _suggest_feed_listing(markup, page_url, hostname):
    """RSS and Atom feeds share one layout, so they need no item search."""
    soup = BeautifulSoup(normalize_feed_markup(markup), "html.parser")
    item = "item" if soup.find("item") else "entry"
    items = soup.select(item)[:SAMPLE_ITEMS]
    fields = {"imdb": []}
    if items:
        fields["title"] = _rank(
            [_evaluate(items, {"selector": "title"}, "title", page_url, hostname)]
        )
        fields["link"] = _rank(
            [
                _evaluate(
                    items,
                    {"selector": "permalink", "attr": "text"},
                    "link",
                    page_url,
                    hostname,
                ),
                _evaluate(
                    items,
                    {"selector": "link", "attr": "href"},
                    "link",
                    page_url,
                    hostname,
                ),
            ]
        )
        fields["date"] = _rank(
            [
                _evaluate(items, {"selector": name}, "date", page_url, hostname)
                for name in ("pubdate", "published", "updated")
            ]
        )
        fields["size"] = suggest_size(items, page_url, hostname)
        fields["imdb"] = suggest_imdb(items, page_url, hostname)
    best = {"item": item, "fields": fields, "quality": len(items)} if items else None
    return {
        "items": [{"selector": item, "count": len(items), "score": len(items)}]
        if items
        else [],
        "best": best,
        "search": suggest_search_url(
            BeautifulSoup("", "html.parser"), page_url, hostname
        ),
    }


def listing_from_suggestion(best):
    """Turn the top suggestion of every field into a definition listing."""
    listing = {"item": best["item"]}
    for field in ("title", "link", "size", "date", "imdb"):
        if best["fields"].get(field):
            listing[field] = best["fields"][field][0]["spec"]
    # a release name read from the post text falls back to the link text for
    # releases that name none, as albums and books often do
    title, link = listing.get("title"), listing.get("link")
    if isinstance(title, dict) and title.get("find") and isinstance(link, dict):
        fallback = {"selector": link["selector"]} if link.get("selector") else {}
        listing["title"] = [title, fallback]
    return listing


def builtin_matches(hostname):
    """Built-in sources already set to this hostname, so no custom one is needed."""
    from quasarr.providers import shared_state

    try:
        config = shared_state.values["config"]("Hostnames")
        from quasarr.search.sources.helpers import get_hostnames

        return [
            key.upper()
            for key in get_hostnames()
            if str(config.get(key) or "").lower().removeprefix("www.") == hostname
        ]
    except Exception:
        return []


# --- Search and download -------------------------------------------------------


def _candidate(url, method="get", body=None):
    candidate = {"url": url, "method": method}
    if body:
        candidate["body"] = body
    return candidate


# menu words for each kind of release, in English and German
_FEED_WORDS = {
    2000: ("movies", "movie", "films", "film", "filme", "kino"),
    5000: (
        "tv shows",
        "tv",
        "series",
        "serien",
        "serie",
        "shows",
        "episoden",
        "staffeln",
    ),
    3000: ("music", "musik", "audio", "mp3", "albums", "alben"),
    7000: (
        "books",
        "ebooks",
        "e-books",
        "ebook",
        "e-book",
        "bücher",
        "buecher",
        "magazines",
        "zeitschriften",
    ),
}
# menu words for the newest releases of every kind
_NEW_WORDS = ("new releases", "latest releases", "neuerscheinungen", "neu erschienen")
# how menus name a language, to prefer the site's own over the others
_LANGUAGE_WORDS = {
    "de": ("german", "deutsch", "deutsche"),
    "en": ("english", "englisch"),
    "fr": ("french", "français", "francais", "französisch"),
}
_OTHER_LANGUAGE = re.compile(r"\b(international|non-\w+|foreign)\b")


def suggest_feeds(soup, page_url, hostname, language=None):
    """Pages for each kind of release, found by their menu links.

    Returns {category: path}. A short link text that holds one of the words
    counts; release names do not. Menus often split a kind by language, as
    "German Movies" and "English Movies", so the site's language wins.
    """
    own = _LANGUAGE_WORDS.get(language, ())
    others = [
        w for code, words in _LANGUAGE_WORDS.items() if code != language for w in words
    ]
    found = {}
    kinds_of = {}
    generic = []
    for anchor in soup.find_all("a", href=True):
        text = " ".join(anchor.get_text(" ", strip=True).lower().split())
        if not text or len(text) > 30 or release_likeness(text) >= 2:
            continue
        # a title with its year is a post ("Der Film (2026)"), not a menu entry
        if re.search(r"\b(19|20)\d\d\b", text):
            continue
        link = _resolve_link(page_url, anchor["href"], hostname)
        if not link or not is_on_host(link, hostname):
            continue
        parsed = urlparse(link)
        path = parsed.path or "/"
        if path == "/":
            continue
        if parsed.query:
            path += "?" + parsed.query
        if any(re.search(rf"\b{w}\b", text) for w in _NEW_WORDS):
            generic.append(((0 if _in_menu(anchor) else 1, len(path)), path))
        for category, words in _FEED_WORDS.items():
            for rank, word in enumerate(words):
                if text == word:
                    match = 0
                elif re.search(rf"\b{re.escape(word)}\b", text):
                    match = 1
                else:
                    continue
                if any(re.search(rf"\b{w}\b", text) for w in own):
                    spoken = 0
                elif _OTHER_LANGUAGE.search(text) or any(
                    re.search(rf"\b{w}\b", text) for w in others
                ):
                    spoken = 2
                else:
                    spoken = 1
                # the word decides first; language only between links of one word
                score = (rank, spoken, match, path.count("/"), len(path))
                kinds_of.setdefault(path, set()).add(category)
                found.setdefault(category, []).append((score, path, _in_menu(anchor)))
                break

    # a page below another kind page is a genre of it ("Filme > Musical"),
    # not a kind of its own
    def nested(path):
        return any(other != path and path.startswith(other) for other in kinds_of)

    # post titles name kinds too ("… Der Film (2026)"): with a menu, only it counts
    menu = any(link[2] for links in found.values() for link in links)
    # a page linked as several kinds is a mixed list, not a kind of its own
    chosen = {}
    for category, links in found.items():
        own_pages = [
            link[:2]
            for link in links
            if len(kinds_of[link[1]]) == 1
            and not nested(link[1])
            and (link[2] or not menu)
        ]
        if own_pages:
            chosen[category] = min(own_pages)[1]
    # "New releases" carries the movies when the menu has no movie page
    if 2000 not in chosen and generic:
        chosen[2000] = min(generic)[1]
    return chosen


_GERMAN_WORDS = re.compile(r"\b(und|der|die|das|mit|nicht|für|ist|auch|neu)\b")
_ENGLISH_WORDS = re.compile(r"\b(and|the|with|not|for|is|also|new)\b")


def page_language(soup):
    """The page's language code: its lang attribute, else German or English
    by their most common words. None when neither shows."""
    root = soup.find("html")
    code = str(root.get("lang") or "").strip().lower()[:2] if root else ""
    if code.isalpha() and len(code) == 2:
        return code
    text = soup.get_text(" ", strip=True).lower()
    german = len(_GERMAN_WORDS.findall(text))
    english = len(_ENGLISH_WORDS.findall(text))
    if max(german, english) < 10:
        return None
    return "de" if german > english else "en"


def unreadable_reason(soup):
    """Why a page shows no releases Quasarr can read, when the page itself says so.

    A login form or a page that only fills in through JavaScript cannot be set
    up without code.
    """
    body = soup.find("body") or soup
    text = " ".join(body.get_text(" ", strip=True).split())
    if (
        soup.find("input", attrs={"type": "password"})
        and len(body.find_all("a", href=True)) < 15
    ):
        return "login"
    scripts = len(soup.find_all("script"))
    app_root = soup.find(id=re.compile(r"^(app|root|__next|__nuxt)$"))
    if len(text) < 300 and (scripts >= 3 or app_root is not None):
        return "javascript"
    return None


def page_rss(soup, page_url, hostname):
    """The RSS feed of this very page, as an alternate link or an RSS button.

    Feeds carry the names, links and dates in fixed fields, so they read more
    reliably than the page. A site-wide feed only counts for the main page.
    """
    page_path = urlparse(page_url).path or "/"
    found = []
    for node in soup.find_all(["link", "a"], href=True):
        if node.name == "link":
            kind = str(node.get("type") or "").lower()
            if "rss" not in kind and "atom" not in kind:
                continue
        else:
            names = " ".join(
                [*(node.get("class") or []), str(node.get("title") or "")]
            ).lower()
            if "rss" not in names and node.get_text(strip=True).lower() != "rss":
                continue
        link = _resolve_link(page_url, node["href"], hostname)
        if not link or not is_on_host(link, hostname):
            continue
        path = urlparse(link).path or "/"
        if path != page_path and path.startswith(page_path) and "comments" not in path:
            found.append((len(path), path))
    return min(found)[1] if found else None


_MENU_HINT = re.compile(r"\b(menu|nav|navbar|navigation)\b", re.I)


def _in_menu(anchor):
    """Whether a link sits in the site navigation rather than in a post."""
    for parent in list(anchor.parents)[:8]:
        if parent.name in ("nav", "header"):
            return True
        if parent.name in ("article", "main"):
            return False
        names = " ".join(parent.get("class") or []) + " " + str(parent.get("id") or "")
        if _MENU_HINT.search(names.replace("-", " ").replace("_", " ")):
            return True
    return False


def suggest_search_url(soup, page_url, hostname):
    """Search requests from the page's search forms, then common layouts.

    Each candidate is ``{"url", "method", "body"}``; a POST form carries the
    query in its body.
    """
    candidates = []
    for form in soup.find_all("form"):
        method = (form.get("method") or "get").lower()
        if method not in ("get", "post"):
            continue
        field = form.find("input", attrs={"type": ["search", "text"]}) or form.find(
            "input", attrs={"name": "s"}
        )
        if field is None or not field.get("name"):
            continue
        # login and newsletter forms also have a text field
        if form.find("input", attrs={"type": "password"}) or _ACCOUNT_FIELD.search(
            field["name"]
        ):
            continue
        action = urljoin(page_url, form.get("action") or page_url)
        if not is_on_host(action, hostname):
            continue
        path = urlparse(action).path or "/"
        fields = [f"{field['name']}={{q}}"] + [
            f"{i['name']}={i.get('value', '')}"
            for i in form.find_all("input", attrs={"type": "hidden"})
            if i.get("name")
        ]
        if method == "post":
            candidates.append(
                _candidate(f"https://{{host}}{path}", "post", "&".join(fields))
            )
        else:
            candidates.append(_candidate(f"https://{{host}}{path}?{'&'.join(fields)}"))

    # a category feed often searches within its own path
    section = urlparse(page_url).path
    for suffix in ("feed/", "rss/", "feed", "rss"):
        section = section.removesuffix(suffix)
    if section.strip("/"):
        candidates.append(_candidate(f"https://{{host}}{section.rstrip('/')}/?s={{q}}"))
    candidates += [_candidate(template) for template in COMMON_SEARCH_TEMPLATES]

    unique = []
    for candidate in candidates:
        if candidate not in unique:
            unique.append(candidate)
    return unique


def search_quality(query, rows, feed_rows=(), imdb_id=None):
    """How well search results answer the query; judges a template in preview.

    A search by IMDb ID passes the ID's title as the query: a result matches
    when it names the title or carries the ID.
    """
    words = [w.lower() for w in re.split(r"[\W_]+", query) if len(w) > 2]

    def matches_query(row):
        if imdb_id and row.get("imdb_id") == imdb_id:
            return True
        return all(w in row["title"].lower() for w in words)

    matches = sum(map(matches_query, rows))
    # feeds may link short addresses, so names count as well
    feed_keys = {r["link"] for r in feed_rows} | {_plain(r["title"]) for r in feed_rows}

    def in_feed(row):
        return row["link"] in feed_keys or _plain(row["title"]) in feed_keys

    # a site that ignores the query answers with its front page
    unrelated_feed = sum(in_feed(r) and not matches_query(r) for r in rows)
    same_as_feed = bool(rows) and unrelated_feed >= len(rows) / 2
    return {
        "rows": len(rows),
        "matches": matches,
        "same_as_feed": same_as_feed,
        "works": matches > 0
        and not same_as_feed
        and matches >= len(rows) * MIN_SEARCH_PRECISION,
    }


def _hoster_named(anchor):
    from quasarr.constants import SHARE_HOSTERS_LOWERCASE

    # image buttons name the hoster only in their address, as /go/rapidgator
    text = " ".join(
        [
            anchor.get_text(" ", strip=True),
            *(anchor.get("class") or []),
            urlparse(anchor.get("href") or "").path,
        ]
    ).lower()
    return any(hoster.split(".")[0] in text for hoster in SHARE_HOSTERS_LOWERCASE)


def suggest_download(markup, page_url, hostname=None):
    """Link selectors on a release page that collect crypter and hoster links."""
    return _download_candidates(
        BeautifulSoup(markup, "html.parser"), page_url, hostname
    )


def _mirror_default(anchors, page_url):
    """How links are best named: crypter addresses say nothing about the hoster."""
    from quasarr.constants import SHARE_HOSTERS_LOWERCASE

    texts = " ".join(a.get_text(" ", strip=True).lower() for a in anchors)
    named = sum(h in texts for h in SHARE_HOSTERS_LOWERCASE) >= max(
        1, len(anchors) // 2
    )

    def to_hoster(anchor):
        host = (urlparse(urljoin(page_url, anchor["href"])).hostname or "").lower()
        return any(part in SHARE_HOSTERS_LOWERCASE for part in host.split("."))

    if sum(map(to_hoster, anchors)) * 2 >= len(anchors):
        return "text" if named else "href_host"
    return "hoster_name" if named else "text"


def _link_names(anchor, page_url):
    """What each naming choice calls one link, shown in the wizard."""
    href = urljoin(page_url, anchor.get("href", ""))
    return {
        mode: _mirror_name(anchor, href, mode)
        for mode in ("text", "href_host", "hoster_name")
    }


# hoster pages that sell accounts rather than hold a file, as in ads and ref links
_HOSTER_PAGES = re.compile(
    r"/(account|registration|register|signup|premium|pricing|ref|affiliate|login)\b|[?&]ref=",
    re.I,
)


def _download_link(url):
    if not _is_known_link(url):
        return False
    parsed = urlparse(url)
    return parsed.path.strip("/") != "" and not _HOSTER_PAGES.search(
        parsed.path + ("?" + parsed.query if parsed.query else "")
    )


# on-site buttons that forward to a hoster or crypter
_REDIRECT_PATH = re.compile(r"/(go|out|redirect|link)/[^/]+")
# a crypter link for a sample or trailer is no download of the release
_EXTRA_LINK = re.compile(r"\b(sample|trailer|probe|vorschau)\b", re.I)


def _download_candidates(soup, page_url, hostname=None):
    anchors = soup.find_all("a", href=True)
    known = [
        a
        for a in anchors
        if _download_link(urljoin(page_url, a["href"]))
        and not _EXTRA_LINK.search(a.get_text(" ", strip=True))
    ]
    redirects = False
    if not known and hostname:
        # on-site buttons named after hosters redirect to the real links
        known = [
            a
            for a in anchors
            if is_on_host(urljoin(page_url, a["href"]), hostname)
            and (_hoster_named(a) or _REDIRECT_PATH.match(urlparse(a["href"]).path))
            and not _is_noise(a)
        ]
        redirects = bool(known)
    if not known:
        return []
    selectors = Counter()
    for anchor in known:
        selectors[_attribute_selector(anchor) or build_selector(anchor, soup)] += 1
        container = anchor.find_parent(
            lambda t: (
                t.name in ("div", "p", "td", "ul", "section") and stable_classes(t)
            )
        )
        if container is not None:
            selectors[f"{_simple_selector(container)} a[href]"] += 1

    # forwarding buttons are named by the hoster in their text or address
    mirror = "hoster_name" if redirects else _mirror_default(known, page_url)
    results = []
    seen = set()
    for selector, _ in selectors.most_common(6):
        try:
            matched = soupsieve.select(selector, soup)
        except Exception:
            continue
        hits = [a for a in matched if a in known]
        # selectors that collect the same links are one choice
        found = frozenset(map(id, matched))
        if not hits or found in seen:
            continue
        seen.add(found)
        spec = {"selector": selector, "mirror": mirror}
        if redirects:
            spec["redirects"] = True
        results.append(
            {
                "spec": spec,
                "names": _link_names(hits[0], page_url),
                "known": len(hits),
                "other": len(matched) - len(hits),
                "coverage": round(len(hits) / len(known), 2),
            }
        )
    results.sort(key=lambda r: (r["coverage"], -r["other"]), reverse=True)
    return results[:MAX_CANDIDATES]


def pick_download(soup, q, page_url, hostname):
    """The download link selector around one clicked link.

    A suggestion that holds the clicked link wins; otherwise the links that
    share its box, or links like it, are taken.
    """
    element = element_by_q(soup, q)
    if element is None:
        return {"error": "The page changed. Load it again."}
    anchor = (
        element
        if element.name == "a" and element.get("href")
        else element.find_parent("a", href=True) or element.find("a", href=True)
    )
    # a click next to the links, as on a "Mirror 1" label, takes the closest one
    for box in element.parents if anchor is None else []:
        if box.name in ("body", "html", "[document]"):
            break
        anchor = box.find("a", href=True)
        if anchor is not None:
            break
    if anchor is None:
        return {"error": "That is not a link. Click one of the download links."}
    for candidate in _download_candidates(soup, page_url, hostname):
        if anchor in soupsieve.select(candidate["spec"]["selector"], soup):
            return candidate
    container = anchor.find_parent(
        lambda t: t.name in ("div", "p", "td", "ul", "section") and stable_classes(t)
    )
    selectors = [_attribute_selector(anchor)]
    if container is not None:
        selectors.append(f"{_simple_selector(container)} a[href]")
    selectors.append(build_selector(anchor, soup))
    selector = next(s for s in selectors if s and anchor in soupsieve.select(s, soup))
    matched = soupsieve.select(selector, soup)
    return {
        "spec": {"selector": selector, "mirror": _mirror_default(matched, page_url)},
        "names": _link_names(anchor, page_url),
        "known": len(matched),
        "other": 0,
        "coverage": 1.0,
    }


# --- Search discovery ------------------------------------------------------------

# the wizard waits for discovery, so it gets a budget of its own
SEARCH_DISCOVERY_SECONDS = 90
SEARCH_DISCOVERY_TIMEOUT = 15


def _name_words(title):
    """The words naming a release: everything before year, season or tags."""
    words = []
    for word in re.split(r"[.\s_]+", title):
        if (
            re.fullmatch(r"(?:19|20)\d{2}", word)
            or SEASON_EP_REGEX.fullmatch(word)
            or RESOLUTION_REGEX.search(word)
            or word.lower() in _RELEASE_TAGS
        ):
            break
        if word.isalnum() and not word.isdigit() and len(word) > 2:
            words.append(word)
    return words


def _plain(name):
    """A release name for comparing: lower case, dots and spaces alike."""
    return " ".join(re.split(r"[\W_]+", str(name or "").lower())).strip()


def pick_query(rows, skip=()):
    """A release name from the feed that few other releases share, and its row.

    ``skip`` holds queries already tried, so a second call picks another release.
    """
    names = [(row, _name_words(row["title"])[:3]) for row in rows]
    names = [(row, words) for row, words in names if " ".join(words) not in skip]
    counts = Counter(w.lower() for _, words in names for w in set(words))
    for row, words in names:
        if words and min(counts[w.lower()] for w in words) <= 2:
            return " ".join(words), row
    # every name is common: any release name still tests the search
    for row, words in names:
        if words:
            return " ".join(words), row
    return "", None


def _search_rows(markup, url, hostname, listing, feed_rows, query):
    """Rows of a search page, with the feed layout first and its own second."""
    from quasarr.search.sources.helpers.custom_source import _compile_listing

    rows = parse_listing(markup, url, _compile_listing(listing, "list"), hostname)[
        "rows"
    ]
    if search_quality(query, rows, feed_rows)["works"]:
        return rows, None
    words = [w for w in _plain(query).split() if len(w) > 2]
    unrelated = [
        row for row in feed_rows if not all(w in _plain(row["title"]) for w in words)
    ]
    own = suggest_listing(
        markup,
        url,
        hostname,
        min_items=1,
        query=query,
        # feed releases the query does not name: a box of recent posts, not results
        avoid_links={row["link"] for row in unrelated}
        | {_plain(row["title"]) for row in unrelated},
    )
    if not own["best"]:
        return rows, None
    own_listing = listing_from_suggestion(own["best"])
    try:
        own_rows = parse_listing(
            markup, url, _compile_listing(own_listing, "search_list"), hostname
        )["rows"]
    except Exception:
        return rows, None
    return own_rows, own_listing


def _search_request(candidate, hostname, query):
    from urllib.parse import parse_qsl, quote_plus

    url = candidate["url"].replace("{host}", hostname)
    if candidate["method"] == "post":
        body = candidate["body"].replace("{q}", quote_plus(query))
        return url, dict(parse_qsl(body))
    return url.replace("{q}", quote_plus(query)), None


def discover_search(shared_state, hostname, feed_url, listing, fetch=None):
    """Find a working search URL and whether the site answers IMDb IDs.

    Starts from the feed: a query is built from one of its releases, each
    candidate template is fired once, and the first one whose results name the
    query wins. A release with an IMDb ID then tells whether ``imdb`` or
    ``title`` search fits.
    """
    import time

    from quasarr.search.sources.helpers.custom_source import (
        _compile_listing,
        fetch_markup,
    )

    fetch = fetch or fetch_markup
    deadline = time.time() + SEARCH_DISCOVERY_SECONDS
    feed = fetch(shared_state, feed_url, SEARCH_DISCOVERY_TIMEOUT, False)
    if feed.error:
        return {"success": False, "error": f"Feed: {feed.error}"}
    feed_rows = parse_listing(
        feed.markup, feed_url, _compile_listing(listing, "list"), hostname
    )["rows"]
    query, query_row = pick_query(feed_rows)
    if not query:
        return {"success": False, "error": "The feed has no release to search for"}

    form_page = feed.markup
    if is_feed_markup(feed.markup):
        # an RSS feed has no search form, the front page usually does
        front = fetch(
            shared_state, f"https://{hostname}/", SEARCH_DISCOVERY_TIMEOUT, False
        )
        form_page = front.markup or ""
    candidates = suggest_search_url(
        BeautifulSoup(form_page, "html.parser"), feed_url, hostname
    )

    attempts = []
    found = None
    tried = []
    # the newest release may not be searchable yet: up to three releases are tried
    while query and len(tried) < 3 and not found and time.time() < deadline:
        tried.append(query)
        for template in candidates:
            if time.time() >= deadline:
                break
            url, form = _search_request(template, hostname, query)
            # a slow site sometimes answers with an unrelated page: one match among
            # many is a box of recent posts there, so that address is asked again
            for _ in range(2):
                page = fetch(shared_state, url, SEARCH_DISCOVERY_TIMEOUT, False, form)
                if page.error:
                    attempts.append({"search": template, "error": page.error})
                    break
                rows, own_listing = _search_rows(
                    page.markup, url, hostname, listing, feed_rows, query
                )
                quality = search_quality(query, rows, feed_rows)
                attempts.append({"search": template, "query": query, **quality})
                precise = quality["matches"] >= DISCOVERY_PRECISION * len(rows)
                if not quality["works"] or precise:
                    break
            if page.error:
                continue
            if quality["works"] and precise:
                found = {"search": template, "search_list": own_listing}
                break
        if not found:
            query, query_row = pick_query(feed_rows, tried)
    query = tried[-1] if tried else query

    if not found:
        return {
            "success": False,
            "query": query,
            "attempts": attempts,
            "error": "No search URL answered the query",
        }

    # IMDb ID or title is left to the wizard's search test, which tries IMDb IDs first
    return {
        "success": True,
        "query": query,
        "query_title": query_row["title"],
        "search": found["search"],
        "search_list": found["search_list"],
        # a template that finds text finds music and books too
        "phrase": True,
        "attempts": attempts,
        # the other addresses, for a kind the found one cannot search
        "alternatives": [c for c in candidates if c != found["search"]],
    }


# --- Bundled template detection ---------------------------------------------------


def _template_rows(source, markup, url, hostname):
    listing = source.spec["list"]
    if not listing or not markup:
        return 0
    try:
        rows = parse_listing(markup, url, listing, hostname)["rows"]
    except Exception:
        return 0
    return len(rows)


def detect_templates(shared_state, markup, page_url, hostname, fetch=None):
    """Bundled templates that read this site, so no custom source is needed.

    Every template is tried on the page the user loaded. Templates whose key
    letters both appear in the domain (the naming rule of the built-in
    hostnames) also get their own first feed fetched.
    """
    from quasarr.search.sources.helpers.custom_source import fetch_markup
    from quasarr.search.sources.templates import get_templates

    fetch = fetch or fetch_markup
    domain = hostname.split(".")[0]
    matches = []
    for key, source in get_templates().items():
        rows = _template_rows(source, markup, page_url, hostname)
        if rows < MIN_ITEMS and all(letter in domain for letter in key):
            feeds = source.spec["feeds"]
            if feeds:
                url = next(iter(feeds.values())).replace("{host}", hostname)
                page = fetch(shared_state, url, SEARCH_DISCOVERY_TIMEOUT, False)
                rows = _template_rows(source, page.markup, url, hostname)
        if rows >= MIN_ITEMS:
            matches.append({"key": key.upper(), "name": source.name, "rows": rows})
    matches.sort(key=lambda m: m["rows"], reverse=True)
    return matches


# --- Template export -----------------------------------------------------------

_EXPORT_DROPPED = ("key", "hostname", "enabled", "schema")


def verify_definition(shared_state, source):
    """Check the live feed and search of a source; returns the problems found."""
    from quasarr.constants import (
        FEED_REQUEST_TIMEOUT_SECONDS,
        SEARCH_REQUEST_TIMEOUT_SECONDS,
    )

    spec = source.spec
    problems = []
    feed_rows = []
    if not spec["feeds"]:
        problems.append("No feed is set up")
    for category in spec["feeds"]:
        url, data = source.feed_request(category)
        report, fetched = source.load_listing(
            shared_state, url, spec["list"], FEED_REQUEST_TIMEOUT_SECONDS, data
        )
        issue = fetched.error or describe_report(report)
        if issue:
            problems.append(f"Feed {category}: {issue}")
        else:
            feed_rows += report["rows"]

    if not spec["search_url"]:
        problems.append("No search is set up")
    elif feed_rows:
        query, _ = pick_query(feed_rows)
        url, data = source.search_request(query)
        report, fetched = source.load_listing(
            shared_state, url, spec["search_list"], SEARCH_REQUEST_TIMEOUT_SECONDS, data
        )
        rows = report["rows"] if report else []
        if fetched.error or not search_quality(query, rows, feed_rows)["works"]:
            problems.append(
                f"Search for {query!r} did not find it: {fetched.error or 'no match'}"
            )
    return problems


def export_template(shared_state, definition):
    """A bundled-template module for a verified custom source, ready for a PR.

    Export needs a working feed and search, so shared templates are proven.
    The hostname never leaves Quasarr: it is replaced by ``{host}`` and the
    export is refused if it still appears anywhere.
    """
    import pprint

    from quasarr.search.sources.helpers.custom_source import CustomSource

    source = CustomSource(definition)
    problems = verify_definition(shared_state, source)
    if problems:
        return {"success": False, "problems": problems}

    hostname = source.hostname
    template = {k: v for k, v in definition.items() if k not in _EXPORT_DROPPED}
    body = pprint.pformat(template, indent=4, sort_dicts=False, width=88)
    body = body.replace(hostname, "{host}")
    site_name = hostname.removeprefix("www.").split(".")[0]
    # short names also occur in release tags, only longer ones identify a site
    if len(site_name) > 3 and site_name in body.lower():
        return {
            "success": False,
            "problems": ["The site name still appears in the template; remove it"],
        }
    module = (
        "# -*- coding: utf-8 -*-\n"
        "# Quasarr\n"
        "# Project by https://github.com/rix1337\n\n"
        f"TEMPLATE = {body}\n"
    )
    return {
        "success": True,
        "path": "quasarr/search/sources/templates/<two-letter key>.py",
        "module": module,
    }


def report_table(markup, page_url, listing, hostname, report, limit=25):
    """Releases and skipped items in page order, for the wizard's result table.

    A skipped item shows what its fields read as plain text, with the reason.
    """
    skipped = dict(report["skipped_at"])
    if not skipped:
        return report["rows"][:limit]
    soup = BeautifulSoup(normalize_feed_markup(markup), "html.parser")
    items = listing["item"].select(soup)
    rows = iter(report["rows"])
    table = []
    for index, item in enumerate(items[: len(report["rows"]) + len(skipped)]):
        if len(table) >= limit:
            break
        if index not in skipped:
            table.append(next(rows))
            continue
        cells = {"skipped": skipped[index]}
        for name in ("title", "size", "date"):
            try:
                raw = extract_field(item, listing[name]) if listing[name] else None
            except Exception:
                raw = None
            cells[name] = " ".join(str(raw or "").split())[:200]
        table.append(cells)
    return table


# --- Page picker ------------------------------------------------------------------

# elements that run code, embed other pages or submit data: never shown in a preview
_UNSAFE_TAGS = (
    "script",
    "noscript",
    "iframe",
    "frame",
    "frameset",
    "object",
    "embed",
    "applet",
    "base",
    "meta",
    "form",
    "input",
    "button",
    "textarea",
    "select",
    "option",
    "template",
    "svg",
    "math",
    "audio",
    "video",
    "source",
    "track",
    "canvas",
    "portal",
    "dialog",
    "slot",
)
_URL_ATTRIBUTES = (
    "href",
    "src",
    "srcset",
    "action",
    "formaction",
    "poster",
    "background",
    "xlink:href",
    "data",
    "codebase",
    "cite",
    "ping",
    "lowsrc",
    "dynsrc",
)
# Only the wizard's own script runs; images, stylesheets and fonts still load
PREVIEW_CSP = (
    "default-src 'none'; script-src 'nonce-{nonce}'; style-src http: https: 'unsafe-inline'; "
    "img-src http: https: data:; font-src http: https: data:; form-action 'none'"
)
# one color per part, shared by the preview, the field rows and the result tables
FIELD_COLORS = {
    "item": "#0d6efd",
    "title": "#d63384",
    "link": "#6f42c1",
    "size": "#198754",
    "date": "#fd7e14",
}

_PREVIEW_STYLE = (
    ".q-picking [data-q]{cursor:crosshair}"
    # one release on its own: everything else is hidden
    ".q-solo body *:not(.q-keep):not(.q-shown):not(.q-shown *){display:none !important}"
    ".q-hover{outline:2px dashed #0dcaf0 !important;outline-offset:1px}"
    f".q-item{{outline:2px solid {FIELD_COLORS['item']} !important;outline-offset:2px}}"
    # the link often is the name too, so it gets an outline instead of a fill
    f".q-link{{outline:2px solid {FIELD_COLORS['link']} !important;outline-offset:1px}}"
    + "".join(
        f".q-{name}{{background:{color}40 !important;box-shadow:0 0 0 2px {color} inset}}"
        for name, color in FIELD_COLORS.items()
        if name in ("title", "size", "date")
    )
)

# Runs inside the sandboxed preview, which has no access to the wizard page.
# It never follows links and only reports which numbered element was clicked.
_PREVIEW_SCRIPT = """
(function() {
  var picking = false, hovered = null, shown = null;
  function post(message) { parent.postMessage(message, '*'); }
  function numbered(node) { return node && node.closest ? node.closest('[data-q]') : null; }
  function hover(node) {
    if (hovered) hovered.classList.remove('q-hover');
    hovered = node;
    if (node) node.classList.add('q-hover');
  }
  // shows only one release, so details can only be picked inside it
  function solo(q) {
    document.querySelectorAll('.q-keep, .q-shown').forEach(function(node) {
      node.classList.remove('q-keep', 'q-shown');
    });
    shown = q === null || q === undefined
      ? null : document.querySelector('[data-q="' + Number(q) + '"]');
    document.documentElement.classList.toggle('q-solo', !!shown);
    if (!shown) return;
    shown.classList.add('q-shown');
    for (var node = shown.parentElement; node; node = node.parentElement) node.classList.add('q-keep');
  }
  function mark(name, list) {
    document.querySelectorAll('.' + name).forEach(function(node) { node.classList.remove(name); });
    (list || []).forEach(function(q) {
      var node = document.querySelector('[data-q="' + Number(q) + '"]');
      if (node) node.classList.add(name);
    });
  }
  addEventListener('message', function(event) {
    if (event.source !== parent) return;
    var message = event.data || {};
    if (message.type === 'mark') {
      mark('q-item', message.items);
      ['title', 'link', 'size', 'date'].forEach(function(name) {
        mark('q-' + name, (message.fields || {})[name]);
      });
      solo(message.shown);
      var first = shown || (message.scroll && document.querySelector('.q-item'));
      // scrolls only this preview; scrollIntoView would move the wizard page too
      if (first) {
        var top = first.getBoundingClientRect().top + window.scrollY;
        window.scrollTo(0, Math.max(0, shown ? top - 8 : top - window.innerHeight / 3));
      }
    } else if (message.type === 'picking') {
      picking = !!message.on;
      document.documentElement.classList.toggle('q-picking', picking);
      if (!picking) hover(null);
    }
  });
  document.addEventListener('mouseover', function(event) {
    if (picking) hover(numbered(event.target));
  }, true);
  document.addEventListener('click', function(event) {
    event.preventDefault();
    event.stopPropagation();
    // a click that picks nothing says why, so the wizard can explain it
    var node = numbered(event.target);
    if (!picking) post({type: 'refused', reason: 'idle'});
    else if (shown && !shown.contains(event.target)) post({type: 'refused', reason: 'outside'});
    else if (!node) post({type: 'refused', reason: 'nothing'});
    else post({type: 'pick', q: Number(node.getAttribute('data-q'))});
  }, true);
  document.addEventListener('keydown', function(event) {
    if (event.key === 'Escape') post({type: 'cancel'});
  });
  post({type: 'ready'});
})();
"""


def annotate_page(markup):
    """Parse a page once and number its elements for click-to-pick.

    The numbers are only stored on this parse, so selectors built from a click
    are checked against exactly the tree the source runs on.
    """
    soup = BeautifulSoup(normalize_feed_markup(markup), "html.parser")
    for index, element in enumerate(soup.find_all(True)):
        element["data-q"] = str(index)
    return soup


def _is_stylesheet(element):
    rel = element.get("rel") or []
    rel = rel.split() if isinstance(rel, str) else rel
    return "stylesheet" in [value.lower() for value in rel]


def _web_address(value):
    return urlparse(str(value).strip()).scheme.lower() in ("", "http", "https")


def preview_html(soup, page_url):
    """A copy of an annotated page that runs only the wizard's picker script.

    Site code, forms and embedded pages are removed. Images, stylesheets and
    fonts load from the site so the preview looks like the page.
    """
    import copy

    page = copy.copy(soup)
    for element in page.find_all(_UNSAFE_TAGS):
        element.decompose()
    for element in page.find_all("link"):
        if not (_is_stylesheet(element) and _web_address(element.get("href", ""))):
            element.decompose()
    for element in page.find_all(True):
        # what an element may load from the site
        keep = {"img": ("src", "srcset"), "link": ("href",)}.get(element.name, ())
        for attribute in list(element.attrs):
            name = attribute.lower()
            if name in keep and _web_address(element[attribute]):
                continue
            if (
                name.startswith("on")
                or name in _URL_ATTRIBUTES
                or name in ("srcdoc", "target")
            ):
                del element[attribute]
    body = page.body or page
    head = "".join(str(tag) for tag in page.find_all(["link", "style"]))
    content = "".join(
        str(child) for child in body.children if child.name not in ("link", "style")
    )
    nonce = secrets.token_urlsafe(16)
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        '<meta name="referrer" content="no-referrer">'
        f'<meta http-equiv="Content-Security-Policy" '
        f'content="{PREVIEW_CSP.format(nonce=nonce)}">'
        f'<base href="{html.escape(page_url)}">'
        f"{head}<style>{_PREVIEW_STYLE}</style></head><body>{content}"
        f'<script nonce="{nonce}">{_PREVIEW_SCRIPT}</script></body></html>'
    )


def element_by_q(soup, q):
    return soup.find(attrs={"data-q": str(q)})


def q_of(element):
    return element.get("data-q") if element is not None else None


def _contains(container, element):
    return container is element or any(
        parent is container for parent in element.parents
    )


def pick_item(soup, q, page_url, hostname, min_items=1):
    """The release container around a clicked element."""
    element = element_by_q(soup, q)
    if element is None:
        return None
    for candidate in suggest_items(soup, page_url, hostname, min_items):
        try:
            matches = soupsieve.select(candidate["selector"], soup)
        except Exception:
            continue
        if len(matches) >= 2 and any(_contains(match, element) for match in matches):
            return {"selector": candidate["selector"], "count": len(matches)}
    # no suggested block: the closest repeated container around the click
    for node in [element, *element.parents]:
        if not isinstance(node, Tag) or node.name in ("body", "html", "[document]"):
            break
        for selector in _container_selectors(node):
            matches = soupsieve.select(selector, soup)
            if len(matches) >= 2 and node in matches:
                return {"selector": selector, "count": len(matches)}
    return {
        "error": "Nothing around this repeats like a release does. Click inside one release."
    }


def _around(element, container):
    """Elements near a click inside one release, closest first."""
    nodes = [element, *element.find_all(True)]
    for node in element.parents:
        if node is container:
            break
        nodes.append(node)
    nodes += container.find_all(True)
    seen, ordered = set(), []
    for node in nodes:
        if id(node) not in seen:
            seen.add(id(node))
            ordered.append(node)
    return ordered


def _field_spec(target, container, field):
    spec = {}
    if field in ("link", "source"):
        spec["attr"] = "href"
    elif field == "date" and target.get("datetime"):
        spec["attr"] = "datetime"
    selector = build_selector(target, container)
    if selector:
        spec["selector"] = selector
    return spec


def _value_in(container, spec, field, page_url, hostname):
    from quasarr.search.sources.helpers.custom_source import _compile_field

    try:
        compiled = _compile_field(spec, field, "href" if field == "link" else "text")
        value = _reads(container, compiled, field, page_url, hostname)
    except Exception:
        return None
    # a whole block of text is not a release name
    if field == "title" and value is not None and len(str(value)) > 200:
        return None
    return value


def _field_suggestions(items, field, page_url, hostname):
    if field in ("title", "link"):
        return suggest_title_link(items, page_url, hostname)[field]
    if field == "size":
        return suggest_size(items, page_url, hostname)
    if field == "date":
        return suggest_date(items, page_url, hostname)
    return []


def pick_field(soup, q, item_selector, field, page_url, hostname):
    """A field selector, relative to its release, built from one click.

    A click that misses, such as on the space next to a link, takes the
    nearest element that reads as the field. When a suggestion reads the same
    value in that release and in more releases, the suggestion wins.
    """
    element = element_by_q(soup, q)
    if element is None:
        return {"error": "The page changed. Load it again."}
    try:
        items = soupsieve.select(item_selector, soup)
    except Exception:
        return {"error": "The release block selector is not valid."}
    container = next((item for item in items if _contains(item, element)), None)
    if container is None:
        return {"error": "Click inside one of the highlighted releases."}
    spec, value = None, None
    for target in _around(element, container):
        if field in ("link", "source") and not (
            target.name == "a" and target.get("href")
        ):
            continue
        candidate = _field_spec(target, container, field)
        value = _value_in(container, candidate, field, page_url, hostname)
        if value is not None:
            spec = candidate
            break
    if spec is None:
        return {"error": "Nothing in this release reads as that. Click it directly."}
    note = None
    if field == "title":
        spec, value, note = _release_name_spec(element, container, spec, value)
    sample = items[:SAMPLE_ITEMS]
    result = _evaluate(sample, spec, field, page_url, hostname)
    for suggestion in _field_suggestions(sample, field, page_url, hostname):
        if (
            suggestion["spec"]
            and suggestion["coverage"] >= (result or {}).get("coverage", 0)
            and _value_in(container, suggestion["spec"], field, page_url, hostname)
            == value
        ):
            spec, result = suggestion["spec"], suggestion
            break
    if result:
        result.pop("_values", None)
    picked = {"spec": spec, "result": result, "value": str(value)}
    if note:
        picked["note"] = note
    return picked


def _release_name_spec(element, container, spec, value):
    """A picked name that is no release name is replaced or flagged.

    A release name with spaces is fine. A longer text that starts with one
    keeps just the name; a headline gives way to a release name in the text
    of the same release, and is flagged when there is none.
    """
    text = str(value)
    found = find_release_name(text)
    if release_likeness(text) >= 3 and (not found or found == text):
        return spec, value, None
    if found and release_likeness(found) >= 3:
        return {**spec, "find": "release"}, found, None
    for node in _around(element, container):
        found = find_release_name(node.get_text(" ", strip=True))
        if found and release_likeness(found) >= 3:
            selector = build_selector(node, container)
            replaced = {
                "find": "release",
                **({"selector": selector} if selector else {}),
            }
            return (
                replaced,
                found,
                (
                    "That looks like a headline, not a release name. Quasarr reads the release "
                    "name from the text of each release instead."
                ),
            )
    return (
        spec,
        value,
        (
            "That does not look like a release name, as Movie.Title.2026.1080p.WEB.x264-GROUP. "
            "Your apps only accept releases with names like that."
        ),
    )


def highlight(soup, item_selector, fields, page_url="", hostname="", options=None):
    """Element numbers a listing reads, to outline them in the preview.

    A field only counts where its value also reads as that kind of value, so
    a size picked on a date shows up as missing instead of as found. "values"
    holds what each field reads per release, and "options" the same for each
    suggested spec, so the wizard can show them for whichever release it shows.
    """
    try:
        items = soupsieve.select(item_selector, soup) if item_selector else []
    except Exception:
        return {"error": "The release block selector is not valid."}
    marked = {
        "items": [q_of(item) for item in items],
        "fields": {},
        "values": {},
        "options": {},
    }
    for name, spec in (fields or {}).items():
        try:
            field = _compile_field(spec, name, "href" if name == "link" else "text")
        except Exception as e:
            marked["fields"][name] = {"error": str(e)}
            continue
        found, values = [], []
        for item in items:
            base = field["within"].closest(item) if field.get("within") else item
            element = None
            if base is not None:
                element = (
                    field["selector"].select_one(base) if field["selector"] else base
                )
            value = (
                _reads(item, field, name, page_url, hostname)
                if element is not None and q_of(element)
                else None
            )
            if value is not None:
                found.append(q_of(element))
            values.append(None if value is None else str(value))
        marked["fields"][name] = found
        marked["values"][name] = values
    for name, specs in (options or {}).items():
        marked["options"][name] = [
            _values_of(items, spec, name, page_url, hostname)
            for spec in list(specs)[: MAX_CANDIDATES * 2]
        ]
    return marked


def _values_of(items, spec, name, page_url, hostname):
    try:
        field = _compile_field(spec, name, "href" if name == "link" else "text")
    except Exception:
        return [None] * len(items)
    values = []
    for item in items:
        try:
            value = _reads(item, field, name, page_url, hostname)
        except Exception:
            value = None
        values.append(None if value is None else str(value))
    return values


def _reads(item, field, name, page_url, hostname):
    """The value a field reads in one release, or None if it reads nothing usable."""
    raw = extract_field(item, field)
    if not raw:
        return None
    if name == "size":
        return parse_size(raw, field["unit"])
    if name == "date":
        # shown as the page writes it; only the reading decides its zone
        return " ".join(raw.split()) if parse_date(raw, field["format"]) else None
    if name == "link":
        return _resolve_link(page_url, raw, hostname)
    if name == "imdb":
        return parse_imdb_id(raw)
    return raw


def _template_from_module(text):
    """The TEMPLATE literal of an exported template module, read without running it."""
    import ast

    from quasarr.search.sources.helpers.custom_source import DefinitionError

    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError) as e:
        raise DefinitionError("Neither JSON nor a template file") from e
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            getattr(target, "id", None) == "TEMPLATE" for target in node.targets
        ):
            try:
                return ast.literal_eval(node.value)
            except (ValueError, TypeError, SyntaxError, RecursionError) as e:
                raise DefinitionError("TEMPLATE must be plain data") from e
    raise DefinitionError("The file has no TEMPLATE")


def import_template(text):
    """A definition from shared JSON or an exported template module.

    Templates that link code ship with Quasarr only, so they are refused here.
    """
    import json

    from quasarr.search.sources.helpers.custom_source import (
        DefinitionError,
        compile_definition,
    )

    text = str(text or "").strip()
    if len(text) > 200_000:
        raise DefinitionError("The template is too large")
    try:
        definition = json.loads(text)
    except ValueError:
        definition = None
    if definition is None:
        definition = _template_from_module(text)
    if not isinstance(definition, dict):
        raise DefinitionError("The template must be an object")
    if definition.get("hooks"):
        raise DefinitionError(
            "This template needs Quasarr's own code and can only ship with Quasarr"
        )
    definition = {
        k: v
        for k, v in definition.items()
        if k not in ("key", "hostname", "schema", "enabled")
    }
    # the placeholders only let the engine check everything else
    compile_definition({**definition, "key": "c1", "hostname": "example.invalid"})
    return definition
