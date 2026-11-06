# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

"""Editing built-in sites: their template as JSON, tested live, saved apart.

Changes lay over the shipped template (see ``storage.template_overrides``);
resetting deletes them. A changed site is the user's to maintain, so the page
says that issues about it are not supported.
"""

import time

from bottle import abort, request, response

from quasarr.providers.auth import require_api_key
from quasarr.providers.html_templates import json_for_script, render_form
from quasarr.providers.log import info
from quasarr.storage.config import Config
from quasarr.storage.setup.sites import CATEGORY_LABELS, SITES_CSS, UI_HELPERS_JS

_STEP_NAMES = {"feed": "newest releases", "search": "search", "download": "downloads"}


def _template_key(key):
    from quasarr.search.sources.templates import get_template_keys

    key = str(key or "").lower()
    return key if key in get_template_keys() else None


def template_state(key):
    """Shipped and current editable parts of one built-in site."""
    from quasarr.search.sources.templates import get_templates, shipped_definition
    from quasarr.storage.template_overrides import EDITABLE_PARTS, load_overrides

    shipped = shipped_definition(key)
    editable = {part: shipped[part] for part in EDITABLE_PARTS if part in shipped}
    changes = load_overrides().get(key) or {}
    source = get_templates()[key]
    return {
        "key": key.upper(),
        "shipped": editable,
        "current": {**editable, **changes},
        "modified": bool(changes),
        "code_steps": [
            _STEP_NAMES[point]
            for point in shipped.get("hooks", {})
            if point in _STEP_NAMES
        ],
        "parts": list(EDITABLE_PARTS),
        "categories": [
            {"id": cat, "name": label}
            for cat, label in CATEGORY_LABELS
            if cat in source.supported_categories
        ],
        "hostname": str(Config("Hostnames").get(key) or ""),
    }


def _changed_parts(key, current):
    """Only the parts that differ from the shipped template count as changes."""
    from quasarr.search.sources.templates import shipped_definition

    if not isinstance(current, dict):
        raise ValueError("The template must be a JSON object")
    shipped = shipped_definition(key)
    # a part the shipped template leaves out stays unchanged while it is empty
    return {
        part: value
        for part, value in current.items()
        if shipped.get(part) != value and (part in shipped or value)
    }


def _release_rows(releases):
    rows = []
    for release in releases[:25]:
        details = release.get("details") or {}
        rows.append(
            {
                "title": str(details.get("title") or ""),
                "size": round((details.get("size") or 0) / 1024 / 1024),
                "date": str(details.get("date") or ""),
                "imdb": str(details.get("imdb_id") or ""),
                "source": str(details.get("source") or ""),
            }
        )
    return rows


def test_template(shared_state, key, current, step, category=None, query="", url=""):
    """Run one step of a built-in site with unsaved changes; saves nothing."""
    from quasarr.search.sources.templates import build_template

    source = build_template(key, _changed_parts(key, current))
    if not source.hostname:
        return {"success": False, "error": "Add the site's address first"}
    if step == "download":
        if not str(url or "").startswith("http"):
            return {"success": False, "error": "Enter the address of a release page"}
        result = source.get_download_links(shared_state, url, [], "", "") or {}
        links = [[str(link[0]), str(link[1])] for link in result.get("links") or []]
        return {"success": True, "links": links[:50], "count": len(links)}
    category = int(category or 0)
    if category not in source.supported_categories:
        return {"success": False, "error": "Choose a kind of release"}
    started = time.time()
    if step == "feed":
        releases = source.feed(shared_state, started, category)
    elif step == "search":
        if not str(query or "").strip():
            return {"success": False, "error": "Enter a title or an IMDb ID"}
        releases = source.search(shared_state, started, category, query.strip())
    else:
        return {"success": False, "error": "Unknown step"}
    return {
        "success": True,
        "rows": _release_rows(releases or []),
        "count": len(releases or []),
        "seconds": round(time.time() - started, 1),
    }


def setup_site_editor_routes(app, shared_state, onboarding=False):
    @app.get("/sites/edit/<key>")
    def edit_builtin_site(key):
        key = _template_key(key)
        if not key:
            abort(404, "Unknown built-in site")
        return builtin_editor_page(key, onboarding)

    @app.get("/api/sites/<key>/template")
    @require_api_key
    def get_site_template(key):
        response.content_type = "application/json"
        key = _template_key(key)
        if not key:
            response.status = 404
            return {"success": False, "error": "Unknown built-in site"}
        return {"success": True, **template_state(key)}

    @app.put("/api/sites/<key>/template")
    @require_api_key
    def save_site_template(key):
        from quasarr.storage.template_overrides import delete_override, save_override

        response.content_type = "application/json"
        key = _template_key(key)
        if not key:
            response.status = 404
            return {"success": False, "error": "Unknown built-in site"}
        try:
            changes = _changed_parts(key, (request.json or {}).get("template"))
            if changes:
                save_override(key, changes)
            else:
                delete_override(key)
        except Exception as e:
            response.status = 400
            return {"success": False, "error": str(e)}
        info(
            f"{key.upper()} now runs your changes to its built-in template"
            if changes
            else f"{key.upper()} runs its shipped template again"
        )
        return {"success": True, **template_state(key)}

    @app.delete("/api/sites/<key>/template")
    @require_api_key
    def reset_site_template(key):
        from quasarr.storage.template_overrides import delete_override

        response.content_type = "application/json"
        key = _template_key(key)
        if not key:
            response.status = 404
            return {"success": False, "error": "Unknown built-in site"}
        if delete_override(key):
            info(f"{key.upper()} runs its shipped template again")
        return {"success": True, **template_state(key)}

    @app.post("/api/sites/<key>/template/test")
    @require_api_key
    def test_site_template(key):
        response.content_type = "application/json"
        key = _template_key(key)
        if not key:
            response.status = 404
            return {"success": False, "error": "Unknown built-in site"}
        data = request.json or {}
        try:
            return test_template(
                shared_state,
                key,
                data.get("template"),
                data.get("step"),
                data.get("category"),
                str(data.get("query") or ""),
                str(data.get("url") or ""),
            )
        except Exception as e:
            return {"success": False, "error": str(e)}


def builtin_editor_page(key, onboarding=False):
    config = {"key": key.upper(), "sites_url": "/" if onboarding else "/hostnames"}
    body = (
        '<script type="application/json" id="editor-config">'
        + json_for_script(config)
        + "</script>"
        + _EDITOR_HTML
    )
    return render_form(f"Edit {key.upper()}", body, _EDITOR_SCRIPT + _EDITOR_STYLE)


_EDITOR_HTML = """
<div class="sites editor" id="editor">
  <p class="sites-lead" id="ed-lead">Loading…</p>
  <div class="note warn" id="ed-support">A changed site is yours to maintain. Issues about it are not supported:
    reset it to the shipped version and check again before you report a problem.</div>
  <div id="ed-code"></div>

  <section class="sites-card" aria-labelledby="ed-template-title">
    <div class="ed-head">
      <h3 id="ed-template-title">Template</h3>
      <span class="chip warn" id="ed-modified" hidden>Changed by you</span>
      <span class="chip" id="ed-dirty" hidden>Unsaved changes</span>
    </div>
    <p class="hint">The parts Quasarr lets you change, as JSON, in the format of
      <a href="https://github.com/rix1337/Quasarr#sites-without-a-matching-template" target="_blank" rel="noopener noreferrer">sites you set up yourself</a>.</p>
    <label for="ed-json" class="visually-hidden">Template</label>
    <textarea id="ed-json" rows="22" spellcheck="false" autocomplete="off" autocapitalize="off" autocorrect="off"></textarea>
    <div id="ed-json-error" aria-live="polite"></div>
    <div class="sites-row">
      <button type="button" class="btn-secondary" id="ed-format">Format</button>
      <button type="button" class="btn-secondary" id="ed-shipped" aria-expanded="false">Show shipped version</button>
    </div>
    <pre class="ed-shipped" id="ed-shipped-view" hidden></pre>
  </section>

  <section class="sites-card" aria-labelledby="ed-test-title">
    <h3 id="ed-test-title">Test before saving</h3>
    <p class="hint">Tests run your unsaved template against the live site. Nothing is saved or sent to your apps.</p>
    <div class="ed-test">
      <span class="ed-test-label">Newest releases</span>
      <select id="ed-feed-cat" aria-label="Kind of release for the newest releases"></select>
      <button type="button" class="btn-secondary" id="ed-feed-test">Test</button>
    </div>
    <div class="ed-test">
      <span class="ed-test-label">Search</span>
      <input id="ed-query" type="text" autocapitalize="off" autocorrect="off" spellcheck="false" placeholder="tt0499549" aria-label="Search for">
      <select id="ed-search-cat" aria-label="Kind of release for the search"></select>
      <button type="button" class="btn-secondary" id="ed-imdb">Grab IMDb ID</button>
      <button type="button" class="btn-secondary" id="ed-search-test">Test</button>
    </div>
    <p class="hint" id="ed-imdb-name" aria-live="polite"></p>
    <div class="ed-test">
      <span class="ed-test-label">Downloads</span>
      <input id="ed-url" type="url" autocapitalize="off" autocorrect="off" spellcheck="false" placeholder="Address of a release page" aria-label="Release page address">
      <button type="button" class="btn-secondary" id="ed-download-test">Test</button>
    </div>
    <div id="ed-results" aria-live="polite"></div>
  </section>

  <div id="ed-notes" aria-live="polite"></div>
  <div class="sites-footer">
    <button type="button" class="btn-secondary" id="ed-back">Back to your sites</button>
    <button type="button" class="btn-secondary" id="ed-reset" hidden>Reset to shipped</button>
    <button type="button" class="btn-primary" id="ed-save">Save</button>
  </div>
</div>
"""

_EDITOR_STYLE = (
    "<style>"
    + SITES_CSS
    + """
  .editor textarea { min-height: 18rem; font-size: .85rem; line-height: 1.35; tab-size: 2; }
  .ed-head { display: flex; align-items: center; gap: .5rem; flex-wrap: wrap; margin-bottom: .25rem; }
  .ed-head h3 { margin: 0; }
  .ed-shipped { max-height: 24rem; overflow: auto; background: var(--code-bg); padding: .75rem;
    border-radius: .4rem; font-size: .8rem; white-space: pre; }
  .ed-test { display: flex; gap: .5rem; flex-wrap: wrap; align-items: center; margin: .5rem 0; }
  .ed-test-label { flex: 0 0 9rem; font-weight: 600; }
  .ed-test input { flex: 1 1 12rem; margin: 0; }
  .ed-test select { width: auto; margin: 0; }
  .ed-table { width: 100%; border-collapse: collapse; font-size: .85rem; table-layout: fixed; }
  .ed-table th, .ed-table td { text-align: left; padding: .3rem .4rem; border-bottom: 1px solid var(--divider-color);
    overflow-wrap: anywhere; vertical-align: top; }
  .ed-table th:nth-child(2), .ed-table td:nth-child(2) { width: 5.5rem; }
  @media (max-width: 600px) {
    .ed-test-label { flex-basis: 100%; }
    .ed-table th:nth-child(3), .ed-table td:nth-child(3) { display: none; }
  }
</style>
"""
)

_EDITOR_SCRIPT = r"""
<script>
(function() {
  'use strict';
  var config = JSON.parse(document.getElementById('editor-config').textContent);
  var key = config.key.toLowerCase();
  var state = null;
  var saved = '';
/*UI_HELPERS*/
  function pretty(value) { return JSON.stringify(value, null, 2); }
  function parsed() {
    $('ed-json-error').textContent = '';
    try {
      var value = JSON.parse($('ed-json').value);
      if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('The template must be a JSON object.');
      return value;
    } catch (e) {
      note($('ed-json-error'), 'error', 'Not valid JSON: ' + e.message);
      $('ed-json').focus();
      return null;
    }
  }
  function markDirty() { $('ed-dirty').hidden = $('ed-json').value === saved; }

  function render(data) {
    state = data;
    saved = pretty(data.current);
    $('ed-json').value = saved;
    $('ed-shipped-view').textContent = pretty(data.shipped);
    $('ed-modified').hidden = !data.modified;
    $('ed-reset').hidden = !data.modified;
    markDirty();
    $('ed-lead').textContent = data.key + ' ships with Quasarr' + (data.hostname ? ' and reads ' + data.hostname : '') +
      '. Change it here when the site moved something and you do not want to wait for an update.';
    var code = $('ed-code');
    code.textContent = '';
    if (data.code_steps.length) {
      var steps = data.code_steps.length > 1
        ? data.code_steps.slice(0, -1).join(', ') + ' and ' + data.code_steps[data.code_steps.length - 1]
        : data.code_steps[0];
      note(code, 'ok', 'Quasarr\'s own code handles ' + steps +
        ' for ' + data.key + '. You can change the addresses it requests under urls; the rest of that logic is not editable.');
    }
    [$('ed-feed-cat'), $('ed-search-cat')].forEach(function(select) {
      var current = select.value;
      select.textContent = '';
      data.categories.forEach(function(category) { select.appendChild(el('option', {value: category.id, text: category.name})); });
      if (current) select.value = current;
    });
    searchHint();
  }
  function load() {
    api('/api/sites/' + encodeURIComponent(key) + '/template').then(function(data) {
      if (!data.success) { $('ed-lead').textContent = data.error || 'Could not load the template.'; return; }
      render(data);
    });
  }

  // --- tests --------------------------------------------------------------------
  function showResult(data, label) {
    var target = $('ed-results');
    target.textContent = '';
    if (!data.success) { note(target, 'error', label + ': ' + (data.error || 'the test failed') + '.'); return; }
    if (data.links) {
      note(target, data.count ? 'ok' : 'warn', label + ': ' + data.count + (data.count === 1 ? ' link' : ' links') + ' found.');
      if (!data.count) return;
      var linkTable = el('table', {className: 'ed-table'}, [el('thead', {}, [el('tr', {}, [el('th', {text: 'Address'}), el('th', {text: 'Mirror'})])])]);
      var linkBody = el('tbody');
      data.links.forEach(function(link) { linkBody.appendChild(el('tr', {}, [el('td', {text: link[0]}), el('td', {text: link[1]})])); });
      linkTable.appendChild(linkBody);
      target.appendChild(linkTable);
      return;
    }
    note(target, data.count ? 'ok' : 'warn', label + ': ' + data.count + (data.count === 1 ? ' release' : ' releases') +
      ' in ' + data.seconds + ' s' + (data.count > data.rows.length ? ', the first ' + data.rows.length + ' shown.' : '.'));
    if (!data.count) return;
    var table = el('table', {className: 'ed-table'}, [el('thead', {}, [el('tr', {}, [
      el('th', {text: 'Name'}), el('th', {text: 'Size'}), el('th', {text: 'Date'})])])]);
    var body = el('tbody');
    data.rows.forEach(function(row) {
      body.appendChild(el('tr', {}, [el('td', {text: row.title}), el('td', {text: row.size ? row.size + ' MB' : '–'}), el('td', {text: row.date})]));
    });
    table.appendChild(body);
    target.appendChild(table);
  }
  function runTest(button, step, extra, label) {
    var template = parsed();
    if (!template) return;
    var done = busy(button, 'Testing…');
    $('ed-results').textContent = '';
    note($('ed-results'), 'busy', 'Asking the site. Searches can take up to a minute.');
    api('/api/sites/' + encodeURIComponent(key) + '/template/test', Object.assign({template: template, step: step}, extra))
      .then(function(data) { done(); showResult(data, label); });
  }
  $('ed-feed-test').onclick = function() { runTest(this, 'feed', {category: $('ed-feed-cat').value}, 'Newest releases'); };
  // movies and shows arrive as IMDb IDs from Radarr and Sonarr, so a typed title is looked up first
  function videoKind() { var id = Number($('ed-search-cat').value); return id >= 2000 && id < 3000 ? 'movie' : id >= 5000 && id < 6000 ? 'tv' : ''; }
  // a site searched by title gets the title; only IMDb sites need the ID
  function byTitle() { var search = state && state.current && state.current.search; return !!search && search.mode === 'title'; }
  function needsImdb() { return !!videoKind() && !byTitle(); }
  function grabImdb(button, then) {
    var term = $('ed-query').value.trim();
    var kind = videoKind();
    if (!term || !needsImdb() || /^tt\d{5,10}$/.test(term)) { if (then) then(); return; }
    var done = busy(button, 'Grabbing…');
    api('/api/custom-sources/imdb-lookup', {term: term, kind: kind}).then(function(data) {
      done();
      var hit = data.success && data.results[0];
      if (!hit) {
        $('ed-imdb-name').textContent = data.success ? 'No IMDb ID found for “' + term + '”; searching for the title as typed.' : data.error + '.';
      } else {
        $('ed-query').value = hit.imdb_id;
        $('ed-imdb-name').textContent = hit.imdb_id + ' is ' + hit.title + (hit.year ? ' (' + hit.year + ')' : '') + '.';
      }
      if (then) then();
    });
  }
  $('ed-imdb').onclick = function() {
    if (!$('ed-query').value.trim()) { $('ed-query').focus(); return; }
    grabImdb(this);
  };
  $('ed-search-test').onclick = function() {
    if (!$('ed-query').value.trim()) { $('ed-query').focus(); return; }
    var button = this;
    grabImdb(button, function() {
      runTest(button, 'search', {category: $('ed-search-cat').value, query: $('ed-query').value}, 'Search');
    });
  };
  // Radarr and Sonarr search movies and shows by IMDb ID, music and books by name
  function searchHint() {
    var imdb = needsImdb();
    $('ed-imdb').hidden = !imdb;
    $('ed-query').placeholder = imdb ? 'tt0499549' : videoKind() ? 'Avatar' : 'Artist, album or book';
    $('ed-imdb-name').textContent = imdb
      ? 'This site is searched by IMDb ID. Type a title and press Grab IMDb ID to get one.'
      : videoKind() ? 'This site is searched by the movie or show title.' : 'Lidarr and Magazarr search by name.';
  }
  $('ed-search-cat').addEventListener('change', searchHint);
  $('ed-download-test').onclick = function() {
    if (!$('ed-url').value.trim()) { $('ed-url').focus(); return; }
    runTest(this, 'download', {url: $('ed-url').value.trim()}, 'Downloads');
  };
  $('ed-query').addEventListener('keydown', function(event) { if (event.key === 'Enter') $('ed-search-test').click(); });
  $('ed-url').addEventListener('keydown', function(event) { if (event.key === 'Enter') $('ed-download-test').click(); });

  // --- editing ------------------------------------------------------------------
  $('ed-json').addEventListener('input', markDirty);
  $('ed-json').addEventListener('keydown', function(event) {
    if (event.key !== 'Tab' || event.shiftKey) return;
    event.preventDefault();
    var area = event.target, start = area.selectionStart;
    area.setRangeText('  ', start, area.selectionEnd, 'end');
    markDirty();
  });
  $('ed-format').onclick = function() { var value = parsed(); if (value) { $('ed-json').value = pretty(value); markDirty(); } };
  $('ed-shipped').onclick = function() {
    var view = $('ed-shipped-view');
    view.hidden = !view.hidden;
    this.setAttribute('aria-expanded', String(!view.hidden));
    this.textContent = view.hidden ? 'Show shipped version' : 'Hide shipped version';
  };
  $('ed-save').onclick = function() {
    var template = parsed();
    if (!template) return;
    $('ed-notes').textContent = '';
    var done = busy($('ed-save'), 'Saving…');
    api('/api/sites/' + encodeURIComponent(key) + '/template', {template: template}, 'PUT').then(function(data) {
      done();
      if (!data.success) { note($('ed-notes'), 'error', 'Not saved: ' + data.error + '.'); return; }
      render(data);
      note($('ed-notes'), 'ok', data.modified
        ? 'Saved. ' + data.key + ' uses your changes from the next feed and search on.'
        : 'Nothing differs from the shipped version, so ' + data.key + ' runs the shipped template.');
    });
  };
  $('ed-reset').onclick = function() {
    if (!confirm('Reset ' + state.key + ' to the shipped version? Your changes are deleted.')) return;
    $('ed-notes').textContent = '';
    var done = busy($('ed-reset'), 'Resetting…');
    api('/api/sites/' + encodeURIComponent(key) + '/template', undefined, 'DELETE').then(function(data) {
      done();
      if (!data.success) { note($('ed-notes'), 'error', data.error + '.'); return; }
      render(data);
      note($('ed-notes'), 'ok', data.key + ' runs the shipped version again.');
    });
  };
  $('ed-back').onclick = function() { window.location.href = config.sites_url; };
  window.addEventListener('beforeunload', function(event) {
    if (state && $('ed-json').value !== saved) { event.preventDefault(); event.returnValue = ''; }
  });
  load();
})();
</script>
"""
_EDITOR_SCRIPT = _EDITOR_SCRIPT.replace("/*UI_HELPERS*/\n", UI_HELPERS_JS)
