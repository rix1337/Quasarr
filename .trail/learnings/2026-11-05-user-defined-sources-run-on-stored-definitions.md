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
  - quasarr/storage/setup/custom_sources.py
  - quasarr/storage/setup/sites.py
  - quasarr/storage/setup/hostnames.py
  - quasarr/storage/setup/site_editor.py
  - quasarr/storage/template_overrides.py
  - quasarr/api/captcha/custom_userscript.py
---

## Decided

Users add their own sites as data, not modules. One `CustomSource` class serves both the search and the download contract from a JSON definition (feed URLs per category, search mode, BeautifulSoup selectors, download links). Built-in sources stay untouched; the registries merge custom sources in, and the orchestrators read a custom source's hostname from `custom_hostname` instead of the INI config.

Why: the orchestrators, payload, crypter handling, mirrors, statistics and hostname issues already work on source keys, so a generic source plugs in without a second code path.

Definitions live encrypted, one row per site, in the `custom_sources` table. Every process keeps its compiled sources and reloads them only when the shared `custom_sources_rev` stamp changes, so searches never touch the database. The INI config only holds fixed keys and prunes unknown ones, and large JSON does not belong there.

Custom keys are a letter from c to z plus a digit. Built-in keys are two letters, so they can never collide, and a custom key is never reused because grabbed payloads carry it.

Selectors are suggested, never guessed by the user alone. Every candidate is scored with the same extraction code the source runs, so the coverage shown is what the saved definition achieves. Item containers are found from the release links outward: the container that holds exactly one release link each. The release links are the ones whose text looks like a release name, or links in headings on sites without scene names.

Built-in sites move to bundled templates, one module per two-letter key in the templates package: a `TEMPLATE` definition plus, only where selectors cannot express a step, a hook (login sessions, JSON APIs, browser-only flows). Quirks that are data (paths, filters, query rules) extend the engine instead of becoming hooks. A template replaces the old module of the same key, so keys, hostname settings, credentials and grabbed payloads stay valid. Each site migrates in its own commit with full parity to the old module. Templates are Python modules rather than JSON files because the standalone build only collects submodules.

In Quasarr 6 every site is a template; module discovery is gone. Sites whose behavior is mostly code (logins, JSON APIs, solver sessions, episode selection) are template packages: the site code moved beside `TEMPLATE` as its search and download modules, and a hook names the module (`"search"`) whose `Source` runs that step. The loader builds the calls, passing the episode date only to searches that accept it, so packages hold no wrapper code. The site's addresses live in `TEMPLATE["urls"]` and the code reads them through `site_url`; only logic stays in code. A step the engine expresses fully moves into the template, as WX's feed did. Sites the engine expresses fully are single template modules; when a site needed something new, the engine gained a generic option instead of a hook.

A custom source can be exported as a template module for a pull request only after its live feed and search work, and only with its hostname replaced by `{host}`.

The wizard turns clicks into selectors on the server: a fetched page is parsed once, every element gets a number, and the browser only shows a sanitized copy in a sandboxed frame without site scripts, links or forms. It keeps the site's images and stylesheets so the preview looks like the page. Selectors are built and counted on that same parse, so a browser that repairs markup differently cannot produce a selector the source will not match. Site and user text reaches the page only as text. Field counts only include values that read as their kind (a size, a date, a link), so a wrong pick shows as missing.

Search result pages often differ from the newest-releases page. The wizard loads a real results page and checks whether the newest-releases fields read it; when they do not, the search gets its own fields.

Sites are set up from one page for onboarding and settings. Users paste the hostnames they know; Quasarr opens each one and runs the template detection, adds the built-in matches together and sends only the rest to the wizard. The wizard is for experienced users who found no built-in match, so it is no longer the default path. A built-in site counts as a match only when its template reads the page or the user's list names its key. The two-letter hostname rule alone is weak evidence (most hostnames contain the letters of several keys), so such fits are offered but never preselected.

Hostnames whose labels name a link protection service or a file hoster are refused for built-in and custom sites alike. Labels are compared whole, so a name that only contains such a word stays allowed.

Users may change the data parts of a built-in template (addresses, feeds, selectors, download rules), never its hooks, name or capabilities. Changes are stored apart and laid over the shipped template, so deleting a changed site resets it to the shipped one instead of removing it. A changed or self-made site is the user's to maintain: the UI, the startup log and the issue form say issues about it are not supported. The editor is JSON with live tests per step and sits behind a secondary menu; the guided wizard would drop options it has no field for, so it never edits built-in sites, and it keeps unknown options when it edits an own site or an imported template.

Shared templates import as JSON or as the exported module, read as a Python literal, never run; templates with hooks are refused because code ships only with Quasarr. Sites that need a login cannot be added by users at all: they need Python code through a pull request.

Release pages that only reveal links in a browser can go to the user's own userscript: the definition turns on the `userscript` download option, the release goes to the CAPTCHA queue unfetched, and the CAPTCHA page offers a readable template with fixed input and output stubs. The template has no update URL, so Quasarr never overwrites the user's code, and it works only after the user writes that code.

The wizard must set up every shipped site that needs no code (DT, FX, MB, NK, SL) on its own; rerun it against them after changing detection. Menu pages count only from the site navigation when it has one, since post titles name kinds too, and a page below another kind page is a genre of it. A "new releases" page carries the movies when the menu has none. A page's own RSS feed replaces it, as feeds read more reliably. The site language comes from the page (lang attribute, else common German or English words) because title searches depend on it. IMDb is tried whenever Radarr or Sonarr know an ID for the example, even if the feed shows none, and a result counts when it names the ID's title or carries the ID. Search results that only link posts are followed to the first post and read like the feed. A site that searches all kinds at once is searched per kind in the kind's section. In an automatic run a kind that reads nothing is left out with a note instead of blocking the others.

## Tried and ruled out

Editing built-in sites in the guided wizard: it rebuilds definitions from its own fields and silently drops filters, labels, parts and cleanups.


Taking every link that reads like a release as one: a tag link such as "720p" in every post made each post hold two releases, so the headline won as the block and size and date were lost. Links whose target repeats three or more times on a page are no release links.

Grouping repeated elements by their full class list missed real lists. Rows alternate classes, and posts carry per-post and per-genre classes, so no two items share a signature. Single stable classes per container fixed it.

Judging noise by class names (menu, sidebar, widget) hid a whole content area wrapped in a "sidebar" class. Only nav, footer, aside and menu elements count as noise now; the one-link-per-container rule filters the rest.

## Watch out

The wizard sets each step up on its own and only informs, never interrupts: it finds each kind's page from the site menu (menu words in English and German, the site's language preferred), tests every page, finds the search and tests it with each kind's newest release (its IMDb ID from the feed or through Radarr and Sonarr; titles when the feed shows no IDs or IDs find nothing), and opens a release to pick its download links. Search results count only when they look like video releases and pass the same release check as a real search. Sites that put the release name in the post text rather than the headline read it with the field option find: release, with the headline as a fallback way. The picker has two steps. First the release block on the full page: only blocks that repeat (on listing pages) and score at least half of the best are offered, and blocks that hold the same releases, nested or not, are one choice. Then the details on one release at a time, starting in the middle because the first and last blocks are often ads or notices, with arrows to check others; the rest of the page is hidden, so nothing outside a release can be picked. Users never type selectors in the wizard: each field is a dropdown of suggestions labelled with the value they read in the first release, plus Pick. Suggestions that read the same values are one choice, and a release name or link that repeats across releases (an author or tag link) is dropped when a fully distinct one exists. A click that misses takes the nearest element that reads as the field, and a suggestion that reads the same value in that release with at least the same coverage replaces the click's selector.

The picker runs as Quasarr's own script inside the preview: the frame allows scripts but not same-origin, popups, forms or top navigation, a per-render nonce in the frame's CSP lets only that script run, and it talks to the wizard by postMessage. Picking through listeners attached from the parent page, or an overlay that reads the frame with elementFromPoint, failed in Safari, which does not run event handlers in a frame with scripts disabled. Chromium does, so test the picker in WebKit as well.

A release link may point straight at a crypter or hoster (several releases per post). Grabs then fall through the shared crypter detection, so such definitions need no download step. On-site hoster buttons that redirect use the shared `resolve_crypter_redirect` when the download step sets `redirects`.

Each host keeps one HTTP session per process. A security check is passed once through FlareSolverr, and its cookies and User-Agent are reused by plain requests until they stop working; only then does FlareSolverr load the page itself. Rendering every request in the solver is far slower and loses the clearance.

Search discovery starts from a working feed: it searches for the name of one feed release that few other releases share, fires each candidate request (GET templates, the page's own GET or POST forms, common layouts), and keeps the first whose results name the query. Login forms are skipped. Whether the site answers IMDb IDs can only be probed when a feed release carries one; otherwise title search is assumed.

RSS is read with the HTML parser because lxml is not a dependency: `<link>` is renamed before parsing (the parser treats it as an empty tag) and the XML declaration is dropped.

A search template is only accepted when results name the query, are not the front page in disguise, and are not one match among hundreds. Sites that ignore the query answer with their feed.

Out of scope: JavaScript-rendered pages, login and multi-page listings. Built-ins whose search or links need an API or browser JavaScript (WX search, DW buttons) or their own protection (HE) cannot be rebuilt as custom sources.
