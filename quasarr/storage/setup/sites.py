# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

"""The sites page: built-in templates first, the site wizard for the rest.

Users paste the hostnames they know. Quasarr checks each one against the
built-in templates, adds the matches, and points only the leftovers to the
wizard. Passwords never reach the page; site text is shown as text only.
"""

import re
from concurrent.futures import ThreadPoolExecutor

from bottle import request, response

import quasarr.providers.web_server
from quasarr.constants import (
    FEED_REQUEST_TIMEOUT_SECONDS,
    SEARCH_CAT_BOOKS,
    SEARCH_CAT_MOVIES,
    SEARCH_CAT_MUSIC,
    SEARCH_CAT_SHOWS,
    SEARCH_CAT_SHOWS_ANIME,
    SEARCH_CAT_SHOWS_DOCUMENTARY,
    SEARCH_CAT_XXX,
)
from quasarr.providers.auth import require_api_key
from quasarr.providers.hostname_issues import (
    clear_hostname_issue,
    get_all_hostname_issues,
    record_configured_hostnames,
)
from quasarr.providers.html_images import FLAG_SVGS, LANGUAGE_FLAG_EMOJI
from quasarr.providers.html_templates import json_for_script, render_form
from quasarr.providers.shared_state import extract_valid_hostname
from quasarr.storage.config import Config
from quasarr.storage.sqlite_database import DataBase

# hostnames checked at once; each check loads up to a few pages of that site
MAX_HOSTNAMES = 40
_CHECK_WORKERS = 6
_KV_LINE = re.compile(r"^\s*([A-Za-z]{2})\s*[=:]\s*(\S+)\s*$")
CATEGORY_LABELS = (
    (SEARCH_CAT_MOVIES, "Movies"),
    (SEARCH_CAT_SHOWS, "TV"),
    (SEARCH_CAT_SHOWS_ANIME, "Anime"),
    (SEARCH_CAT_SHOWS_DOCUMENTARY, "Docs"),
    (SEARCH_CAT_MUSIC, "Music"),
    (SEARCH_CAT_BOOKS, "Books"),
    (SEARCH_CAT_XXX, "Adult"),
)
_LANGUAGES = {"de": "German", "en": "English", "fr": "French"}


def _clean_hostname(raw):
    value = str(raw or "").strip().lower()
    value = re.sub(r"^[a-z]+://", "", value)
    value = re.split(r"[/?#\s]", value, maxsplit=1)[0]
    return value.removeprefix("www.").strip(".")


def _login_section(key):
    return "JUNKIES" if key in ("dj", "sj") else key.upper()


def _describe(source):
    """What a site offers and needs, for the page's chips."""
    categories = set(source.supported_categories)
    return {
        "lang": source.language,
        "language": _LANGUAGES.get(source.language, source.language),
        "flag": LANGUAGE_FLAG_EMOJI.get(source.language, ""),
        "kinds": [label for cat, label in CATEGORY_LABELS if cat in categories],
        "needs_login": bool(source.requires_login),
        "needs_account": bool(source.requires_account),
        "invite_only": bool(source.invite_only),
        "needs_flaresolverr": bool(source.requires_flaresolverr),
    }


def _status(key, issues, problem=None):
    """Traffic light and a sentence for one configured site."""
    if problem:
        return "warn", problem
    issue = issues.get(key)
    if issue:
        operation = issue.get("operation") or "use"
        return (
            "error",
            f"Last {operation} failed: {issue.get('error', 'unknown error')}",
        )
    return "ok", "Working"


def sites_overview(shared_state, onboarding=False):
    """Configured sites (built-in and custom) and the built-in catalog.

    Onboarding asks for FlareSolverr and the *arr apps after this page, so
    their absence is no problem yet.
    """
    from quasarr.search.sources.helpers import (
        get_radarr_required_hostnames,
        get_sonarr_required_hostnames,
    )
    from quasarr.search.sources.templates import get_templates, is_modified
    from quasarr.storage.custom_sources import load_definitions
    from quasarr.storage.setup.arr import missing_arr_client_requirement
    from quasarr.storage.setup.radarr import is_radarr_configured
    from quasarr.storage.setup.sonarr import is_sonarr_configured

    hostnames = Config("Hostnames")
    skip_login = DataBase("skip_login")
    issues = get_all_hostname_issues()
    radarr_required = set(get_radarr_required_hostnames())
    sonarr_required = set(get_sonarr_required_hostnames())
    radarr_ok = is_radarr_configured(shared_state)
    sonarr_ok = is_sonarr_configured(shared_state)
    flaresolverr_ready = _flaresolverr_ready(shared_state)

    sites = []
    catalog = []
    for key, source in sorted(get_templates().items()):
        hostname = str(hostnames.get(key) or "").strip()
        about = _describe(source)
        catalog.append({"key": key.upper(), "added": bool(hostname), **about})
        if not hostname:
            continue
        login_user = ""
        if source.requires_login:
            login_user = str(Config(_login_section(key)).get("user") or "")
        problem = None
        if source.requires_login and skip_login.retrieve(key):
            problem = "Login skipped: Quasarr cannot search this site without it."
        elif source.requires_login and not login_user:
            problem = "Needs your login for this site."
        elif onboarding:
            pass
        elif source.requires_flaresolverr and not flaresolverr_ready:
            problem = "Needs FlareSolverr, which is not set up."
        else:
            missing = missing_arr_client_requirement(
                key, radarr_required, sonarr_required, radarr_ok, sonarr_ok
            )
            if missing:
                problem = f"Needs {missing} for titles. Set it up on the home page."
        state, text = _status(key, issues, problem)
        sites.append(
            {
                "kind": "builtin",
                "key": key.upper(),
                "name": key.upper(),
                "hostname": hostname,
                "state": state,
                "status": text,
                "login_user": login_user,
                "modified": is_modified(key),
                **about,
            }
        )

    from quasarr.search.sources.helpers.custom_source import CustomSource

    for key, definition in sorted(load_definitions().items()):
        try:
            about = _describe(CustomSource(definition))
        except Exception:
            about = {"language": "", "flag": "", "kinds": []}
        state, text = _status(key, issues)
        if definition.get("enabled") is False:
            state, text = "warn", "Switched off"
        sites.append(
            {
                "kind": "custom",
                "key": key.upper(),
                "name": str(definition.get("name") or key.upper()),
                "hostname": str(definition.get("hostname") or ""),
                "state": state,
                "status": text,
                **about,
            }
        )
    return {"sites": sites, "catalog": catalog}


def _flaresolverr_ready(shared_state):
    try:
        from quasarr.providers.utils import is_flaresolverr_available

        return is_flaresolverr_available(shared_state)
    except Exception:
        return False


def parse_hostname_list(text):
    """Hostnames from pasted text: one per line or separated by spaces/commas.

    Community lists write ``xx = hostname``; such a line names its site.
    """
    entries = []
    seen = set()
    for line in str(text or "").splitlines():
        match = _KV_LINE.match(line)
        if match:
            parts = [(match.group(1).lower(), match.group(2))]
        else:
            parts = [(None, part) for part in re.split(r"[\s,;]+", line) if part]
        for key, raw in parts:
            hostname = _clean_hostname(raw)
            if hostname and hostname not in seen:
                seen.add(hostname)
                entries.append({"hostname": hostname, "key": key})
    return entries[:MAX_HOSTNAMES]


def check_hostname(shared_state, hostname, named_key=None, fetch=None):
    """What Quasarr can do with one hostname, without saving anything."""
    from quasarr.search.sources.helpers.custom_source import (
        DefinitionError,
        fetch_markup,
        normalize_hostname,
    )
    from quasarr.search.sources.helpers.custom_suggest import detect_templates
    from quasarr.search.sources.templates import get_templates
    from quasarr.storage.custom_sources import load_definitions

    result = {"hostname": hostname, "verified": [], "possible": [], "added_as": None}
    try:
        hostname = normalize_hostname(hostname)
    except DefinitionError as e:
        result["blocked"] = str(e).split(": ", 1)[-1]
        return result
    result["hostname"] = hostname

    configured = Config("Hostnames")
    templates = get_templates()
    for key in templates:
        if str(configured.get(key) or "").lower().removeprefix("www.") == hostname:
            result["added_as"] = key.upper()
            return result
    for definition in load_definitions().values():
        if definition.get("hostname") == hostname:
            result["added_as"] = str(
                definition.get("name") or definition["key"].upper()
            )
            return result

    if named_key:
        if named_key in templates and extract_valid_hostname(hostname, named_key).get(
            "domain"
        ):
            result["named"] = named_key.upper()
        else:
            result["named_error"] = f"{named_key.upper()} does not fit this hostname"

    fits = [
        key for key in templates if extract_valid_hostname(hostname, key).get("domain")
    ]
    url = f"https://{hostname}/"
    page = (fetch or fetch_markup)(
        shared_state, url, FEED_REQUEST_TIMEOUT_SECONDS, False
    )
    if page.error:
        result["unreachable"] = _short_error(page)
    verified = {
        match["key"].lower(): match["rows"]
        for match in detect_templates(
            shared_state, page.markup or "", url, hostname, fetch=fetch
        )
    }
    for key in sorted(verified, key=verified.get, reverse=True):
        result["verified"].append(_candidate(templates[key], key, verified[key]))
    for key in fits:
        if key not in verified:
            result["possible"].append(_candidate(templates[key], key, None))
    return result


def _short_error(page):
    """A fetch error in words a user can act on."""
    text = str(page.error)
    if page.status:
        return f"it answered with HTTP {page.status}"
    if "resolve" in text or "NameResolution" in text:
        return "the name does not resolve"
    if "timed out" in text.lower() or "timeout" in text.lower():
        return "it did not answer in time"
    if "SSL" in text:
        return "its certificate failed the check"
    return "the connection failed"


def _candidate(source, key, rows):
    return {"key": key.upper(), "rows": rows, **_describe(source)}


def check_hostnames(shared_state, text):
    entries = parse_hostname_list(text)
    if not entries:
        return []
    with ThreadPoolExecutor(max_workers=min(_CHECK_WORKERS, len(entries))) as pool:
        return list(
            pool.map(
                lambda entry: check_hostname(
                    shared_state, entry["hostname"], entry["key"]
                ),
                entries,
            )
        )


def add_builtin_site(key, hostname):
    """Point a built-in template at a hostname; returns an error or None."""
    from quasarr.search.sources.templates import get_templates

    key = str(key or "").lower()
    if key not in get_templates():
        return "Unknown built-in site"
    checked = extract_valid_hostname(_clean_hostname(hostname), key)
    if not checked.get("domain"):
        return checked.get("message", "Invalid hostname").removeprefix("Error: ")
    Config("Hostnames").save(key, checked["domain"])
    clear_hostname_issue(key)
    try:
        record_configured_hostnames()
    except Exception:
        pass
    return None


def remove_site(key):
    from quasarr.search.sources.templates import get_templates
    from quasarr.storage.custom_sources import delete_definition

    key = str(key or "").lower()
    if key in get_templates():
        from quasarr.search.sources.templates import is_modified
        from quasarr.storage.template_overrides import delete_override

        # removing a changed built-in site restores its shipped template
        if is_modified(key):
            delete_override(key)
            return True
        Config("Hostnames").save(key, "")
        clear_hostname_issue(key)
        try:
            record_configured_hostnames()
        except Exception:
            pass
        return True
    return delete_definition(key)


def setup_site_routes(app, shared_state, onboarding=False):
    from quasarr.storage.setup.site_editor import setup_site_editor_routes

    setup_site_editor_routes(app, shared_state, onboarding)

    @app.get("/api/sites")
    @require_api_key
    def list_sites():
        response.content_type = "application/json"
        return {"success": True, **sites_overview(shared_state, onboarding)}

    @app.post("/api/sites/check")
    @require_api_key
    def check_sites():
        """Check pasted hostnames against the built-in sites; saves nothing."""
        response.content_type = "application/json"
        data = request.json or {}
        results = check_hostnames(shared_state, data.get("hostnames", ""))
        if not results:
            response.status = 400
            return {"success": False, "error": "Enter at least one hostname."}
        return {"success": True, "results": results}

    @app.put("/api/sites/<key>")
    @require_api_key
    def put_site(key):
        response.content_type = "application/json"
        error = add_builtin_site(key, (request.json or {}).get("hostname"))
        if error:
            response.status = 400
            return {"success": False, "error": error}
        return {"success": True}

    @app.delete("/api/sites/<key>")
    @require_api_key
    def delete_site(key):
        response.content_type = "application/json"
        if not remove_site(key):
            response.status = 404
            return {"success": False, "error": "Unknown site"}
        return {"success": True}

    if onboarding:

        @app.post("/api/sites/finish-setup")
        @require_api_key
        def finish_setup():
            response.content_type = "application/json"
            from quasarr.storage.config import get_clean_hostnames
            from quasarr.storage.custom_sources import get_custom_sources

            if not get_clean_hostnames(shared_state) and not get_custom_sources():
                response.status = 400
                return {"success": False, "error": "Add a site first."}
            quasarr.providers.web_server.temp_server_success = True
            return {"success": True}


def sites_page(shared_state, onboarding=False):
    config = {
        "onboarding": onboarding,
        "flags": FLAG_SVGS,
        "import_url": Config("Settings").get("hostnames_url") or "",
        "max": MAX_HOSTNAMES,
    }
    title = "Add your sites" if onboarding else "Sites"
    body = (
        '<script type="application/json" id="sites-config">'
        + json_for_script(config)
        + "</script>"
        + _PAGE_HTML.replace("{{BACK}}", "" if onboarding else _BACK_BUTTON)
    )
    return render_form(title, body, _PAGE_SCRIPT + _PAGE_STYLE)


_BACK_BUTTON = '<button type="button" class="btn-secondary" onclick="location.href=\'/\'">Back</button>'

_PAGE_HTML = """
<div class="sites" id="sites">
  <section class="sites-card" aria-labelledby="add-title">
    <h3 id="add-title">Add sites</h3>
    <p class="sites-lead">Paste the addresses of the sites you use, one per line. Quasarr checks which of them it
      already knows. Lines such as <code>xy = example.org</code> from community lists work too.</p>
    <label for="add-input" class="visually-hidden">Hostnames</label>
    <textarea id="add-input" rows="3" spellcheck="false" autocomplete="off" autocapitalize="off" autocorrect="off"
      placeholder="example.org"></textarea>
    <div class="sites-row">
      <button type="button" class="btn-primary" id="add-check">Check</button>
      <button type="button" class="btn-secondary" id="import-toggle" aria-expanded="false">Load a list from a URL</button>
    </div>
    <div id="import-box" hidden>
      <label for="import-url">Address of a hostname list</label>
      <div class="sites-row">
        <input id="import-url" type="url" autocapitalize="off" autocorrect="off" spellcheck="false" placeholder="https://…">
        <button type="button" class="btn-secondary" id="import-load">Load</button>
      </div>
    </div>
    <div id="check-results" aria-live="polite"></div>
  </section>

  <section class="sites-card" aria-labelledby="mine-title">
    <h3 id="mine-title">Your sites</h3>
    <div id="attention" aria-live="polite"></div>
    <ul class="site-list" id="site-list"></ul>
    <p class="sites-empty" id="sites-empty" hidden>No sites yet. Add one above.</p>
  </section>

  <details class="sites-card" id="catalog-box">
    <summary>All built-in sites</summary>
    <p class="hint">Quasarr ships support for these sites. Each needs its address, which Quasarr does not provide.</p>
    <div class="catalog" id="catalog"></div>
  </details>

  <p class="advanced">Is a site missing? <a href="/sources/custom">Set it up yourself</a> or import a template someone shared.
    This is meant for experienced users. Sites that need a login need Python code, contributed as a pull request.</p>

  <div class="sites-footer">
    {{BACK}}
    <button type="button" class="btn-primary" id="finish" hidden disabled>Continue</button>
  </div>
</div>
"""

SITES_CSS = """
  .inner:has(.sites) { max-width: min(860px, 96vw); }
  .sites { text-align: left; }
  .sites code { background: var(--code-bg); padding: 0 .3rem; border-radius: .25rem; }
  .sites-card { border: 1px solid var(--border-color); border-radius: .6rem; padding: 1rem; margin-bottom: 1rem; }
  .sites-card h3 { margin: 0 0 .5rem; }
  details.sites-card summary { cursor: pointer; font-weight: 600; }
  .sites-lead { margin-top: 0; }
  .sites textarea { width: 100%; box-sizing: border-box; padding: .5rem; font: inherit; font-family: ui-monospace, monospace;
    border: 1px solid var(--card-border); border-radius: .5rem; background: var(--card-bg); color: var(--fg-color); resize: vertical; }
  .sites-row { display: flex; gap: .5rem; flex-wrap: wrap; align-items: center; margin-top: .5rem; }
  .sites-row input { flex: 1 1 14rem; margin: 0; }
  .sites .hint { color: var(--text-muted); font-size: .85rem; }
  .visually-hidden { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); }
  .note { padding: .6rem .8rem; border-radius: .4rem; margin: .6rem 0; border: 1px solid var(--border-color); }
  .note.ok { background: var(--success-bg); border-color: var(--success-border); }
  .note.warn { background: #fff3cd; border-color: #ffe69c; color: #664d03; }
  .note.error { background: var(--error-bg); border-color: var(--error-border); }
  .note.busy { color: var(--text-muted); }
  .summary-line { font-weight: 600; margin: .75rem 0 .25rem; }
  .check-list, .site-list { list-style: none; margin: 0; padding: 0; }
  .check-item, .site { display: grid; grid-template-columns: auto minmax(0, 1fr) auto; gap: .25rem .6rem;
    align-items: start; padding: .65rem 0; border-bottom: 1px solid var(--divider-color); }
  .check-item:last-child, .site:last-child { border-bottom: 0; }
  .dot { width: .75rem; height: .75rem; border-radius: 50%; margin-top: .35rem; background: var(--secondary); }
  .dot.ok { background: var(--success-color); }
  .dot.warn { background: #f59f00; }
  .dot.error { background: var(--error-color); }
  .site-main { min-width: 0; }
  .site-title { font-weight: 600; }
  .site-host { display: inline-block; margin-left: .35rem; word-break: break-all; }
  .site-status { font-size: .875rem; color: var(--text-muted); margin-top: .15rem; }
  .site-status.warn { color: #b7791f; }
  .site-status.error { color: var(--error-color); }
  .chips { display: flex; flex-wrap: wrap; gap: .25rem; margin-top: .3rem; }
  .chip { font-size: .75rem; padding: .1rem .5rem; border-radius: .65rem; border: 1px solid rgba(108,117,125,.25);
    background: rgba(108,117,125,.08); white-space: nowrap; }
  .chip .flag svg { width: 1em; height: .75em; vertical-align: -.05em; }
  .chip.warn { background: #fff3cd; border-color: #d39e00; color: #856404; }
  .site-actions { display: flex; gap: .35rem; flex-wrap: wrap; justify-content: flex-end; align-items: flex-start; }
  .more { position: relative; }
  .more > summary { list-style: none; cursor: pointer; padding: .3rem .7rem; font-size: .85rem; border-radius: .4rem;
    border: 1px solid var(--card-border); color: var(--fg-color); }
  .more > summary::-webkit-details-marker { display: none; }
  .more-menu { position: absolute; right: 0; z-index: 5; width: min(16rem, 80vw); margin-top: .3rem; padding: .6rem;
    background: var(--card-bg); border: 1px solid var(--card-border); border-radius: .5rem; box-shadow: 0 6px 18px rgba(0,0,0,.25); }
  .more-menu .hint { margin: .4rem 0 0; }
  .site-actions button, .check-actions button { padding: .3rem .7rem; font-size: .85rem; margin: 0; }
  .check-actions { display: flex; gap: .35rem; flex-wrap: wrap; align-items: center; justify-content: flex-end; }
  .check-actions select { width: auto; padding: .3rem 1.8rem .3rem .5rem; background-position: right .5rem center;
    font-size: .85rem; margin: 0; }
  .check-actions label.check { display: inline-flex; align-items: center; gap: .3rem; margin: 0; white-space: nowrap; }
  .check-actions label.check input { width: auto; margin: 0; }
  .inline-form { grid-column: 2 / -1; display: flex; flex-wrap: wrap; gap: .5rem; align-items: center; margin-top: .4rem; }
  .inline-form input { flex: 1 1 10rem; margin: 0; }
  .inline-form .form-note { flex: 1 1 100%; font-size: .85rem; }
  .catalog { display: grid; grid-template-columns: repeat(auto-fill, minmax(15rem, 1fr)); gap: .5rem; margin-top: .5rem; }
  .catalog-item { border: 1px solid var(--divider-color); border-radius: .5rem; padding: .5rem .6rem; }
  .catalog-item.added { opacity: .65; }
  .status-modal.share-modal { max-width: min(820px, 94vw); text-align: left; }
  .share-modal pre { max-height: 55vh; overflow: auto; background: var(--code-bg); padding: .75rem;
    border-radius: .4rem; font-size: .8rem; white-space: pre; }
  .advanced { color: var(--text-muted); font-size: .9rem; }
  .sites-footer { display: flex; justify-content: flex-end; gap: .5rem; flex-wrap: wrap; margin-top: 1rem; }
  @media (max-width: 600px) {
    .check-item, .site { grid-template-columns: auto minmax(0, 1fr); }
    .site-actions, .check-actions { grid-column: 2; justify-content: flex-start; }
    .inline-form { grid-column: 1 / -1; }
    .sites-footer > button { flex: 1 1 auto; }
  }
"""
_PAGE_STYLE = f"<style>{SITES_CSS}</style>"

_PAGE_SCRIPT = r"""
<script>
(function() {
  'use strict';
  var config = JSON.parse(document.getElementById('sites-config').textContent);
  var state = {sites: [], catalog: []};
  var windows = /Windows/.test(navigator.userAgent);

/*UI_HELPERS*/
  function plural(count, one, many) { return count + ' ' + (count === 1 ? one : many); }
  function chips(about, extra, configured) {
    var list = el('div', {className: 'chips'});
    if (about.language) {
      var language = el('span', {className: 'chip'});
      // Windows draws no flag emoji; the SVGs are Quasarr's own constants
      var flag = windows && config.flags[about.lang] ? el('span', {className: 'flag'}) : null;
      if (flag) flag.innerHTML = config.flags[about.lang];
      language.appendChild(flag || document.createTextNode(about.flag ? about.flag + ' ' : ''));
      language.appendChild(document.createTextNode((flag ? ' ' : '') + about.language));
      list.appendChild(language);
    }
    (about.kinds || []).forEach(function(kind) { list.appendChild(el('span', {className: 'chip', text: kind})); });
    if (!configured && about.invite_only) list.appendChild(el('span', {className: 'chip warn', text: 'Invite only'}));
    if (configured) { /* the status line says what is missing */ }
    else if (about.needs_login) list.appendChild(el('span', {className: 'chip warn', text: 'Needs your login'}));
    else if (about.needs_account) list.appendChild(el('span', {className: 'chip warn', text: 'Needs an account'}));
    if (!configured && about.needs_flaresolverr) list.appendChild(el('span', {className: 'chip warn', text: 'Needs FlareSolverr'}));
    (extra || []).forEach(function(text) { list.appendChild(el('span', {className: 'chip', text: text})); });
    return list;
  }
  function setupLink(hostname) {
    return '/sources/custom?hostname=' + encodeURIComponent(hostname);
  }

  // --- your sites ----------------------------------------------------------
  function load() {
    return api('/api/sites').then(function(data) {
      if (!data.success) return;
      state.sites = data.sites;
      state.catalog = data.catalog;
      renderSites();
      renderCatalog();
    });
  }
  function renderSites() {
    var list = $('site-list');
    list.textContent = '';
    $('sites-empty').hidden = state.sites.length > 0;
    var attention = state.sites.filter(function(site) { return site.state !== 'ok'; });
    $('attention').textContent = '';
    if (attention.length) {
      note($('attention'), 'warn', plural(attention.length, 'site needs', 'sites need') + ' your attention.');
    }
    state.sites.forEach(function(site) { list.appendChild(siteRow(site)); });
    var finish = $('finish');
    if (config.onboarding) {
      finish.hidden = false;
      finish.disabled = !state.sites.length;
    }
  }
  function siteRow(site) {
    var row = el('li', {className: 'site'});
    var actions = el('div', {className: 'site-actions'});
    var title = el('div', {}, [
      el('span', {className: 'site-title', text: site.name}),
      el('code', {className: 'site-host', text: site.hostname})
    ]);
    var main = el('div', {className: 'site-main'}, [
      title,
      el('div', {className: 'site-status ' + site.state, text: site.status}),
      chips(site, site.kind === 'custom' ? ['Set up by you'] : [], true)
    ]);
    if (site.modified) {
      var changed = el('span', {className: 'chip warn', text: 'Changed by you',
        title: 'Issues about a changed site are not supported. Reset it before you report a problem.'});
      main.querySelector('.chips').appendChild(changed);
      main.querySelector('.site-status').textContent = site.status + '. Changed by you: issues about it are not supported.';
    }
    row.appendChild(el('span', {className: 'dot ' + site.state, 'aria-hidden': 'true'}));
    row.appendChild(main);
    row.appendChild(actions);
    if (site.kind === 'builtin') {
      if (site.needs_login) {
        actions.appendChild(el('button', {type: 'button', className: site.login_user ? 'btn-secondary' : 'btn-primary',
          text: site.login_user ? 'Login' : 'Log in', onclick: function() { loginForm(row, site); }}));
      }
      actions.appendChild(el('button', {type: 'button', className: 'btn-secondary', text: 'Address',
        onclick: function() { addressForm(row, site); }}));
      if (site.modified) {
        actions.appendChild(el('button', {type: 'button', className: 'btn-secondary', text: 'Reset',
          onclick: function(event) { resetTemplate(site, event.currentTarget); }}));
      }
    } else {
      actions.appendChild(el('button', {type: 'button', className: 'btn-secondary', text: 'Edit',
        onclick: function() { window.location.href = '/sources/custom/' + encodeURIComponent(site.key.toLowerCase()); }}));
      actions.appendChild(el('button', {type: 'button', className: 'btn-secondary', text: 'Share',
        onclick: function(event) { share(site, event.currentTarget); }}));
    }
    // a changed built-in site is reset to the shipped version, not removed
    if (!site.modified) {
      actions.appendChild(el('button', {type: 'button', className: 'btn-secondary', text: 'Remove',
        onclick: function() { remove(site); }}));
    }
    // the template editor is for advanced users only, so it hides behind More
    if (site.kind === 'builtin') {
      var menu = el('div', {className: 'more-menu'}, [
        el('button', {type: 'button', className: 'btn-secondary', text: site.modified ? 'Edit your changes' : 'Change its template',
          onclick: function() { window.location.href = '/sites/edit/' + encodeURIComponent(site.key.toLowerCase()); }}),
        el('p', {className: 'hint', text: 'For experienced users, when the site changed and an update is not out yet. ' +
          'Issues about a changed site are not supported.'})
      ]);
      actions.appendChild(el('details', {className: 'more'}, [el('summary', {text: 'More'}), menu]));
    }
    if (site.needs_login && !site.login_user && site.kind === 'builtin') loginForm(row, site);
    return row;
  }
  function resetTemplate(site, button) {
    if (!confirm('Reset ' + site.name + ' to the shipped version? Your changes to its template are deleted.')) return;
    var done = busy(button, 'Resetting…');
    api('/api/sites/' + encodeURIComponent(site.key.toLowerCase()) + '/template', undefined, 'DELETE').then(function(data) {
      done();
      if (data.success) load(); else alert(data.error);
    });
  }
  function closeForms(row) { row.querySelectorAll('.inline-form').forEach(function(form) { form.remove(); }); }
  function loginForm(row, site) {
    closeForms(row);
    var user = el('input', {type: 'text', autocomplete: 'username', placeholder: 'Username', 'aria-label': site.name + ' username'});
    user.value = site.login_user || '';
    var password = el('input', {type: 'password', autocomplete: 'current-password', placeholder: 'Password', 'aria-label': site.name + ' password'});
    var save = el('button', {type: 'submit', className: 'btn-primary', text: 'Save login'});
    var message = el('div', {className: 'form-note', 'aria-live': 'polite'});
    var form = el('form', {className: 'inline-form'}, [user, password, save, message]);
    form.onsubmit = function(event) {
      event.preventDefault();
      message.textContent = '';
      var done = busy(save, 'Checking…');
      api('/api/hostnames/check-credentials/' + encodeURIComponent(site.key.toLowerCase()),
        {user: user.value.trim(), password: password.value}).then(function(data) {
        done();
        if (data.success) { load(); }
        else { message.textContent = data.message || data.error || 'The login did not work.'; }
      });
    };
    row.appendChild(form);
    (user.value ? password : user).focus();
  }
  function addressForm(row, site) {
    closeForms(row);
    var input = el('input', {type: 'text', autocapitalize: 'off', autocorrect: 'off', spellcheck: 'false', 'aria-label': site.name + ' address'});
    input.value = site.hostname;
    var save = el('button', {type: 'submit', className: 'btn-primary', text: 'Save'});
    var cancel = el('button', {type: 'button', className: 'btn-secondary', text: 'Cancel', onclick: function() { form.remove(); }});
    var message = el('div', {className: 'form-note', 'aria-live': 'polite'});
    var form = el('form', {className: 'inline-form'}, [input, save, cancel, message]);
    form.onsubmit = function(event) {
      event.preventDefault();
      var done = busy(save, 'Saving…');
      api('/api/sites/' + encodeURIComponent(site.key.toLowerCase()), {hostname: input.value}, 'PUT').then(function(data) {
        done();
        if (data.success) load(); else message.textContent = data.error;
      });
    };
    row.appendChild(form);
    input.focus();
    input.select();
  }
  function remove(site) {
    var question = site.kind === 'custom'
      ? 'Remove ' + site.name + '? Its setup is deleted. Releases already sent to your apps still download.'
      : 'Remove ' + site.name + ' (' + site.hostname + ')? Releases already sent to your apps still download.';
    if (!confirm(question)) return;
    api('/api/sites/' + encodeURIComponent(site.key.toLowerCase()), undefined, 'DELETE').then(function(data) {
      if (data.success) load(); else alert(data.error);
    });
  }
  function share(site, button) {
    var done = busy(button, 'Checking…');
    api('/api/custom-sources/' + encodeURIComponent(site.key.toLowerCase()) + '/export').then(function(data) {
      done();
      showModal('Share as a template', '', null);
      document.querySelector('#global-modal-overlay .status-modal').classList.add('share-modal');
      var content = document.getElementById('global-modal-content');
      content.textContent = '';
      if (data.success) {
        content.appendChild(el('p', {text: 'Your site as a template, without its hostname. Others can import it in their own setup under Set it up yourself.'}));
        content.appendChild(el('p', {text: 'If it runs stable for you, please share it with the community: save it as a new file in quasarr/search/sources/templates/, named after a free two-letter key such as xy.py, and open a pull request. Then everyone gets the site built in.'}));
        content.appendChild(el('pre', {text: data.module}));
        var copy = el('button', {type: 'button', className: 'btn-primary', text: 'Copy'});
        copy.onclick = function() { navigator.clipboard.writeText(data.module).then(function() { copy.textContent = 'Copied'; }); };
        var buttons = document.getElementById('global-modal-buttons');
        buttons.insertBefore(copy, buttons.firstChild);
      } else {
        content.appendChild(el('p', {text: 'Sharing needs a working feed and search. Quasarr found:'}));
        content.appendChild(el('ul', {}, (data.problems || [data.error || 'The check failed.']).map(function(problem) {
          return el('li', {text: problem});
        })));
      }
    });
  }

  // --- checking pasted hostnames --------------------------------------------
  function check(text) {
    var results = $('check-results');
    results.textContent = '';
    if (!text.trim()) { note(results, 'error', 'Paste at least one hostname.'); $('add-input').focus(); return; }
    var done = busy($('add-check'), 'Checking…');
    var waiting = note(results, 'busy', 'Quasarr opens each site to see which built-in template matches it. This takes a few seconds per site.');
    api('/api/sites/check', {hostnames: text}).then(function(data) {
      done();
      waiting.remove();
      if (!data.success) { note(results, 'error', data.error); return; }
      renderResults(data.results);
    });
  }
  function choiceFor(result) {
    if (result.named) return {key: result.named, sure: true};
    if (result.verified.length) return {key: result.verified[0].key, sure: true};
    if (result.possible.length === 1) return {key: result.possible[0].key, sure: false};
    return null;
  }
  function renderResults(results) {
    var target = $('check-results');
    var addable = [];
    var counts = {match: 0, unsure: 0, setup: 0, skipped: 0};
    var list = el('ul', {className: 'check-list'});
    results.forEach(function(result) {
      var item = el('li', {className: 'check-item'});
      var main = el('div', {className: 'site-main'}, [el('code', {className: 'site-title', text: result.hostname})]);
      var actions = el('div', {className: 'check-actions'});
      var dot = 'dot';
      var text;
      if (result.blocked) {
        dot += ' error'; text = result.blocked.charAt(0).toUpperCase() + result.blocked.slice(1) + '.'; counts.skipped++;
      } else if (result.added_as) {
        dot += ' ok'; text = 'Already added as ' + result.added_as + '.'; counts.skipped++;
      } else {
        var options = result.verified.concat(result.possible);
        var choice = choiceFor(result);
        if (result.named_error) text = result.named_error + '. ';
        if (choice) {
          var picked = options.filter(function(option) { return option.key === choice.key; })[0] || {key: choice.key};
          dot += choice.sure ? ' ok' : ' warn';
          counts[choice.sure ? 'match' : 'unsure']++;
          text = (text || '') + (picked.rows
            ? 'The ' + picked.key + ' template matches: it read ' + plural(picked.rows, 'release', 'releases') + '.'
            : (result.named ? 'Your list names it ' + result.named + '.' : 'The ' + picked.key + ' template fits its name, but Quasarr could not confirm it from the page.'));
          var select = el('select', {'aria-label': 'Built-in site for ' + result.hostname});
          options.forEach(function(option) { select.appendChild(el('option', {value: option.key, text: option.key})); });
          if (!options.length) select.appendChild(el('option', {value: picked.key, text: picked.key}));
          select.value = picked.key;
          var include = el('input', {type: 'checkbox', 'aria-label': 'Add ' + result.hostname});
          // a fit by name alone is weak evidence, so only a confirmed match starts selected
          include.checked = choice.sure;
          actions.appendChild(el('label', {className: 'check'}, [include, ' Add as ']));
          actions.appendChild(select);
          actions.appendChild(el('button', {type: 'button', className: 'btn-secondary', text: 'Set it up yourself',
            onclick: function() { window.location.href = setupLink(result.hostname); }}));
          actions.appendChild(el('button', {type: 'button', className: 'btn-secondary', text: 'Skip',
            onclick: function() {
              include.checked = false;
              include.dispatchEvent(new Event('change'));
              item.remove();
            }}));
          addable.push({hostname: result.hostname, select: select, include: include, item: item});
          main.appendChild(chips(picked));
        } else {
          dot += ' warn'; counts.setup++;
          text = (text || '') + (result.unreachable
            ? 'Quasarr could not open it (' + result.unreachable + ').'
            : 'No built-in template matches it.');
          actions.appendChild(el('button', {type: 'button', className: 'btn-secondary', text: 'Set it up yourself',
            onclick: function() { window.location.href = setupLink(result.hostname); }}));
          if (result.possible.length) {
            // the name rule alone is weak evidence, so nothing is preselected
            var chooser = el('select', {'aria-label': 'Built-in site for ' + result.hostname});
            chooser.appendChild(el('option', {value: '', text: 'or use a built-in site…'}));
            result.possible.forEach(function(option) { chooser.appendChild(el('option', {value: option.key, text: option.key})); });
            var box = el('input', {type: 'checkbox', hidden: 'hidden'});
            chooser.onchange = function() { box.checked = !!chooser.value; };
            actions.appendChild(chooser);
            addable.push({hostname: result.hostname, select: chooser, include: box, item: item});
          }
        }
      }
      main.appendChild(el('div', {className: 'site-status', text: text}));
      item.appendChild(el('span', {className: dot, 'aria-hidden': 'true'}));
      item.appendChild(main);
      item.appendChild(actions);
      list.appendChild(item);
    });
    var parts = [];
    if (counts.match) parts.push(plural(counts.match, 'site matches', 'sites match') + ' a built-in template');
    if (counts.unsure) parts.push(plural(counts.unsure, 'needs', 'need') + ' you to confirm the site');
    if (counts.setup) parts.push(plural(counts.setup, 'needs', 'need') + ' your own setup');
    if (counts.skipped) parts.push(plural(counts.skipped, 'is', 'are') + ' already added or not usable');
    target.appendChild(el('p', {className: 'summary-line', text: (parts.join(', ') || 'Nothing to add') + '.'}));
    target.appendChild(list);
    if (addable.length) {
      var addAll = el('button', {type: 'button', className: 'btn-primary', text: 'Add selected sites'});
      addAll.onclick = function() { addSelected(addable, addAll); };
      var refresh = function() {
        addAll.disabled = !addable.some(function(entry) { return entry.include.checked && entry.select.value; });
      };
      addable.forEach(function(entry) {
        entry.select.addEventListener('change', refresh);
        entry.include.addEventListener('change', refresh);
      });
      refresh();
      target.appendChild(el('div', {className: 'sites-row'}, [addAll]));
    }
    if (counts.setup) {
      note(target, 'warn', [
        el('strong', {text: 'No built-in template matches ' + (counts.setup === 1 ? 'one site' : counts.setup + ' sites') + '. '}),
        'You can teach Quasarr to read it yourself: the guided setup opens the site with you, you click where its releases, ' +
        'its search and its download links are, and every step is tested before you save. A site you set up is yours to maintain, ' +
        'and issues about it are not supported. Sites that need a login cannot be set up this way: they need Python code, ' +
        'contributed as a pull request.'
      ]);
    }
  }
  function addSelected(addable, button) {
    var chosen = addable.filter(function(entry) { return entry.include.checked && entry.select.value; });
    if (!chosen.length) return;
    var done = busy(button, 'Adding…');
    Promise.all(chosen.map(function(entry) {
      return api('/api/sites/' + encodeURIComponent(entry.select.value.toLowerCase()), {hostname: entry.hostname}, 'PUT')
        .then(function(data) { return {entry: entry, data: data}; });
    })).then(function(outcomes) {
      done();
      var failed = outcomes.filter(function(outcome) { return !outcome.data.success; });
      outcomes.forEach(function(outcome) {
        var status = outcome.entry.item.querySelector('.site-status');
        if (outcome.data.success) {
          outcome.entry.item.querySelector('.check-actions').textContent = '';
          status.textContent = 'Added as ' + outcome.entry.select.value + '.';
        } else {
          status.textContent = 'Not added: ' + outcome.data.error + '.';
        }
      });
      button.remove();
      if (!failed.length) $('add-input').value = '';
      load();
    });
  }

  $('add-check').onclick = function() { check($('add-input').value); };
  $('add-input').addEventListener('keydown', function(event) {
    if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) { event.preventDefault(); check($('add-input').value); }
  });
  $('import-toggle').onclick = function() {
    var box = $('import-box');
    box.hidden = !box.hidden;
    $('import-toggle').setAttribute('aria-expanded', String(!box.hidden));
    if (!box.hidden) $('import-url').focus();
  };
  $('import-url').value = config.import_url;
  $('import-load').onclick = function() {
    var results = $('check-results');
    results.textContent = '';
    var done = busy($('import-load'), 'Loading…');
    api('/api/hostnames/import-url', {url: $('import-url').value.trim()}).then(function(data) {
      done();
      if (!data.success) { note(results, 'error', data.error); return; }
      var lines = Object.keys(data.hostnames).map(function(key) { return key + ' = ' + data.hostnames[key]; });
      $('add-input').value = lines.join('\n');
      check($('add-input').value);
    });
  };

  // --- catalog --------------------------------------------------------------
  function renderCatalog() {
    var grid = $('catalog');
    grid.textContent = '';
    state.catalog.forEach(function(entry) {
      grid.appendChild(el('div', {className: 'catalog-item' + (entry.added ? ' added' : '')}, [
        el('div', {className: 'site-title', text: entry.key + (entry.added ? ' · added' : '')}),
        chips(entry)
      ]));
    });
  }

  // --- onboarding ------------------------------------------------------------
  $('finish').onclick = function() {
    var button = $('finish');
    var done = busy(button, 'Starting…');
    api('/api/sites/finish-setup', {}).then(function(data) {
      if (!data.success) { done(); alert(data.error); return; }
      button.textContent = 'Quasarr is starting…';
      (function wait(attempt) {
        setTimeout(function() {
          fetch('/', {method: 'HEAD', cache: 'no-store'}).then(function(response) {
            if (response.ok) window.location.href = '/'; else wait(attempt + 1);
          }).catch(function() { wait(attempt + 1); });
        }, attempt ? 1000 : 2500);
      })(0);
    });
  };

  // an open More menu closes when the page is clicked elsewhere
  document.addEventListener('click', function(event) {
    document.querySelectorAll('details.more[open]').forEach(function(menu) {
      if (!menu.contains(event.target)) menu.open = false;
    });
  });
  load();
  $('add-input').focus();
})();
</script>
"""

# helpers both site pages share; each page script marks their place
UI_HELPERS_JS = r"""
  function $(id) { return document.getElementById(id); }
  function el(tag, props, children) {
    var node = document.createElement(tag);
    Object.keys(props || {}).forEach(function(key) {
      var value = props[key];
      if (key === 'text') node.textContent = value;
      else if (key === 'className') node.className = value;
      else if (key.slice(0, 2) === 'on') node.addEventListener(key.slice(2), value);
      else node.setAttribute(key, value);
    });
    (children || []).forEach(function(child) {
      if (child) node.appendChild(typeof child === 'string' ? document.createTextNode(child) : child);
    });
    return node;
  }
  function note(target, kind, parts) {
    var box = el('div', {className: 'note ' + kind, role: kind === 'error' ? 'alert' : 'status'},
      Array.isArray(parts) ? parts : [parts]);
    target.appendChild(box);
    return box;
  }
  function api(path, body, method) {
    return quasarrApiFetch(path, {
      method: method || (body === undefined ? 'GET' : 'POST'),
      headers: {'Content-Type': 'application/json'},
      body: body === undefined ? undefined : JSON.stringify(body)
    }).then(function(response) {
      return response.json().catch(function() { return {success: false, error: 'Quasarr answered with HTTP ' + response.status}; });
    }).catch(function() { return {success: false, error: 'Quasarr did not answer'}; });
  }
  function busy(button, text) {
    var original = button.textContent;
    button.disabled = true;
    button.textContent = text;
    return function() { button.disabled = false; button.textContent = original; };
  }
"""
_PAGE_SCRIPT = _PAGE_SCRIPT.replace("/*UI_HELPERS*/\n", UI_HELPERS_JS)
