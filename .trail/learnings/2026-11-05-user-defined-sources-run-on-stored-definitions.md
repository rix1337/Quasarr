---
title: User-defined sources run on stored definitions, guided by scored suggestions
date: 2026-11-05
author: Quasarr
touches:
  - quasarr/search/sources/helpers/custom_source.py
  - quasarr/search/sources/helpers/custom_suggest.py
  - quasarr/storage/custom_sources.py
  - quasarr/api/config/custom_sources.py
  - quasarr/search/sources/__init__.py
  - quasarr/downloads/sources/__init__.py
  - quasarr/search/__init__.py
  - quasarr/downloads/__init__.py
  - quasarr/search/sources/templates/__init__.py
---

## Decided

Users add their own sites as data, not modules. One `CustomSource` class serves both the search and the download contract from a JSON definition (feed URLs per category, search mode, BeautifulSoup selectors, download links). Built-in sources stay untouched; the registries merge custom sources in, and the orchestrators read a custom source's hostname from `custom_hostname` instead of the INI config.

Why: the orchestrators, payload, crypter handling, mirrors, statistics and hostname issues already work on source keys, so a generic source plugs in without a second code path.

Definitions live encrypted, one row per site, in the `custom_sources` table. Every process keeps its compiled sources and reloads them only when the shared `custom_sources_rev` stamp changes, so searches never touch the database. The INI config only holds fixed keys and prunes unknown ones, and large JSON does not belong there.

Custom keys are a letter from c to z plus a digit. Built-in keys are two letters, so they can never collide, and a custom key is never reused because grabbed payloads carry it.

Selectors are suggested, never guessed by the user alone. Every candidate is scored with the same extraction code the source runs, so the coverage shown is what the saved definition achieves. Item containers are found from the release links outward: the container that holds exactly one release link each. The release links are the ones whose text looks like a release name, or links in headings on sites without scene names.

Built-in sites move to bundled templates, one module per two-letter key in the templates package: a `TEMPLATE` definition plus, only where selectors cannot express a step, hook functions in the same module (login sessions, JSON APIs, browser-only flows). Quirks that are data (paths, filters, query rules) extend the engine instead of becoming hooks. A template replaces the old module of the same key, so keys, hostname settings, credentials and grabbed payloads stay valid. Each site migrates in its own commit with full parity to the old module. Bundled templates are read-only; users copy one into a custom source, without its hooks. Templates are Python modules rather than JSON files because the standalone build only collects submodules.

A custom source can be exported as a template module for a pull request only after its live feed and search work, and only with its hostname replaced by `{host}`.

## Tried and ruled out

Grouping repeated elements by their full class list missed real lists. Rows alternate classes, and posts carry per-post and per-genre classes, so no two items share a signature. Single stable classes per container fixed it.

Judging noise by class names (menu, sidebar, widget) hid a whole content area wrapped in a "sidebar" class. Only nav, footer, aside and menu elements count as noise now; the one-link-per-container rule filters the rest.

## Watch out

A release link may point straight at a crypter or hoster (several releases per post). Grabs then fall through the shared crypter detection, so such definitions need no download step. On-site hoster buttons that redirect use the shared `resolve_crypter_redirect` when the download step sets `redirects`.

Each host keeps one HTTP session per process. A security check is passed once through FlareSolverr, and its cookies and User-Agent are reused by plain requests until they stop working; only then does FlareSolverr load the page itself. Rendering every request in the solver is far slower and loses the clearance.

Search discovery starts from a working feed: it searches for the name of one feed release that few other releases share, fires each candidate request (GET templates, the page's own GET or POST forms, common layouts), and keeps the first whose results name the query. Login forms are skipped. Whether the site answers IMDb IDs can only be probed when a feed release carries one; otherwise title search is assumed.

RSS is read with the HTML parser because lxml is not a dependency: `<link>` is renamed before parsing (the parser treats it as an empty tag) and the XML declaration is dropped.

A search template is only accepted when results name the query, are not the front page in disguise, and are not one match among hundreds. Sites that ignore the query answer with their feed.

Out of scope: JavaScript-rendered pages, login and multi-page listings. Built-ins whose search or links need an API or browser JavaScript (WX search, DW buttons) or their own protection (HE) cannot be rebuilt as custom sources.
