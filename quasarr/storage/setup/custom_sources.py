# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

"""The site wizard: users add sites Quasarr does not ship a template for.

Everything a site returns is untrusted. The page shows it only through
``textContent`` and element properties, and the site preview renders in a
sandboxed frame without scripts, links or external resources.
"""

import html
import re

from bottle import abort

from quasarr.providers.html_templates import json_for_script, render_form
from quasarr.storage.custom_sources import load_definitions

_KEY_REGEX = re.compile(r"^[c-z][1-9]$")

# Quasarr categories a user site can serve, in the order the wizard shows them
WIZARD_CATEGORIES = [
    {"id": 2000, "name": "Movies"},
    {"id": 5000, "name": "TV shows"},
    {"id": 3000, "name": "Music"},
    {"id": 7000, "name": "Books"},
    {"id": 6000, "name": "Adult"},
]


def custom_source_wizard_page(key=None, onboarding=False):
    definition = None
    if key is not None:
        if not _KEY_REGEX.match(key):
            abort(404, "Unknown site")
        definition = load_definitions().get(key)
        if definition is None:
            abort(404, "Unknown site")
    config = {
        "definition": definition,
        "categories": WIZARD_CATEGORIES,
        "sites_url": "/" if onboarding else "/hostnames",
    }
    title = (
        f"Edit {html.escape(str(definition.get('name', key)))}"
        if definition
        else "Add a site"
    )
    body = (
        '<script type="application/json" id="wizard-config">'
        + json_for_script(config)
        + "</script>"
        + _WIZARD_HTML
    )
    return render_form(title, body, _WIZARD_SCRIPT + _WIZARD_STYLE)


def setup_custom_source_pages(app, onboarding=False):
    """The wizard pages; onboarding returns to its own sites page."""

    @app.get("/sources/custom")
    def new_custom_source():
        return custom_source_wizard_page(onboarding=onboarding)

    @app.get("/sources/custom/<key>")
    def edit_custom_source(key):
        return custom_source_wizard_page(key, onboarding=onboarding)


_WIZARD_HTML = """
<div class="wizard" id="wizard">
  <ol class="wizard-steps" id="wizard-steps">
    <li data-step="site"><button type="button">Site</button></li>
    <li data-step="feed"><button type="button">Newest releases</button></li>
    <li data-step="search"><button type="button">Search</button></li>
    <li data-step="download"><button type="button">Downloads</button></li>
    <li data-step="save"><button type="button">Save</button></li>
  </ol>

  <section class="wizard-step" data-step="site">
    <p class="wizard-lead">Tell Quasarr where the site is. Nothing is saved until the last step.</p>
    <p class="hint">A site you set up is yours to maintain, and issues about it are not supported.
      Sites that need a login cannot be set up here: they need Python code, contributed as a pull request.</p>
    <label for="w-name">Name</label>
    <input id="w-name" maxlength="60" autocomplete="off" placeholder="My site">
    <p class="hint">Only shown inside Quasarr.</p>
    <label for="w-hostname">Hostname</label>
    <input id="w-hostname" autocomplete="off" autocorrect="off" spellcheck="false" placeholder="example.org">
    <p class="hint">The address you open in your browser, without https://.</p>
    <label for="w-language">Language of its releases</label>
    <select id="w-language">
      <option value="de">German</option>
      <option value="en">English</option>
      <option value="fr">French</option>
    </select>
    <label class="check"><input type="checkbox" id="w-flaresolverr"> Load the site through FlareSolverr</label>
    <p class="hint">Turn this on if the site shows a browser check before its pages.
      Quasarr also falls back to FlareSolverr on its own when it meets one and FlareSolverr is set up.</p>
    <details class="wizard-more" id="import-box">
      <summary>Import a template someone shared</summary>
      <p class="hint">Paste the template as JSON or the template file a share produced. You test every step before you save.</p>
      <label for="w-import" class="visually-hidden">Template</label>
      <textarea id="w-import" rows="6" spellcheck="false" autocomplete="off"></textarea>
      <div class="button-row left"><button type="button" class="btn-secondary" id="import-apply">Import</button></div>
      <div class="wizard-notes" id="import-notes" aria-live="polite"></div>
    </details>
    <div class="wizard-notes" id="site-notes" aria-live="polite"></div>
    <div class="button-row">
      <button type="button" class="btn-primary" id="site-next">Continue</button>
    </div>
  </section>

  <section class="wizard-step" data-step="feed" hidden>
    <p class="wizard-lead">Choose what the site offers and where its newest releases are listed.</p>
    <div id="feed-categories" class="category-grid"></div>
    <div id="feed-rows"></div>
    <div class="wizard-notes" id="feed-notes" aria-live="polite"></div>
    <div id="feed-picker"></div>
    <div class="results" id="feed-results" aria-live="polite"></div>
    <div class="button-row">
      <button type="button" class="btn-secondary" data-back>Back</button>
      <button type="button" class="btn-secondary" id="feed-test">Test newest releases</button>
      <button type="button" class="btn-primary" id="feed-next" disabled title="Test the newest releases first">Continue</button>
    </div>
  </section>

  <section class="wizard-step" data-step="search" hidden>
    <p class="wizard-lead">Radarr and Sonarr search by IMDb ID. Quasarr can send that ID to the site,
      or the movie or show title when the site cannot handle IDs.</p>
    <div class="button-row left">
      <button type="button" class="btn-primary" id="search-discover">Find the search for me</button>
    </div>
    <div class="wizard-notes" id="search-notes" aria-live="polite"></div>
    <details id="search-manual">
      <summary>Search settings</summary>
      <label>Search with</label>
      <div class="radio-row" id="search-modes">
        <label class="check"><input type="radio" name="w-mode" value="imdb"> IMDb ID</label>
        <label class="check"><input type="radio" name="w-mode" value="title" checked> Title</label>
        <label class="check"><input type="radio" name="w-mode" value="off"> No search</label>
      </div>
      <label for="w-method">Request</label>
      <select id="w-method"><option value="get">GET</option><option value="post">POST form</option></select>
      <label for="w-search-url">Search address</label>
      <input id="w-search-url" spellcheck="false" placeholder="/?s={q}">
      <p class="hint">{q} is replaced by what Quasarr searches for.</p>
      <div id="w-body-wrap" hidden>
        <label for="w-search-body">Form fields</label>
        <input id="w-search-body" spellcheck="false" placeholder="search={q}">
      </div>
      <label class="check"><input type="checkbox" id="w-phrase"> Also search by name for music and books</label>
    </details>
    <div id="search-results-setup">
      <h4>Results page</h4>
      <p class="hint">Search results are often laid out differently from the newest releases.
        Load one results page to check.</p>
      <label for="search-query">Search for</label>
      <div class="inline">
        <input id="search-query" spellcheck="false" placeholder="tt0111161 or a title">
        <button type="button" class="btn-secondary" id="search-load">Show results page</button>
        <button type="button" class="btn-secondary" id="search-test">Test search</button>
      </div>
      <div class="radio-row" id="search-layouts" hidden>
        <label class="check"><input type="radio" name="w-layout" value="same" checked> Results look like the newest releases</label>
        <label class="check"><input type="radio" name="w-layout" value="own"> Results use their own layout</label>
      </div>
      <div id="search-picker"></div>
    </div>
    <div class="results" id="search-results" aria-live="polite"></div>
    <div class="button-row">
      <button type="button" class="btn-secondary" data-back>Back</button>
      <button type="button" class="btn-primary" id="search-next">Continue</button>
    </div>
  </section>

  <section class="wizard-step" data-step="download" hidden>
    <p class="wizard-lead">When your app grabs a release, Quasarr opens its page and collects the download links.</p>
    <div class="wizard-notes" id="download-notes" aria-live="polite"></div>
    <div id="download-setup">
      <label for="download-release">Release to check</label>
      <div class="inline">
        <select id="download-release"></select>
        <button type="button" class="btn-secondary" id="download-load">Open release page</button>
      </div>
      <div class="field-chips" id="download-chips"></div>
      <label for="w-download-selector">Download links</label>
      <input id="w-download-selector" spellcheck="false" placeholder="CSS selector">
      <label for="w-mirror">Name each link after</label>
      <select id="w-mirror">
        <option value="text">its link text</option>
        <option value="href_host">the address it points to</option>
        <option value="hoster_name">the hoster named in its text</option>
      </select>
      <label class="check"><input type="checkbox" id="w-redirects"> The links point to this site and redirect to the download</label>
      <div class="button-row left">
        <button type="button" class="btn-secondary" id="download-test">Test links</button>
      </div>
      <div class="results" id="download-results" aria-live="polite"></div>
    </div>
    <details class="wizard-more" id="userscript-box">
      <summary>The links only appear in a browser, after a CAPTCHA or a click</summary>
      <p>Quasarr can hand each release page to a userscript you write. When your app grabs a release, the CAPTCHA page
        opens it in your browser, and your script sends the links back.</p>
      <p><strong>This needs your own JavaScript.</strong> Install <a href="https://www.tampermonkey.net/" target="_blank" rel="noopener noreferrer">Tampermonkey</a>
        first, then the <a href="/captcha/custom.user.js" target="_blank">userscript template</a>. The template does not work out of the box:
        it only connects the page to Quasarr, and you add the code that finds the links. It never updates itself, so your code stays.</p>
      <label class="check"><input type="checkbox" id="w-userscript"> My own userscript collects the links of this site</label>
    </details>
    <div class="button-row">
      <button type="button" class="btn-secondary" data-back>Back</button>
      <button type="button" class="btn-primary" id="download-next">Continue</button>
    </div>
  </section>

  <section class="wizard-step" data-step="save" hidden>
    <dl class="summary" id="summary"></dl>
    <div class="wizard-notes" id="save-notes" aria-live="polite"></div>
    <div class="button-row">
      <button type="button" class="btn-secondary" data-back>Back</button>
      <button type="button" class="btn-primary" id="save">Save site</button>
    </div>
  </section>
</div>
"""

_WIZARD_STYLE = """
<style>
  /* the picker needs room for the page preview next to the fields */
  .inner:has(.wizard) { max-width: min(1200px, 96vw); }
  .wizard { text-align: left; max-width: 72rem; margin: 0 auto; }
  .wizard input[type=checkbox], .wizard input[type=radio] { width: auto; display: inline-block; margin: 0; flex: 0 0 auto; }
  .wizard label { display: block; font-weight: 600; margin: .9rem 0 .25rem; }
  .wizard label.check { font-weight: normal; display: flex; align-items: center; gap: .4rem; }
  .wizard input:not([type=checkbox]):not([type=radio]), .wizard select { width: 100%; box-sizing: border-box; }
  .wizard .hint { color: var(--text-muted); font-size: .85rem; margin: .25rem 0 0; }
  .wizard-more { border: 1px solid var(--divider-color); border-radius: .5rem; padding: .5rem .75rem; margin: 1rem 0; }
  .wizard-more summary { cursor: pointer; font-weight: 600; }
  .wizard-more textarea { width: 100%; box-sizing: border-box; font-family: ui-monospace, monospace; font-size: .85rem; }
  .wizard .visually-hidden { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); }
  .wizard-lead { margin-top: 0; }
  .wizard-steps { display: flex; flex-wrap: wrap; gap: .25rem; padding: 0; margin: 0 0 1.25rem;
    list-style: none; counter-reset: step; }
  .wizard-steps li { counter-increment: step; flex: 1; min-width: 0;
    border-bottom: 3px solid var(--divider-color); }
  .wizard-steps button { all: unset; display: block; width: 100%; box-sizing: border-box; padding: .45rem .6rem;
    color: var(--text-muted); font-size: .9rem; cursor: default; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .wizard-steps button::before { content: counter(step) ". "; }
  .wizard-steps li.done { border-color: var(--success-color); }
  .wizard-steps li.done button { color: var(--fg-color); cursor: pointer; }
  .wizard-steps li.done button:hover { text-decoration: underline; }
  .wizard-steps li.current { border-color: var(--primary); }
  .wizard-steps li.current button { color: var(--fg-color); font-weight: 600; }
  .wizard-steps button:focus-visible { outline: 2px solid var(--primary); }
  .radio-row { display: flex; flex-wrap: wrap; gap: .25rem 1.25rem; margin: .5rem 0; }
  .picker-box { margin-top: 1rem; }
  .picker-box h4 { margin: 0 0 .25rem; }
  .wizard .button-row { display: flex; gap: .5rem; justify-content: flex-end; flex-wrap: wrap; margin-top: 1.25rem; }
  .wizard .button-row.left { justify-content: flex-start; margin-top: .5rem; }
  .wizard .inline { display: flex; gap: .5rem; }
  .wizard .inline input, .wizard .inline select { flex: 1; }
  .wizard-notes:empty { display: none; }
  .note { padding: .6rem .8rem; border-radius: .4rem; margin: .6rem 0; border: 1px solid var(--border-color); }
  .note.ok { background: var(--success-bg); border-color: var(--success-border); }
  .note.warn { background: #fff3cd; border-color: #ffe69c; color: #664d03; }
  .note.error { background: var(--error-bg); border-color: var(--error-border); }
  .note.busy { color: var(--text-muted); }
  .category-grid { display: flex; flex-wrap: wrap; gap: .25rem 1rem; }
  .feed-row { display: grid; grid-template-columns: 8rem 1fr auto; gap: .5rem; align-items: center; margin: .4rem 0; }
  .picker { display: grid; grid-template-columns: minmax(0, 26rem) minmax(0, 1fr); gap: 1rem; align-items: start; }
  .picker > * { min-width: 0; }
  @media (max-width: 900px) { .picker { grid-template-columns: minmax(0, 1fr); } }
  @media (max-width: 600px) {
    .field-inputs { flex-wrap: wrap; }
    .field-inputs input:first-child { flex: 1 1 100%; }
    .field-inputs select, .field-inputs .label-input { flex: 1 1 auto; }
    .wizard .inline { flex-wrap: wrap; }
    .wizard .inline input, .wizard .inline select { flex: 1 1 100%; }
    .feed-row.inline > span { flex: 1 1 100%; }
    /* the step bar keeps its numbers; only the current step shows its name */
    .wizard-steps { flex-wrap: nowrap; }
    .wizard-steps li { flex: 0 0 auto; }
    .wizard-steps li:not(.current) button { width: auto; font-size: 0; padding: .45rem .7rem; }
    .wizard-steps li:not(.current) button::before { font-size: .9rem; content: counter(step); }
    .wizard-steps li.current { flex: 1 1 auto; min-width: 0; }
    .preview-wrap iframe { height: 26rem; }
    .wizard .button-row { justify-content: stretch; }
    .wizard .button-row > button { flex: 1 1 auto; }
  }
  .wizard .results { overflow-x: auto; }
  .field-row { border: 1px solid var(--border-color); border-radius: .4rem; padding: .5rem .6rem; margin-bottom: .5rem; }
  .field-row.active { border-color: #f59f00; box-shadow: 0 0 0 2px rgba(245,159,0,.25); }
  .field-name { font-weight: 600; }
  .field-inputs { display: flex; gap: .35rem; margin-top: .35rem; }
  .field-inputs input { flex: 1; min-width: 0; }
  .field-inputs .label-input { flex: 0 0 6.5rem; }
  .field-inputs select { flex: 0 0 8.5rem; width: auto; }
  .field-inputs .pick { flex: 0 0 auto; }
  .field-count { display: block; font-size: .8rem; color: var(--text-muted); margin-top: .25rem; }
  .field-count.good { color: var(--success-color); }
  .field-count.bad { color: var(--error-color); }
  .field-chips { display: flex; flex-wrap: wrap; gap: .3rem; margin-top: .35rem; }
  .chip { border: 1px solid var(--border-color); background: var(--code-bg); color: var(--fg-color);
    border-radius: 1rem; padding: .15rem .6rem; font-size: .8rem; cursor: pointer; max-width: 100%;
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .chip.selected { border-color: var(--primary); box-shadow: 0 0 0 1px var(--primary) inset; }
  .pick.picking { background: #f59f00; color: #000; border-color: #f59f00; }
  .preview-wrap { border: 1px solid var(--border-color); border-radius: .4rem; overflow: hidden; }
  .preview-bar { padding: .35rem .6rem; font-size: .8rem; background: var(--code-bg); color: var(--text-muted); }
  .preview-bar.picking { background: #f59f00; color: #000; }
  .preview-wrap iframe { display: block; width: 100%; height: 36rem; border: 0; background: #fff; }
  .results table { width: 100%; border-collapse: collapse; font-size: .85rem; margin-top: .5rem; }
  .results th, .results td { text-align: left; padding: .3rem .4rem; border-bottom: 1px solid var(--divider-color);
    vertical-align: top; word-break: break-word; }
  .results caption { text-align: left; padding: .4rem 0; }
  .summary { display: grid; grid-template-columns: max-content 1fr; gap: .35rem 1rem; }
  .summary dt { font-weight: 600; }
  .summary dd { margin: 0; word-break: break-word; }
  details summary { cursor: pointer; margin: .8rem 0 .2rem; }
  .chip-button { margin: .25rem .35rem 0 0; padding: .25rem .7rem; font-size: .85rem; text-decoration: none; display: inline-block; }
  .feed-row.inline > span { flex: 0 0 7rem; align-self: center; }
  .share-module { max-height: 22rem; overflow: auto; background: var(--code-bg); padding: .6rem; font-size: .8rem; text-align: left; }
</style>
"""

_WIZARD_SCRIPT = r"""
<script>
(function() {
  'use strict';
  var config = JSON.parse(document.getElementById('wizard-config').textContent);
  // a template imported on the first step comes back after a reload
  var imported = null;
  try {
    imported = JSON.parse(sessionStorage.getItem('quasarr-import') || 'null');
    sessionStorage.removeItem('quasarr-import');
  } catch (e) { imported = null; }
  if (imported) {
    config.definition = Object.assign({}, imported.definition, {hostname: imported.hostname});
    config.imported = true;
  }
  var draft = config.definition || {};
  var FIELDS = [
    {name: 'title', label: 'Release name', help: 'The full release name, as in Movie.2026.1080p.WEB.x264-GROUP.', attrs: ['text', 'title']},
    {name: 'link', label: 'Release link', help: 'The link that opens the release page.', attrs: ['href']},
    {name: 'size', label: 'Size', help: 'Text such as 1,4 GB. Enter a label like "Size" when the value follows one.', attrs: ['text'], labelled: true},
    {name: 'date', label: 'Date', help: 'When the release was posted.', attrs: ['text', 'datetime'], labelled: true}
  ];
  var ATTR_NAMES = {text: 'text', title: 'title text', href: 'link address', datetime: 'date attribute'};
  var ORDER = ['site', 'feed', 'search', 'download', 'save'];
  var state = {step: 'site', reached: config.definition ? 4 : 0, feedRows: [], feedOk: !!config.definition && !config.imported,
    feedIsRss: false, rssListing: null};

  // --- DOM helpers: site content only ever becomes text ----------------------
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
      node.appendChild(typeof child === 'string' ? document.createTextNode(child) : child);
    });
    return node;
  }
  function note(target, kind, parts) {
    var box = el('div', {className: 'note ' + kind, role: kind === 'error' ? 'alert' : 'status'});
    (Array.isArray(parts) ? parts : [parts]).forEach(function(part) {
      box.appendChild(typeof part === 'string' ? document.createTextNode(part) : part);
    });
    (typeof target === 'string' ? $(target) : target).appendChild(box);
    return box;
  }
  function clear(target) { (typeof target === 'string' ? $(target) : target).textContent = ''; }
  function api(path, body, method) {
    return quasarrApiFetch(path, {
      method: method || 'POST',
      headers: {'Content-Type': 'application/json'},
      body: body === undefined ? undefined : JSON.stringify(body)
    }).then(function(response) {
      return response.json().catch(function() {
        return {success: false, error: 'Quasarr answered with HTTP ' + response.status};
      });
    }).catch(function() { return {success: false, error: 'Quasarr did not answer'}; });
  }
  function busy(button, text) {
    var original = button.textContent;
    button.disabled = true;
    button.setAttribute('aria-busy', 'true');
    button.textContent = text;
    return function() { button.disabled = false; button.removeAttribute('aria-busy'); button.textContent = original; };
  }
  function host() {
    return $('w-hostname').value.trim().toLowerCase().replace(/^https?:\/\//, '').replace(/[\/?#].*$/, '').replace(/^www\./, '');
  }
  // "hostname: a file hoster …" reads better without its field prefix
  function plain(message) {
    var text = String(message || '').replace(/^[a-z_.\[\]0-9]+: /, '');
    return text.charAt(0).toUpperCase() + text.slice(1);
  }
  function path(url) { return String(url || '/').replace(/^https?:\/\/\{host\}/, '') || '/'; }
  function ensureSlash(value) { value = String(value || '/').trim() || '/'; return value.charAt(0) === '/' ? value : '/' + value; }
  function onSite(url) {
    try {
      var name = new URL(url).hostname.replace(/^www\./, '');
      return name === host() || name.slice(-host().length - 1) === '.' + host();
    } catch (e) { return false; }
  }

  // --- steps -------------------------------------------------------------------
  function show(step) {
    pickers.forEach(function(picker) { picker.stopPicking(); });
    state.step = step;
    state.reached = Math.max(state.reached, ORDER.indexOf(step));
    document.querySelectorAll('.wizard-step').forEach(function(section) {
      section.hidden = section.getAttribute('data-step') !== step;
    });
    document.querySelectorAll('#wizard-steps li').forEach(function(item) {
      var index = ORDER.indexOf(item.getAttribute('data-step'));
      var current = index === ORDER.indexOf(step);
      item.className = current ? 'current' : (index <= state.reached ? 'done' : '');
      var button = item.querySelector('button');
      button.disabled = current || index > state.reached;
      if (current) button.setAttribute('aria-current', 'step'); else button.removeAttribute('aria-current');
    });
    if (step === 'download') prepareDownload();
    if (step === 'save') renderSummary();
    var heading = document.querySelector('.wizard-step[data-step="' + step + '"] .wizard-lead');
    window.scrollTo({top: 0, behavior: 'smooth'});
    if (heading) { heading.setAttribute('tabindex', '-1'); heading.focus({preventScroll: true}); }
  }
  document.querySelectorAll('#wizard-steps li').forEach(function(item) {
    item.querySelector('button').onclick = function() { show(item.getAttribute('data-step')); };
  });
  document.querySelectorAll('[data-back]').forEach(function(button) {
    button.onclick = function() { show(ORDER[ORDER.indexOf(state.step) - 1]); };
  });
  // Enter runs the main action of a step
  document.querySelectorAll('.wizard-step').forEach(function(section) {
    section.addEventListener('keydown', function(event) {
      if (event.key !== 'Enter' || event.target.tagName !== 'INPUT') return;
      var action = event.target.closest('.inline') ? event.target.closest('.inline').querySelector('button')
        : section.querySelector('.button-row .btn-primary');
      if (action && !action.disabled) { event.preventDefault(); action.click(); }
    });
  });

  // --- picker: preview + click-to-pick + field rows -----------------------------
  var pickers = [];
  function createPicker(mountId, notesId, title, hint) {
    var picker = {page: null, picking: null, marked: {items: [], fields: {}}, activeField: 'title', onEdit: null};
    var mount = $(mountId);
    var chips = el('div', {className: 'field-chips'});
    var itemInput = el('input', {spellcheck: 'false', placeholder: 'CSS selector', 'aria-label': 'Release block selector'});
    var itemPick = el('button', {type: 'button', className: 'btn-secondary pick', text: 'Pick'});
    var itemCount = el('span', {className: 'field-count'});
    var itemRow = el('div', {className: 'field-row', 'data-field': 'item'}, [
      el('span', {className: 'field-name', text: 'Release block'}),
      chips,
      el('div', {className: 'field-inputs'}, [itemInput, itemPick]),
      el('span', {className: 'hint', text: 'The part of the page that holds one release.'}),
      itemCount
    ]);
    var rows = {};
    var fieldBox = el('div');
    FIELDS.forEach(function(field) {
      var selector = el('input', {spellcheck: 'false', placeholder: 'inside the release block', 'aria-label': field.label + ' selector'});
      var label = field.labelled ? el('input', {className: 'label-input', spellcheck: 'false', placeholder: 'label', 'aria-label': field.label + ' label'}) : null;
      var attr = el('select', {'aria-label': field.label + ' reads'});
      field.attrs.forEach(function(name) { attr.appendChild(el('option', {value: name, text: ATTR_NAMES[name]})); });
      var pick = el('button', {type: 'button', className: 'btn-secondary pick', text: 'Pick'});
      var inputs = [selector];
      if (label) inputs.push(label);
      if (field.attrs.length > 1) inputs.push(attr);
      inputs.push(pick);
      var row = el('div', {className: 'field-row', 'data-field': field.name}, [
        el('span', {className: 'field-name', text: field.label}),
        el('div', {className: 'field-chips'}),
        el('div', {className: 'field-inputs'}, inputs),
        el('span', {className: 'hint', text: field.help}),
        el('span', {className: 'field-count'})
      ]);
      rows[field.name] = {row: row, selector: selector, label: label, attr: attr, pick: pick, field: field,
        chips: row.querySelector('.field-chips'), count: row.querySelector('.field-count')};
      [selector, label, attr].forEach(function(input) {
        if (input) input.addEventListener('input', function() { edited(); });
      });
      row.addEventListener('focusin', function() { focusField(field.name); });
      pick.onclick = function() { startPicking(field.name, pick); };
      fieldBox.appendChild(row);
    });
    var cleanup = el('select', {'aria-label': 'Release names'});
    [['trim', 'Keep them as the site shows them'], ['spaces', 'Replace spaces with dots'],
     ['scene', 'Rewrite them in scene style']].forEach(function(option) {
      cleanup.appendChild(el('option', {value: option[0], text: option[1]}));
    });
    cleanup.addEventListener('change', function() { edited(); });
    fieldBox.appendChild(el('div', {className: 'field-row'}, [
      el('label', {className: 'field-name', text: 'Release names'}), cleanup,
      el('span', {className: 'hint', text: 'Scene style also removes umlauts and brackets, which can hurt music and book names.'})
    ]));
    itemInput.addEventListener('input', function() { edited(); });
    itemPick.onclick = function() { startPicking('item', itemPick); };
    var bar = el('div', {className: 'preview-bar', text: 'Preview of the loaded page'});
    var frame = el('iframe', {sandbox: 'allow-same-origin', referrerpolicy: 'no-referrer', title: title + ' preview'});
    var box = el('div', {className: 'picker-box', hidden: 'hidden'}, [
      el('h4', {text: title}),
      el('p', {className: 'hint', text: hint}),
      el('div', {className: 'picker'}, [
        el('div', {className: 'picker-fields'}, [itemRow, fieldBox]),
        el('div', {className: 'preview-wrap'}, [bar, frame])
      ])
    ]);
    mount.appendChild(box);

    var timer = null;
    function edited() {
      if (picker.onEdit) picker.onEdit();
      clearTimeout(timer);
      timer = setTimeout(refresh, 350);
    }
    function readSpec(name) {
      var r = rows[name];
      var spec = {};
      if (r.selector.value.trim()) spec.selector = r.selector.value.trim();
      if (r.label && r.label.value.trim()) spec.label = r.label.value.trim();
      var value = r.field.attrs.length > 1 ? r.attr.value : r.field.attrs[0];
      if (value !== 'text') spec.attr = value;
      return spec;
    }
    function writeSpec(name, spec) {
      var r = rows[name];
      spec = spec || {};
      r.selector.value = spec.selector || '';
      if (r.label) r.label.value = Array.isArray(spec.label) ? spec.label[0] : (spec.label || '');
      if (r.field.attrs.length > 1) {
        var wanted = spec.attr || 'text';
        if (!r.attr.querySelector('option[value="' + CSS.escape(wanted) + '"]')) {
          r.attr.appendChild(el('option', {value: wanted, text: wanted + ' attribute'}));
        }
        r.attr.value = wanted;
      }
    }
    picker.listing = function() {
      var listing = {item: itemInput.value.trim()};
      if (cleanup.value !== 'trim') listing.title_cleanup = cleanup.value;
      FIELDS.forEach(function(field) {
        var spec = readSpec(field.name);
        if (Object.keys(spec).length || field.name === 'title' || field.name === 'link') listing[field.name] = spec;
      });
      return listing;
    };
    picker.setListing = function(listing, suggestions) {
      listing = listing || {};
      itemInput.value = listing.item || '';
      cleanup.value = ['spaces', 'scene'].indexOf(listing.title_cleanup) !== -1 ? listing.title_cleanup : 'trim';
      FIELDS.forEach(function(field) {
        writeSpec(field.name, listing[field.name]);
        var target = rows[field.name].chips;
        target.textContent = '';
        ((suggestions || {})[field.name] || []).forEach(function(candidate) {
          if (!candidate.spec) return;
          var sample = (candidate.samples || [])[0] || '';
          var chip = el('button', {type: 'button', className: 'chip',
            title: (candidate.spec.selector || 'release block') + (candidate.spec.label ? ' after "' + candidate.spec.label + '"' : '') + (sample ? ': ' + sample : ''),
            text: Math.round(candidate.coverage * 100) + '% · ' + (sample || candidate.spec.selector || 'release block')});
          chip.onclick = function() { writeSpec(field.name, candidate.spec); edited(); };
          target.appendChild(chip);
        });
      });
      refresh();
    };
    picker.setItems = function(items) {
      chips.textContent = '';
      (items || []).forEach(function(candidate) {
        var chip = el('button', {type: 'button', className: 'chip', title: 'Use ' + candidate.selector,
          text: candidate.selector});
        chip.onclick = function() { itemInput.value = candidate.selector; edited(); };
        chips.appendChild(chip);
      });
    };
    picker.load = function(page) {
      picker.page = page;
      box.hidden = false;
      picker.setItems(page.items || []);
      frame.srcdoc = page.preview || '<!doctype html><p>No preview</p>';
    };
    picker.hide = function() { box.hidden = true; picker.page = null; };
    picker.loaded = function() { return !!(picker.page && picker.page.token); };

    function setCount(target, text, kind) {
      target.textContent = text || '';
      target.className = 'field-count' + (kind ? ' ' + kind : '');
    }
    function refresh() {
      if (!picker.loaded()) return Promise.resolve(null);
      var listing = picker.listing();
      var fields = {};
      FIELDS.forEach(function(field) { fields[field.name] = listing[field.name] || {}; });
      return api('/api/custom-sources/highlight', {token: picker.page.token, item_selector: listing.item, fields: fields})
        .then(function(data) {
          if (!data.success) {
            setCount(itemCount, data.error, 'bad');
            return data;
          }
          picker.marked = data;
          var items = data.items.length;
          setCount(itemCount, items ? items + ' releases on this page' : 'Matches nothing on this page', items ? 'good' : 'bad');
          FIELDS.forEach(function(field) {
            var found = data.fields[field.name];
            if (found && found.error) { setCount(rows[field.name].count, found.error, 'bad'); return; }
            var count = (found || []).length;
            // an optional field left empty is fine; one that reads nothing is not
            var unset = !Object.keys(listing[field.name] || {}).length;
            setCount(rows[field.name].count, !items ? '' : (unset ? 'Not used' : 'Read in ' + count + ' of ' + items + ' releases'),
              !items || unset ? '' : (count === items ? 'good' : (count ? '' : 'bad')));
          });
          paint();
          return data;
        });
    }
    picker.refresh = refresh;
    function doc() { return frame.contentDocument; }
    function paint() {
      var d = doc();
      if (!d || !d.body) return;
      d.querySelectorAll('.q-item, .q-field').forEach(function(node) { node.classList.remove('q-item', 'q-field'); });
      (picker.marked.items || []).forEach(function(q) {
        var node = d.querySelector('[data-q="' + Number(q) + '"]');
        if (node) node.classList.add('q-item');
      });
      ((picker.marked.fields || {})[picker.activeField] || []).forEach(function(q) {
        var node = d.querySelector('[data-q="' + Number(q) + '"]');
        if (node) node.classList.add('q-field');
      });
      if (!picker.scrolled) {
        var first = d.querySelector('.q-item');
        if (first) { first.scrollIntoView({block: 'center'}); picker.scrolled = true; }
      }
    }
    function focusField(name) {
      picker.activeField = name;
      Object.keys(rows).forEach(function(key) { rows[key].row.classList.toggle('active', key === name); });
      paint();
    }
    frame.addEventListener('load', function() {
      picker.scrolled = false;
      var d = doc();
      if (!d) return;
      d.addEventListener('click', function(event) {
        event.preventDefault();
        event.stopPropagation();
        var target = event.target.closest('[data-q]');
        if (picker.picking && target) choose(Number(target.getAttribute('data-q')));
      }, true);
      d.addEventListener('mouseover', function(event) {
        if (!picker.picking) return;
        d.querySelectorAll('.q-hover').forEach(function(node) { node.classList.remove('q-hover'); });
        var target = event.target.closest('[data-q]');
        if (target) target.classList.add('q-hover');
      });
      d.addEventListener('keydown', function(event) { if (event.key === 'Escape') picker.stopPicking(); });
      paint();
    });
    function startPicking(name, button) {
      if (picker.picking === name) { picker.stopPicking(); return; }
      picker.stopPicking();
      if (name !== 'item' && !itemInput.value.trim()) {
        clear(notesId);
        note(notesId, 'warn', 'Choose the release block first.');
        return;
      }
      picker.picking = name;
      picker.pickButton = button;
      button.classList.add('picking');
      button.textContent = 'Cancel';
      bar.classList.add('picking');
      bar.textContent = name === 'item'
        ? 'Click anywhere inside one release. Press Esc to cancel.'
        : 'Click the ' + rows[name].field.label.toLowerCase() + ' of any release. Press Esc to cancel.';
      if (name !== 'item') focusField(name);
      // on a narrow screen the preview sits below the fields
      if (window.matchMedia('(max-width: 900px)').matches) bar.scrollIntoView({behavior: 'smooth', block: 'start'});
    }
    picker.stopPicking = function() {
      if (!picker.picking) return;
      picker.picking = null;
      picker.pickButton.classList.remove('picking');
      picker.pickButton.textContent = 'Pick';
      bar.classList.remove('picking');
      bar.textContent = 'Preview of the loaded page';
      var d = doc();
      if (d) d.querySelectorAll('.q-hover').forEach(function(node) { node.classList.remove('q-hover'); });
    };
    document.addEventListener('keydown', function(event) { if (event.key === 'Escape') picker.stopPicking(); });
    function choose(q) {
      var name = picker.picking;
      api('/api/custom-sources/pick', {token: picker.page.token, q: q, kind: name === 'item' ? 'item' : 'field',
        field: name, item_selector: itemInput.value.trim()}).then(function(data) {
        if (!data.success) { clear(notesId); note(notesId, 'warn', data.error); return; }
        picker.stopPicking();
        if (name === 'item') itemInput.value = data.selector;
        else writeSpec(name, data.spec);
        edited();
        if (window.matchMedia('(max-width: 900px)').matches) {
          (name === 'item' ? itemRow : rows[name].row).scrollIntoView({behavior: 'smooth', block: 'center'});
        }
      });
    }
    pickers.push(picker);
    return picker;
  }

  // --- step 1: site, and built-in templates that fit -----------------------------
  $('w-name').value = draft.name || '';
  $('w-hostname').value = draft.hostname || new URLSearchParams(location.search).get('hostname') || '';
  $('w-language').value = draft.language || 'de';
  $('w-flaresolverr').checked = !!draft.flaresolverr;
  var matchBox = el('div', {className: 'wizard-notes', id: 'site-matches', 'aria-live': 'polite'});
  $('site-notes').parentNode.insertBefore(matchBox, $('site-notes'));

  function useTemplate(key, button) {
    var done = busy(button, 'Saving…');
    api('/api/sites/' + encodeURIComponent(key.toLowerCase()), {hostname: host()}, 'PUT').then(function(data) {
      done();
      clear('site-matches');
      if (!data.success) { note('site-matches', 'error', 'Could not use ' + key + ': ' + data.error + '.'); return; }
      note('site-matches', 'ok', [key + ' now reads ' + host() + '. It needs no further setup. ',
        el('a', {href: config.sites_url, text: 'Back to your sites'})]);
    });
  }
  function offerTemplates(keys, reason) {
    if (!keys.length) return;
    var line = el('div', {className: 'note warn'}, [reason + ' ']);
    keys.forEach(function(match) {
      var label = match.same_hostname ? 'The ' + match.key + ' template already reads it' : 'Use the ' + match.key + ' template';
      var button = el('button', {type: 'button', className: 'btn-secondary chip-button', text: label});
      if (match.same_hostname) button.disabled = true;
      else button.onclick = function() { useTemplate(match.key, button); };
      line.appendChild(button);
      if (match.configured && !match.same_hostname) {
        line.appendChild(el('span', {className: 'hint', text: ' (replaces the hostname set for ' + match.key + ')'}));
      }
    });
    $('site-matches').appendChild(line);
  }
  $('import-apply').onclick = function() {
    clear('import-notes');
    var text = $('w-import').value.trim();
    if (!text) { $('w-import').focus(); return; }
    var done = busy($('import-apply'), 'Checking…');
    api('/api/custom-sources/import', {text: text}).then(function(data) {
      done();
      if (!data.success) { note('import-notes', 'error', 'Could not import it: ' + plain(data.error) + '.'); return; }
      if (config.definition && !config.imported && !confirm('Replace the setup of this site with the imported template?')) return;
      var definition = Object.assign({}, data.definition, draft.key ? {key: draft.key} : {});
      sessionStorage.setItem('quasarr-import', JSON.stringify({definition: definition, hostname: host()}));
      window.location.reload();
    });
  };

  $('site-next').onclick = function() {
    clear('site-notes');
    if (!$('w-name').value.trim()) { note('site-notes', 'error', 'Give the site a name.'); $('w-name').focus(); return; }
    if (!/^[a-z0-9-]+(\.[a-z0-9-]+)+$/.test(host())) {
      note('site-notes', 'error', 'Enter a hostname such as example.org.');
      $('w-hostname').focus();
      return;
    }
    var done = busy($('site-next'), 'Checking the site…');
    api('/api/custom-sources/page', {hostname: host(), url: '/', flaresolverr: $('w-flaresolverr').checked})
      .then(function(data) {
        done();
        if (data.builtin && data.builtin.length) {
          note('site-notes', 'warn', ['Quasarr already reads this hostname as ' + data.builtin.join(', ') +
            '. Adding it again would list every release twice. See the ', el('a', {href: config.sites_url, text: 'your sites'}), '.']);
        }
        if (data.templates && data.templates.length) {
          clear('site-matches');
          offerTemplates(data.templates.map(function(match) { return {key: match.key}; }),
            'A built-in template matches this site and read ' + data.templates[0].rows + ' of its releases:');
        }
        if (data.suggest_flaresolverr) {
          $('w-flaresolverr').checked = true;
          note('site-notes', 'warn', 'The site showed a browser check. FlareSolverr is now turned on for it.');
        }
        if (!data.success) { note('site-notes', 'error', 'Could not open the site: ' + data.error + '.'); return; }
        show('feed');
        if (!document.querySelector('#feed-rows .feed-row')) loadFeedDefaults();
      });
  };

  // --- step 2: newest releases ----------------------------------------------------
  var feedPicker = createPicker('feed-picker', 'feed-notes', 'Release list',
    'Blue frames are releases, yellow marks the field you are working on. Choose a suggestion, or click Pick and then the matching part of the page.');
  feedPicker.onEdit = function() { setFeedTested(false); };
  var feedUrls = {};
  (draft.feeds || []).forEach(function(feed) { feedUrls[feed.category] = path(feed.url); });
  config.categories.forEach(function(category) {
    var box = el('input', {type: 'checkbox', id: 'cat-' + category.id});
    box.checked = category.id in feedUrls;
    box.onchange = function() { renderFeedRows(); setFeedTested(false); };
    $('feed-categories').appendChild(el('label', {className: 'check'}, [box, ' ' + category.name]));
  });
  function selectedCategories() {
    return config.categories.filter(function(category) { return $('cat-' + category.id).checked; });
  }
  function setFeedTested(ok) {
    state.feedOk = ok;
    $('feed-next').disabled = !ok;
    $('feed-next').title = ok ? '' : 'Test the newest releases first';
  }
  function loadFeedDefaults() {
    if (!selectedCategories().length) { $('cat-2000').checked = true; $('cat-5000').checked = true; }
    renderFeedRows();
    var first = document.querySelector('#feed-rows .load-feed');
    if (first) first.click();
  }
  function renderFeedRows() {
    var wrap = $('feed-rows');
    wrap.textContent = '';
    selectedCategories().forEach(function(category) {
      var input = el('input', {spellcheck: 'false', placeholder: '/', 'aria-label': category.name + ' page'});
      input.value = feedUrls[category.id] || '/';
      feedUrls[category.id] = input.value;
      input.oninput = function() { feedUrls[category.id] = input.value.trim() || '/'; setFeedTested(false); };
      var load = el('button', {type: 'button', className: 'btn-secondary load-feed', text: 'Load page'});
      load.onclick = function() { loadFeedPage(ensureSlash(input.value), load); };
      wrap.appendChild(el('div', {className: 'feed-row inline'}, [el('span', {text: category.name}), input, load]));
    });
    if (selectedCategories().length) {
      wrap.appendChild(el('p', {className: 'hint', text: 'The page listing the newest releases of each kind. One page can serve several kinds.'}));
    }
  }
  function loadFeedPage(url, button) {
    clear('feed-notes');
    var done = busy(button, 'Loading…');
    api('/api/custom-sources/page', {hostname: host(), url: url, flaresolverr: $('w-flaresolverr').checked})
      .then(function(data) {
        done();
        if (!data.success) { note('feed-notes', 'error', 'Could not load the page: ' + data.error + '.'); return; }
        state.feedIsRss = data.is_feed;
        if (data.is_feed) {
          feedPicker.hide();
          state.rssListing = data.listing;
          note('feed-notes', 'ok', 'This is an RSS feed. Quasarr reads its names, links and dates on its own.');
          return;
        }
        feedPicker.load(data);
        var listing = (config.definition && !state.feedLoadedOnce && draft.list) || data.listing || {};
        state.feedLoadedOnce = true;
        feedPicker.setListing(listing, data.best ? data.best.fields : {});
        if (!data.best) {
          note('feed-notes', 'warn', 'Quasarr found no release list on this page. Check the address, or click Pick next to Release block and then one release.');
        }
      });
  }
  function feedListing() { return state.feedIsRss ? state.rssListing : feedPicker.listing(); }

  // --- results tables -------------------------------------------------------------
  function resultsTable(target, rows, columns) {
    var table = el('table');
    var head = el('tr');
    columns.forEach(function(column) { head.appendChild(el('th', {scope: 'col', text: column.label})); });
    table.appendChild(el('thead', {}, [head]));
    var body = el('tbody');
    rows.forEach(function(row) {
      var tr = el('tr');
      columns.forEach(function(column) { tr.appendChild(el('td', {text: column.value(row)})); });
      body.appendChild(tr);
    });
    table.appendChild(body);
    $(target).appendChild(table);
  }
  function sizeText(mb) { return mb ? (mb >= 1024 ? (mb / 1024).toFixed(1) + ' GB' : mb + ' MB') : 'not shown'; }
  function dateText(value) { var d = new Date(value); return isNaN(d) ? value : d.toLocaleString(); }
  var RELEASE_COLUMNS = [
    {label: 'Name', value: function(r) { return r.title; }},
    {label: 'Size', value: function(r) { return sizeText(r.size_mb); }},
    {label: 'Date', value: function(r) { return dateText(r.date); }},
    {label: 'IMDb', value: function(r) { return r.imdb_id || ''; }}
  ];
  function skippedText(data) {
    var reasons = Object.keys(data.skipped || {}).map(function(reason) { return data.skipped[reason] + ' × ' + reason; });
    return reasons.length ? ' Skipped: ' + reasons.join(', ') + '.' : '';
  }

  // --- the definition being built ---------------------------------------------------
  // what the wizard edits; everything else a definition carries is kept as is
  var MANAGED = ['key', 'name', 'hostname', 'language', 'flaresolverr', 'feeds', 'list', 'search', 'search_list', 'download'];
  function definition() {
    var kept = {};
    Object.keys(draft).forEach(function(name) { if (MANAGED.indexOf(name) < 0) kept[name] = draft[name]; });
    var result = Object.assign(kept, {
      name: $('w-name').value.trim(),
      hostname: host(),
      language: $('w-language').value,
      flaresolverr: $('w-flaresolverr').checked,
      feeds: selectedCategories().map(function(category) {
        return {category: category.id, url: 'https://{host}' + ensureSlash(feedUrls[category.id])};
      }),
      // options the wizard has no field for, as a title cleanup, stay
      list: Object.assign({}, draft.list || {}, feedListing())
    });
    if (draft.key) result.key = draft.key;
    var search = searchSettings();
    if (search) {
      result.search = Object.assign({}, draft.search || {}, search);
      var own = searchLayout();
      if (own) result.search_list = Object.assign({}, draft.search_list || {}, own);
    }
    result.download = Object.assign({}, draft.download || {}, downloadSettings());
    return result;
  }

  $('feed-test').onclick = function() {
    clear('feed-results');
    var categories = selectedCategories();
    if (!categories.length) { note('feed-results', 'error', 'Choose at least one kind of release.'); return; }
    var done = busy($('feed-test'), 'Testing…');
    var current = definition();
    Promise.all(categories.map(function(category) {
      return api('/api/custom-sources/preview', {definition: current, step: 'feed', category: category.id})
        .then(function(data) { return {category: category, data: data}; });
    })).then(function(results) {
      done();
      var allGood = true;
      state.feedRows = [];
      results.forEach(function(run) {
        var data = run.data;
        var problem = !data.success ? (data.error || 'the test failed') : data.issue;
        if (problem) {
          allGood = false;
          note('feed-results', 'error', run.category.name + ': ' + problem + '.' + (data.success ? skippedText(data) : ''));
          return;
        }
        note('feed-results', 'ok', run.category.name + ': ' + data.parsed + ' releases read.' + skippedText(data));
        resultsTable('feed-results', data.rows.slice(0, 10), RELEASE_COLUMNS);
        state.feedRows = state.feedRows.concat(data.rows);
      });
      setFeedTested(allGood);
      if (allGood) $('feed-next').focus();
    });
  };
  setFeedTested(state.feedOk);
  $('feed-next').onclick = function() { show('search'); };

  // --- step 3: search -----------------------------------------------------------------
  var searchPicker = createPicker('search-picker', 'search-notes', 'Results page',
    'These fields read the results page. They only apply when the results use their own layout.');
  searchPicker.onEdit = function() { setLayout('own'); };
  var search = draft.search || {};
  if (search.mode) document.querySelector('input[name="w-mode"][value="' + search.mode + '"]').checked = true;
  $('w-method').value = search.method || 'get';
  $('w-search-url').value = search.url ? path(search.url) : '';
  $('w-search-body').value = search.body || '';
  $('w-phrase').checked = !!search.phrase;
  $('w-method').onchange = function() { $('w-body-wrap').hidden = $('w-method').value !== 'post'; };
  $('w-method').onchange();
  if (search.url) $('search-manual').open = true;
  state.searchList = draft.search_list || null;
  if (state.searchList) setLayout('own');

  function setLayout(value) {
    $('search-layouts').hidden = false;
    document.querySelector('input[name="w-layout"][value="' + value + '"]').checked = true;
  }
  document.querySelectorAll('input[name="w-layout"]').forEach(function(radio) {
    radio.onchange = function() {
      if (radio.value === 'same' && radio.checked && searchPicker.loaded()) searchPicker.setListing(feedListing());
    };
  });
  function searchLayout() {
    var own = document.querySelector('input[name="w-layout"]:checked').value === 'own';
    if (!own) return null;
    return searchPicker.loaded() ? searchPicker.listing() : state.searchList;
  }
  function searchSettings() {
    var mode = document.querySelector('input[name="w-mode"]:checked').value;
    var phrase = $('w-phrase').checked;
    var url = $('w-search-url').value.trim();
    if ((mode === 'off' && !phrase) || !url) return null;
    var settings = {
      mode: mode,
      phrase: phrase,
      method: $('w-method').value,
      url: 'https://{host}' + ensureSlash(url),
      categories: selectedCategories().map(function(category) { return category.id; })
    };
    if (settings.method === 'post') settings.body = $('w-search-body').value.trim();
    return settings;
  }

  $('search-discover').onclick = function() {
    clear('search-notes');
    var first = selectedCategories()[0];
    if (!first) { note('search-notes', 'error', 'Set up the newest releases first.'); return; }
    var done = busy($('search-discover'), 'Trying search addresses…');
    var waiting = note('search-notes', 'busy', 'Quasarr searches the site for one of its newest releases. This can take up to a minute.');
    api('/api/custom-sources/suggest-search', {hostname: host(), feed_url: ensureSlash(feedUrls[first.id]), list: feedListing()})
      .then(function(data) {
        done();
        waiting.remove();
        if (!data.success) {
          note('search-notes', 'warn', (data.error || 'No search found') + '. Open the search settings below and enter the search address of the site.');
          $('search-manual').open = true;
          return;
        }
        $('w-method').value = data.search.method;
        $('w-method').onchange();
        $('w-search-url').value = path(data.search.url);
        $('w-search-body').value = data.search.body || '';
        document.querySelector('input[name="w-mode"][value="' + data.mode + '"]').checked = true;
        $('w-phrase').checked = selectedCategories().some(function(c) { return c.id === 3000 || c.id === 7000; });
        state.searchList = data.search_list;
        setLayout(data.search_list ? 'own' : 'same');
        note('search-notes', 'ok', 'Found it: searching for “' + data.query + '” returned that release. ' + data.mode_note + '.');
        $('search-query').value = data.query;
        $('search-load').click();
      });
  };

  $('search-load').onclick = function() {
    clear('search-results');
    var settings = searchSettings();
    var query = $('search-query').value.trim();
    if (!settings) { note('search-results', 'error', 'Enter a search address in the search settings first.'); $('search-manual').open = true; return; }
    if (!query) { note('search-results', 'error', 'Enter something to search for.'); $('search-query').focus(); return; }
    var done = busy($('search-load'), 'Loading…');
    api('/api/custom-sources/page', {hostname: host(), url: '/', search: settings, query: query, purpose: 'search',
      flaresolverr: $('w-flaresolverr').checked}).then(function(data) {
      done();
      if (!data.success) { note('search-results', 'error', 'Could not load the results: ' + data.error + '.'); return; }
      searchPicker.load(data);
      var own = document.querySelector('input[name="w-layout"]:checked').value === 'own';
      if (own && state.searchList) { searchPicker.setListing(state.searchList, data.best ? data.best.fields : {}); return; }
      // does the newest-releases layout read the results page?
      searchPicker.setListing(feedListing(), data.best ? data.best.fields : {});
      searchPicker.refresh().then(function(marked) {
        var items = marked && marked.success ? marked.items.length : 0;
        var titles = items ? (marked.fields.title || []).length : 0;
        if (items && titles === items) {
          setLayout('same');
          note('search-results', 'ok', 'The results look like the newest releases, so the same fields read them.');
        } else {
          setLayout('own');
          searchPicker.setListing(data.listing || {}, data.best ? data.best.fields : {});
          note('search-results', 'warn', data.listing
            ? 'The results are laid out differently. Quasarr suggested fields for them below; check them before testing.'
            : 'The results are laid out differently and Quasarr found no list on them. Pick a release block below.');
        }
      });
    });
  };

  $('search-test').onclick = function() {
    clear('search-results');
    var query = $('search-query').value.trim();
    var settings = searchSettings();
    if (!settings) { note('search-results', 'error', 'Enter a search address in the search settings first.'); $('search-manual').open = true; return; }
    if (!query) { note('search-results', 'error', 'Enter an IMDb ID such as tt0111161 or a title.'); $('search-query').focus(); return; }
    var done = busy($('search-test'), 'Searching…');
    api('/api/custom-sources/preview', {definition: definition(), step: 'search', query: query, category: selectedCategories()[0].id})
      .then(function(data) {
        done();
        if (!data.success) {
          var reason = data.error || 'the search failed';
          note('search-results', 'error', reason + '.');
          return;
        }
        var works = data.quality && data.quality.works;
        var text = data.parsed + ' results.' + skippedText(data);
        if (data.quality && data.quality.same_as_feed) text += ' They look like the front page, so the site may ignore the search.';
        else if (!works && data.parsed) text += ' None of them names what you searched for.';
        if (data.issue && !data.parsed) text = data.issue + '.' + skippedText(data);
        note('search-results', works ? 'ok' : 'warn', text);
        resultsTable('search-results', data.rows.slice(0, 10), RELEASE_COLUMNS);
      });
  };
  $('search-next').onclick = function() { show('download'); };

  // --- step 4: downloads ---------------------------------------------------------------
  var download = draft.download || {};
  var links = download.links || {};
  $('w-download-selector').value = links.selector || '';
  $('w-mirror').value = links.mirror || 'text';
  $('w-redirects').checked = !!download.redirects;
  $('w-userscript').checked = !!download.userscript;
  $('userscript-box').open = !!download.userscript;
  function downloadSettings() {
    var selector = $('w-download-selector').value.trim();
    // link options the wizard does not show stay; only the selector is the wizard's
    var links = Object.assign({}, (draft.download || {}).links || {});
    delete links.selector;
    if (selector) Object.assign(links, {selector: selector, mirror: $('w-mirror').value});
    return {
      links: links,
      redirects: !!selector && $('w-redirects').checked,
      userscript: $('w-userscript').checked
    };
  }
  function prepareDownload() {
    clear('download-notes');
    var select = $('download-release');
    var keep = select.value;
    select.textContent = '';
    var pages = state.feedRows.filter(function(row) { return onSite(row.link); });
    if (state.feedRows.length && !pages.length) {
      note('download-notes', 'ok', 'The releases link straight to their download containers, so there is nothing to set up here.');
      $('download-setup').hidden = true;
      return;
    }
    $('download-setup').hidden = false;
    pages.slice(0, 25).forEach(function(row) { select.appendChild(el('option', {value: row.link, text: row.title})); });
    if (keep) select.value = keep;
    if (!pages.length) note('download-notes', 'warn', 'Test the newest releases first, then pick one of them here.');
  }
  $('download-load').onclick = function() {
    clear('download-notes');
    clear('download-chips');
    var url = $('download-release').value;
    if (!url) return;
    var done = busy($('download-load'), 'Opening…');
    api('/api/custom-sources/page', {hostname: host(), url: url, purpose: 'download', flaresolverr: $('w-flaresolverr').checked})
      .then(function(data) {
        done();
        if (!data.success) { note('download-notes', 'error', 'Could not open the release: ' + data.error + '.'); return; }
        var found = data.download || [];
        if (!found.length) {
          note('download-notes', 'warn', 'Quasarr found no download or container links on this page. Enter a CSS selector for them.');
          return;
        }
        found.forEach(function(candidate, index) {
          var chip = el('button', {type: 'button', className: 'chip', title: candidate.spec.selector,
            text: candidate.spec.selector + ' · ' + candidate.known + (candidate.known === 1 ? ' link' : ' links')});
          chip.onclick = function() {
            $('w-download-selector').value = candidate.spec.selector;
            $('w-mirror').value = candidate.spec.mirror;
            $('w-redirects').checked = !!candidate.spec.redirects;
            document.querySelectorAll('#download-chips .chip').forEach(function(c) { c.classList.remove('selected'); });
            chip.classList.add('selected');
          };
          $('download-chips').appendChild(chip);
          if (index === 0 && !$('w-download-selector').value) chip.click();
        });
      });
  };
  $('download-test').onclick = function() {
    clear('download-results');
    var url = $('download-release').value;
    if (!url || !$('w-download-selector').value.trim()) {
      note('download-results', 'error', 'Open a release page and choose its download links first.');
      return;
    }
    var done = busy($('download-test'), 'Collecting links…');
    api('/api/custom-sources/test-download', {definition: definition(), url: url}).then(function(data) {
      done();
      if (!data.success) { note('download-results', 'error', (data.error || 'No links found') + '.'); return; }
      var groups = data.classified || {};
      note('download-results', 'ok', data.links.length + ' links: ' + (groups.protected || []).length + ' need a CAPTCHA, ' +
        (groups.auto || []).length + ' decrypt on their own, ' + (groups.direct || []).length + ' go straight to a hoster.');
      resultsTable('download-results', data.links, [
        {label: 'Mirror', value: function(link) { return link[1]; }},
        {label: 'Address', value: function(link) { return link[0]; }}
      ]);
    });
  };
  $('download-next').onclick = function() { show('save'); };

  // --- step 5: save ----------------------------------------------------------------------
  function renderSummary() {
    var current = definition();
    var list = $('summary');
    list.textContent = '';
    function line(term, value) { list.appendChild(el('dt', {text: term})); list.appendChild(el('dd', {text: value})); }
    line('Name', current.name);
    line('Hostname', current.hostname);
    line('Newest releases', current.feeds.map(function(feed) {
      var category = config.categories.filter(function(c) { return c.id === feed.category; })[0];
      return category.name + ': ' + path(feed.url);
    }).join(', ') || 'None');
    var s = current.search;
    line('Search', s ? s.method.toUpperCase() + ' ' + path(s.url) + ', by ' + (s.mode === 'imdb' ? 'IMDb ID' : (s.mode === 'title' ? 'title' : 'name only')) +
      (current.search_list ? ', results read with their own fields' : '') : 'Off');
    line('Downloads', current.download.userscript ? 'Your own userscript collects the links'
      : (current.download.links && current.download.links.selector) || 'Releases link to their containers');
    clear('save-notes');
    if (!state.feedOk) note('save-notes', 'warn', 'The newest releases have not passed a test yet.');
  }
  $('save').onclick = function() {
    clear('save-notes');
    var done = busy($('save'), 'Saving…');
    api('/api/custom-sources', definition()).then(function(data) {
      done();
      if (!data.success) { note('save-notes', 'error', 'Could not save: ' + plain(data.error) + '.'); return; }
      draft.key = data.source.key;
      var box = note('save-notes', 'ok', 'Saved as ' + data.source.key.toUpperCase() + '. Quasarr uses it from the next feed and search on. ');
      box.appendChild(el('button', {type: 'button', className: 'btn-secondary chip-button', text: 'Back to your sites', onclick: function() { window.location.href = config.sites_url; }}));
      $('save').textContent = 'Save changes';
    });
  };

  if (config.definition) {
    renderFeedRows();
    setFeedTested(!config.imported);
  }
  show('site');
})();
</script>
"""
