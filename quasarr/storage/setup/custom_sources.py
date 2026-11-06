# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

"""The site wizard: users add sites Quasarr does not ship a template for.

Everything a site returns is untrusted. The page shows it only through
``textContent`` and element properties. The site preview renders in a
sandboxed frame that runs only Quasarr's picker script and follows no links.
"""

import html
import re

from bottle import abort

from quasarr.providers.html_templates import json_for_script, render_form
from quasarr.search.sources.helpers.custom_suggest import FIELD_COLORS
from quasarr.storage.custom_sources import load_definitions

_KEY_REGEX = re.compile(r"^[c-z][1-9]$")

# Quasarr categories a user site can serve, in the order the wizard shows them
WIZARD_CATEGORIES = [
    {"id": 2000, "name": "Movies"},
    {"id": 5000, "name": "TV shows"},
    {"id": 3000, "name": "Music"},
    {"id": 7000, "name": "Books"},
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
    return render_form(title, body, _WIZARD_SCRIPT + _WIZARD_STYLE + _PART_STYLE)


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
    <li data-step="feed"><button type="button">Feed</button></li>
    <li data-step="search"><button type="button">Search</button></li>
    <li data-step="download"><button type="button">Downloads</button></li>
    <li data-step="save"><button type="button">Save</button></li>
  </ol>

  <section class="wizard-step" data-step="site">
    <p class="wizard-lead">Tell Quasarr where the site is. Nothing is saved until the last step.</p>
    <p class="hint">A site you set up is yours to maintain, and issues about it are not supported.
      Sites that need a login cannot be set up here: they need Python code, contributed as a pull request.</p>
    <label for="w-hostname">Hostname</label>
    <input id="w-hostname" autocomplete="off" autocorrect="off" spellcheck="false" placeholder="example.org">
    <p class="hint">The address you open in your browser, without https://.</p>
    <label for="w-name">Name</label>
    <input id="w-name" maxlength="60" autocomplete="off" placeholder="My site">
    <p class="hint">Only shown inside Quasarr. Filled in from the hostname until you change it.</p>
    <label for="w-language">Language of its releases</label>
    <select id="w-language">
      <option value="en">English</option>
      <option value="de">German</option>
      <option value="es">Spanish</option>
      <option value="fr">French</option>
      <option value="it">Italian</option>
      <option value="pt">Portuguese</option>
      <option value="nl">Dutch</option>
      <option value="pl">Polish</option>
      <option value="sv">Swedish</option>
      <option value="tr">Turkish</option>
      <option value="ru">Russian</option>
      <option value="ar">Arabic</option>
      <option value="hi">Hindi</option>
      <option value="zh">Chinese</option>
      <option value="ja">Japanese</option>
      <option value="ko">Korean</option>
    </select>
    <!-- set when the site shows a browser check, never by hand -->
    <input type="checkbox" id="w-flaresolverr" hidden style="display: none">
    <div class="button-row left">
      <button type="button" class="btn-secondary" id="import-open">Import a template someone shared</button>
    </div>
    <div id="import-box" hidden>
      <p class="hint">Paste the template as JSON or the template file a share produced. You test every step before you save.</p>
      <textarea id="w-import" rows="10" spellcheck="false" autocomplete="off" aria-label="Template"
        placeholder="{&quot;name&quot;: …}"></textarea>
      <div class="wizard-notes" id="import-notes" aria-live="polite"></div>
    </div>
    <div class="wizard-notes" id="site-notes" aria-live="polite"></div>
    <div class="button-row">
      <button type="button" class="btn-primary" id="site-next">Continue</button>
    </div>
  </section>

  <section class="wizard-step" data-step="feed" hidden>
    <p class="wizard-lead">Choose what the site offers and the page listing the newest releases of each kind.
      Quasarr fills them in from the site menu and tests them on its own.</p>
    <div id="feed-categories" class="category-grid"></div>
    <div class="wizard-notes" id="feed-info" aria-live="polite"></div>
    <div id="feed-rows"></div>
    <div class="feed-row inline">
      <label for="feed-page">Set up on</label>
      <select id="feed-page"></select>
    </div>
    <div class="wizard-notes" id="feed-notes" aria-live="polite"></div>
    <div id="feed-picker"></div>
    <div class="results" id="feed-results" aria-live="polite"></div>
    <div class="button-row">
      <button type="button" class="btn-secondary" data-back>Back</button>
      <button type="button" class="btn-secondary" id="feed-test">Test feed</button>
      <button type="button" class="btn-primary" id="feed-next" disabled title="Test the feed first">Continue</button>
    </div>
  </section>

  <section class="wizard-step" data-step="search" hidden>
    <p class="wizard-lead">Radarr and Sonarr search by IMDb ID. Quasarr sends that ID to the site, or the
      movie or show title when the site cannot find IDs. It finds the search on its own when this step opens.</p>
    <div class="button-row left">
      <button type="button" class="btn-primary" id="search-discover">Find the search for me</button>
    </div>
    <div class="wizard-notes" id="search-notes" aria-live="polite"></div>
    <details id="search-manual">
      <summary>Search settings</summary>
      <label for="w-method">Request</label>
      <select id="w-method"><option value="get">GET</option><option value="post">POST form</option></select>
      <label for="w-search-url">Search address</label>
      <input id="w-search-url" spellcheck="false" placeholder="/?s={q}">
      <p class="hint">{q} is replaced by what Quasarr searches for.</p>
      <div id="w-body-wrap" hidden>
        <label for="w-search-body">Form fields</label>
        <input id="w-search-body" spellcheck="false" placeholder="search={q}">
      </div>
    </details>
    <label>Search with</label>
    <div class="radio-row" id="search-modes">
      <label class="check"><input type="radio" name="w-mode" value="imdb" checked> IMDb ID</label>
      <label class="check"><input type="radio" name="w-mode" value="title"> Title</label>
      <label class="check"><input type="radio" name="w-mode" value="off"> No search</label>
    </div>
    <p class="hint">Quasarr chooses this on its own: IMDb ID when the feed shows IMDb IDs, otherwise the title
      of the movie or show in the language below. When the test finds nothing by IMDb ID, it switches to the title.
      Music and books are always searched by name.</p>
    <label for="w-search-language">Titles in</label>
    <select id="w-search-language"></select>
    <p class="hint">The language of the site's releases. Title searches use the movie or show title in it,
      as German sites list German titles. Titles in a script Quasarr cannot search, as Cyrillic or Chinese,
      fall back to the English title.</p>
    <div id="search-results-setup">
      <h4>Results page</h4>
      <p class="hint">Each kind is searched for its newest release from the feed, so the search should find it again.
        Change it to anything the site lists: movies and shows take an IMDb ID, so type a title and press Grab IMDb ID.
        Search results are often laid out differently from the feed; the results page below shows how they are read.</p>
      <div id="search-queries"></div>
      <div class="button-row left">
        <button type="button" class="btn-secondary" id="search-test">Test search</button>
      </div>
      <div class="feed-row inline">
        <label for="search-page">Results page for</label>
        <select id="search-page"></select>
      </div>
      <div class="wizard-notes" id="search-layout" aria-live="polite"></div>
      <div class="radio-row" id="search-layouts" hidden>
        <label class="check"><input type="radio" name="w-layout" value="same" checked> Results look like the feed</label>
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
      <select id="download-release"></select>
      <label for="download-choice">Download links</label>
      <div class="field-inputs">
        <select id="download-choice" class="suggest"><option value="own">Not chosen yet: click Pick</option></select>
        <button type="button" class="btn-secondary pick" id="download-pick">Pick</button>
      </div>
      <input type="hidden" id="w-download-selector">
      <div class="preview-wrap" id="download-preview" hidden>
        <div class="preview-bar" id="download-bar"><span>Preview of the release page. Blue frames are the download links.</span></div>
        <iframe sandbox="allow-scripts" referrerpolicy="no-referrer" title="Release page preview"></iframe>
      </div>
      <label for="w-mirror">Name each link after</label>
      <select id="w-mirror">
        <option value="text">its link text</option>
        <option value="href_host">the address it points to</option>
        <option value="hoster_name">the hoster named in its text</option>
      </select>
      <input type="checkbox" id="w-redirects" hidden style="display: none">
      <p class="hint" id="redirect-note" hidden>These links point to the site itself and redirect to the download. Quasarr follows them.</p>
      <div class="button-row left">
        <button type="button" class="btn-secondary" id="download-test">Test links</button>
      </div>
      <div class="results" id="download-results" aria-live="polite"></div>
    </div>
    <details class="wizard-more" id="userscript-box" hidden>
      <summary>The links only appear in a browser, after a CAPTCHA or a click</summary>
      <p>Quasarr can hand each release page to a userscript you write. When your app grabs a release, the CAPTCHA page
        opens it in your browser, and your script sends the links back.</p>
      <p><strong>This needs your own JavaScript.</strong> Install <a href="https://www.tampermonkey.net/" target="_blank" rel="noopener noreferrer">Tampermonkey</a>
        first, then the <a href="/captcha/custom.user.js" target="_blank">userscript template</a>. The template does not work out of the box:
        it only connects the page to Quasarr, and you add the code that finds the links. It never updates itself, so your code stays.</p>
      <label class="check"><input type="checkbox" id="w-userscript"> OK, I set up my userscript for this site</label>
    </details>
    <div class="button-row">
      <button type="button" class="btn-secondary" data-back>Back</button>
      <button type="button" class="btn-primary" id="download-next">Continue</button>
    </div>
  </section>

  <section class="wizard-step" data-step="save" hidden>
    <dl class="summary" id="summary"></dl>
    <div class="wizard-notes" id="save-notes" aria-live="polite"></div>
    <h4>Template</h4>
    <p class="hint">What Quasarr saves, without the hostname. Export it to share it, or contribute it in a pull request.</p>
    <textarea id="w-template" rows="14" readonly spellcheck="false" aria-label="Template"></textarea>
    <div class="button-row left">
      <button type="button" class="btn-secondary" id="template-export">Export template</button>
    </div>
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
  .wizard-more[hidden] { display: none; }
  #w-template { width: 100%; box-sizing: border-box; resize: vertical; font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    font-size: .8rem; background: var(--code-bg); }
  .wizard-more textarea { width: 100%; box-sizing: border-box; font-family: ui-monospace, monospace; font-size: .85rem; }
  .wizard .visually-hidden { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); }
  .wizard-lead { margin-top: 0; }
  /* focused only so screen readers announce a new step */
  .wizard-lead:focus { outline: none; }
  #w-import { display: block; width: 100%; max-width: 100%; box-sizing: border-box; resize: none;
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: .85rem; }
  .wizard-step[inert] button, .wizard-step[inert] select, .wizard-step[inert] input { opacity: .6; }
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
  .note.busy { color: var(--text-muted); display: flex; align-items: center; gap: .5rem; }
  .note.busy::before { content: ""; flex: 0 0 auto; width: .9rem; height: .9rem; border-radius: 50%;
    border: 2px solid var(--border-color); border-top-color: var(--primary); animation: q-spin .8s linear infinite; }
  @keyframes q-spin { to { transform: rotate(360deg); } }
  @media (prefers-reduced-motion: reduce) { .note.busy::before { animation-duration: 3s; } }
  .category-grid { display: flex; flex-wrap: wrap; gap: .25rem 1rem; }
  .feed-row { display: grid; grid-template-columns: 8rem 1fr auto; gap: .5rem; align-items: center; margin: .4rem 0; }
  .picker { display: grid; grid-template-columns: minmax(0, 26rem) minmax(0, 1fr); gap: 1rem; align-items: start; }
  .picker > * { min-width: 0; }
  @media (max-width: 900px) { .picker { grid-template-columns: minmax(0, 1fr); } }
  @media (max-width: 600px) {
    .field-inputs { flex-wrap: wrap; }
    .wizard .inline { flex-wrap: wrap; }
    .wizard .inline input, .wizard .inline select { flex: 1 1 100%; }
    .feed-row.inline > span, .feed-row.inline > label { flex: 1 1 100%; }
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
  .field-row.active { border-color: var(--part); box-shadow: 0 0 0 2px var(--part); }
  .field-row .field-name::before { content: ""; display: inline-block; width: .7rem; height: .7rem;
    border-radius: 50%; background: var(--part); margin-right: .4rem; vertical-align: baseline; }
  .field-row .suggest { border-left: 4px solid var(--part); }
  tr.skipped td { color: var(--text-muted); font-style: italic; }
  tr.skipped td:last-child { color: var(--error-color); font-style: normal; }
  .field-name { font-weight: 600; }
  .field-inputs { display: flex; gap: .35rem; margin-top: .35rem; }
  .field-inputs select { flex: 0 0 8.5rem; width: auto; }
  .field-inputs .pick { flex: 0 0 auto; }
  .field-count { display: block; font-size: .8rem; color: var(--text-muted); margin-top: .25rem; }
  .field-count.good { color: var(--success-color); }
  .field-count.bad { color: var(--error-color); }
  .field-inputs .suggest { flex: 1 1 auto; min-width: 0; text-overflow: ellipsis; }
  .field-chips { display: flex; flex-wrap: wrap; gap: .3rem; margin-top: .35rem; }
  .chip { border: 1px solid var(--border-color); background: var(--code-bg); color: var(--fg-color);
    border-radius: 1rem; padding: .15rem .6rem; font-size: .8rem; cursor: pointer; max-width: 100%;
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .chip.selected { border-color: var(--primary); box-shadow: 0 0 0 1px var(--primary) inset; }
  .pick.picking { background: #f59f00; color: #000; border-color: #f59f00; }
  .preview-wrap { border: 1px solid var(--border-color); border-radius: .4rem; overflow: hidden; }
  .preview-bar { padding: .35rem .6rem; font-size: .8rem; background: var(--code-bg); color: var(--text-muted); }
  .preview-bar.picking { background: #f59f00; color: #000; }
  .preview-bar.refused { background: var(--error-color); color: #fff; }
  .kind-result { margin: 1rem 0; }
  .kind-result h5 { margin: 0 0 .35rem; font-size: .95rem; }
  .imdb-name { display: block; margin: -.2rem 0 .35rem 7.5rem; font-size: .85rem; color: var(--text-muted); }
  .imdb-name:empty { display: none; }
  @media (max-width: 600px) { .imdb-name { margin-left: 0; } }
  .preview-bar { display: flex; align-items: center; justify-content: space-between; gap: .5rem; }
  .release-navs { display: inline-flex; align-items: center; gap: .4rem; white-space: nowrap; }
  .release-navs[hidden] { display: none; }
  .release-nav { padding: .05rem .55rem; font-size: 1rem; line-height: 1.2; }
  .phase-tabs { display: flex; gap: .35rem; margin: .5rem 0 .75rem; }
  .phase-tab { background: var(--code-bg); color: var(--fg-color); border: 1px solid var(--border-color); }
  .phase-tab.active { background: var(--primary); color: #fff; border-color: var(--primary); }
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
  .feed-row.inline > span, .feed-row.inline > label { flex: 0 0 7rem; align-self: center; margin: 0; }
  .share-module { max-height: 22rem; overflow: auto; background: var(--code-bg); padding: .6rem; font-size: .8rem; text-align: left; }
</style>
"""

# the colors the preview marks each part with, also on its row and its result column
_PART_STYLE = (
    "<style>"
    + "".join(
        f'.field-row[data-field="{name}"]{{--part:{color}}}'
        f".col-{name}{{box-shadow:inset 0 -3px 0 {color}}}"
        f"td.col-{name}{{box-shadow:inset 3px 0 0 {color}40}}"
        for name, color in FIELD_COLORS.items()
    )
    + "</style>"
)

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
    {name: 'title', label: 'Release name', attrs: ['text', 'title']},
    {name: 'link', label: 'Release link', attrs: ['href']},
    {name: 'size', label: 'Size', attrs: ['text'], labelled: true},
    {name: 'date', label: 'Date', attrs: ['text', 'datetime'], labelled: true}
  ];
  var ATTR_NAMES = {text: 'text', title: 'title text', href: 'link address', datetime: 'date attribute'};
  var ORDER = ['site', 'feed', 'search', 'download', 'save'];
  var state = {feedByKind: {}, sentQueries: {}, step: 'site', reached: config.definition ? 4 : 0, feedRows: [], feedOk: !!config.definition && !config.imported,
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
  // the name follows the hostname, as "example" for example.org, until the user types one
  var nameTyped = false;
  $('w-name').addEventListener('input', function() { nameTyped = !!$('w-name').value.trim(); });
  $('w-hostname').addEventListener('input', function() {
    $('site-next').textContent = 'Continue';
    // the match notice belongs to the hostname it was found for
    if ($('site-matches')) clear('site-matches');
    if (nameTyped) return;
    var parts = host().split('.');
    var base = parts.length > 1 ? parts[parts.length - 2] : '';
    $('w-name').value = base ? base.charAt(0).toUpperCase() + base.slice(1) : '';
  });
  // while Quasarr sets a step up on its own, the step cannot be changed under it
  function lockStep(step, locked) {
    var section = document.querySelector('.wizard-step[data-step="' + step + '"]');
    if (locked) section.setAttribute('inert', '');
    else section.removeAttribute('inert');
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
    if (step === 'search') { renderSearchQueries(); $('w-search-language').value = $('w-language').value; }
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
    // the first step needs no announcement; later ones move focus to their text
    if (heading && state.shown) { heading.setAttribute('tabindex', '-1'); heading.focus({preventScroll: true}); }
    state.shown = true;
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
    // two steps: first the blocks that hold one release each, then the details inside one
    var picker = {page: null, picking: null, marked: {items: [], fields: {}, values: {}, options: {}},
      activeField: 'title', onEdit: null, phase: 'blocks', index: 0};
    var mount = $(mountId);
    // users choose from what the page offers or click it; selectors stay out of sight
    var itemChoice = el('select', {className: 'suggest', 'aria-label': 'Release block'},
      [el('option', {value: 'own', text: 'Not chosen yet: click Pick'})]);
    var itemInput = el('input', {type: 'hidden'});
    var itemPick = el('button', {type: 'button', className: 'btn-secondary pick', text: 'Pick'});
    var itemCount = el('span', {className: 'field-count'});
    var itemRow = el('div', {className: 'field-row', 'data-field': 'item'}, [
      el('span', {className: 'field-name', text: 'Release block'}),
      el('div', {className: 'field-inputs'}, [itemChoice, itemInput, itemPick]),
      itemCount
    ]);
    var toDetails = el('button', {type: 'button', className: 'btn-primary', text: 'Continue to the details'});
    var blocksBox = el('div', {}, [
      el('p', {className: 'hint', text: 'A release block is the part of the page that holds exactly one release: ' +
        'its name, its link and usually its size and date. Quasarr reads every block as one release, so choose ' +
        'the one that frames each release on its own, not the whole list and not just the name. Click Pick and ' +
        'then any release if no suggestion fits. Ads or notices that look alike are fine: Quasarr skips blocks ' +
        'without a release.'}),
      itemRow, toDetails
    ]);
    var rows = {};
    var fieldBox = el('div', {hidden: 'hidden'}, [
      el('p', {className: 'hint', text: 'Now show Quasarr where each detail sits inside a release. The preview shows ' +
        'one release at a time, starting with the first one that reads, usually the second, as the first block is often an ad ' +
        'or a notice. Use the arrows to check a few others: a choice should read the right value in all of them. ' +
        'Name and link are required; size and date help your apps choose between releases.'})
    ]);
    FIELDS.forEach(function(field) {
      var selector = el('input', {type: 'hidden'});
      var label = field.labelled ? el('input', {type: 'hidden'}) : null;
      var attr = el('select');
      field.attrs.forEach(function(name) { attr.appendChild(el('option', {value: name, text: ATTR_NAMES[name]})); });
      var pick = el('button', {type: 'button', className: 'btn-secondary pick', text: 'Pick'});
      var choice = el('select', {className: 'suggest', 'aria-label': field.label},
        [el('option', {value: 'own', text: 'Not chosen yet: click Pick'})]);
      var inputs = [choice, selector];
      if (label) inputs.push(label);
      inputs.push(pick);
      var row = el('div', {className: 'field-row', 'data-field': field.name}, [
        el('span', {className: 'field-name', text: field.label}),
        el('div', {className: 'field-inputs'}, inputs),
        el('span', {className: 'field-count'})
      ]);
      rows[field.name] = {row: row, selector: selector, label: label, attr: attr, pick: pick, field: field,
        choice: choice, suggestions: [], count: row.querySelector('.field-count')};
      row.addEventListener('focusin', function() { focusField(field.name); });
      pick.onclick = function() { startPicking(field.name, pick); };
      choice.onchange = function() {
        var candidate = rows[field.name].suggestions[Number(choice.value)];
        if (candidate) { writeSpec(field.name, candidate.spec); edited(); }
      };
      fieldBox.appendChild(row);
    });
    var cleanup = el('select', {'aria-label': 'Release names'});
    [['trim', 'Keep them as the site shows them'], ['dots', 'Release style: Name.2026.1080p-GROUP'],
     ['spaces', 'Replace spaces with dots'],
     ['scene', 'Rewrite them in scene style']].forEach(function(option) {
      cleanup.appendChild(el('option', {value: option[0], text: option[1]}));
    });
    cleanup.addEventListener('change', function() { edited(); });
    fieldBox.appendChild(el('div', {className: 'field-row'}, [
      el('label', {className: 'field-name', text: 'Release names'}), cleanup,
      el('span', {className: 'hint', text: 'Scene style also removes umlauts and brackets, which can hurt music and book names.'})
    ]));
    itemPick.onclick = function() { startPicking('item', itemPick); };
    var tabs = {
      blocks: el('button', {type: 'button', className: 'phase-tab', text: '1. Release blocks'}),
      details: el('button', {type: 'button', className: 'phase-tab', text: '2. Details'})
    };
    tabs.blocks.onclick = function() { setPhase('blocks'); };
    tabs.details.onclick = function() { setPhase('details'); };
    toDetails.onclick = function() { setPhase('details'); };
    var barText = el('span', {text: 'Preview of the loaded page'});
    var previous = el('button', {type: 'button', className: 'release-nav', text: '‹', 'aria-label': 'Previous release'});
    var next = el('button', {type: 'button', className: 'release-nav', text: '›', 'aria-label': 'Next release'});
    var position = el('span');
    var nav = el('span', {className: 'release-navs', hidden: 'hidden'}, [previous, position, next]);
    previous.onclick = function() { showRelease(picker.index - 1); };
    next.onclick = function() { showRelease(picker.index + 1); };
    var bar = el('div', {className: 'preview-bar'}, [barText, nav]);
    // scripts without same-origin: the picker script in the preview cannot reach this page
    var frame = el('iframe', {sandbox: 'allow-scripts', referrerpolicy: 'no-referrer', title: title + ' preview'});
    var box = el('div', {className: 'picker-box', hidden: 'hidden'}, [
      el('h4', {text: title}),
      el('p', {className: 'hint', text: hint}),
      el('div', {className: 'phase-tabs'}, [tabs.blocks, tabs.details]),
      el('div', {className: 'picker'}, [
        el('div', {className: 'picker-fields'}, [blocksBox, fieldBox]),
        el('div', {className: 'preview-wrap'}, [bar, frame])
      ])
    ]);
    mount.appendChild(box);

    function setPhase(phase) {
      if (phase === 'details' && !(picker.marked.items || []).length) {
        clear(notesId);
        note(notesId, 'warn', 'Choose the release block first.');
        return;
      }
      picker.stopPicking();
      picker.phase = phase;
      blocksBox.hidden = phase !== 'blocks';
      fieldBox.hidden = phase !== 'details';
      Object.keys(tabs).forEach(function(key) { tabs[key].classList.toggle('active', key === phase); });
      showRelease(picker.index);
    }
    // the release the details step shows
    function showRelease(index) {
      var count = (picker.marked.items || []).length;
      picker.index = count ? Math.max(0, Math.min(count - 1, index)) : 0;
      var details = picker.phase === 'details' && count > 0;
      nav.hidden = !details;
      position.textContent = 'Release ' + (picker.index + 1) + ' of ' + count;
      previous.disabled = picker.index === 0;
      next.disabled = picker.index >= count - 1;
      if (!picker.picking) barText.textContent = details ? 'One release of the loaded page' : 'Preview of the loaded page';
      syncChoices();
      paint();
    }

    var timer = null;
    function edited() {
      syncChoices();
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
      // "release": only the release name the text holds
      if (r.find) spec.find = r.find;
      // further ways to read it, tried when the first finds nothing
      return r.more && r.more.length ? [spec].concat(r.more) : spec;
    }
    function writeSpec(name, spec) {
      var r = rows[name];
      r.more = Array.isArray(spec) ? spec.slice(1) : [];
      spec = (Array.isArray(spec) ? spec[0] : spec) || {};
      r.selector.value = spec.selector || '';
      r.find = spec.find || '';
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
      cleanup.value = ['dots', 'spaces', 'scene'].indexOf(listing.title_cleanup) !== -1 ? listing.title_cleanup : 'trim';
      FIELDS.forEach(function(field) {
        writeSpec(field.name, listing[field.name]);
        rows[field.name].suggestions = ((suggestions || {})[field.name] || []).filter(function(candidate) { return candidate.spec; });
      });
      picker.index = -1;
      refresh();
    };
    picker.setItems = function(items) {
      picker.items = items || [];
      syncChoices();
    };
    itemChoice.onchange = function() {
      var candidate = picker.items[Number(itemChoice.value)];
      if (candidate) { itemInput.value = candidate.selector; picker.index = -1; edited(); }
    };
    function shown(name, value) {
      if (value === undefined || value === null || value === '') return '(nothing in this release)';
      if (name === 'size') return sizeText(Number(value));
      return name === 'date' ? dateText(value) : String(value);
    }
    function share(values) {
      var count = (values || []).length;
      var read = (values || []).filter(function(value) { return value !== null; }).length;
      return count ? Math.round(read / count * 100) + '% of releases' : '';
    }
    function sameSpec(a, b) {
      if (Array.isArray(a) || Array.isArray(b)) {
        a = [].concat(a || []); b = [].concat(b || []);
        return a.length === b.length && a.every(function(part, i) { return sameSpec(part, b[i]); });
      }
      var keys = ['selector', 'label', 'attr', 'find'];
      return keys.every(function(key) {
        var x = (a || {})[key], y = (b || {})[key];
        if (Array.isArray(x)) x = x[0];
        if (Array.isArray(y)) y = y[0];
        if (key === 'attr') { x = x || 'text'; y = y || 'text'; }
        return (x || '') === (y || '');
      });
    }
    // one option per suggestion, plus the user's own pick when it is none of them
    function fill(select, labels, matched, own) {
      select.textContent = '';
      labels.forEach(function(text, index) { select.appendChild(el('option', {value: String(index), text: text})); });
      if (matched === -1) select.appendChild(el('option', {value: 'own', text: own}));
      select.value = matched === -1 ? 'own' : String(matched);
    }
    // each option shows what it reads in the release on display
    function syncChoices() {
      var itemIndex = (picker.items || []).map(function(c) { return c.selector; }).indexOf(itemInput.value.trim());
      var found = (picker.marked.items || []).length;
      fill(itemChoice, (picker.items || []).map(function(candidate) {
        return candidate.selector + ' · ' + (candidate.count + candidate.mixed + candidate.empty) + ' blocks';
      }), itemIndex, itemInput.value.trim() ? 'Your pick · ' + found + ' blocks' : 'Not chosen yet: click Pick');
      FIELDS.forEach(function(field) {
        var r = rows[field.name];
        var spec = readSpec(field.name);
        var options = (picker.marked.options || {})[field.name] || [];
        var index = -1;
        r.suggestions.forEach(function(candidate, i) { if (index === -1 && sameSpec(candidate.spec, spec)) index = i; });
        var values = (picker.marked.values || {})[field.name];
        var set = Object.keys(spec).some(function(key) { return key !== 'attr'; });
        fill(r.choice, r.suggestions.map(function(candidate, i) {
          var read = options[i] || [];
          return shown(field.name, read[picker.index]) + ' · ' + share(read);
        }), index, !set ? 'Not chosen yet: click Pick'
          : 'Your pick · ' + shown(field.name, (values || [])[picker.index]) + ' · ' + share(values));
      });
    }
    picker.load = function(page) {
      picker.page = page;
      box.hidden = false;
      picker.setItems(page.items || []);
      picker.ready = false;
      picker.scrolled = false;
      frame.srcdoc = page.preview || '<!doctype html><p>No preview</p>';
      setPhase('blocks');
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
      var fields = {}, options = {};
      FIELDS.forEach(function(field) {
        fields[field.name] = listing[field.name] || {};
        options[field.name] = rows[field.name].suggestions.map(function(candidate) { return candidate.spec; });
      });
      return api('/api/custom-sources/highlight', {token: picker.page.token, item_selector: listing.item,
        fields: fields, options: options})
        .then(function(data) {
          if (!data.success) {
            setCount(itemCount, data.error, 'bad');
            return data;
          }
          picker.marked = data;
          var items = data.items.length;
          // the dropdowns tell what is read; only a problem needs a line of its own
          setCount(itemCount, !items ? 'Matches nothing on this page'
            : (items < 2 ? 'Matches only one block; a release block repeats for every release' : ''), 'bad');
          toDetails.disabled = !items;
          FIELDS.forEach(function(field) {
            var found = data.fields[field.name];
            var r = rows[field.name];
            if (found && found.error) { setCount(r.count, found.error, 'bad'); return; }
            // an optional field left empty is fine; one that reads nothing is not
            var unset = !Object.keys(listing[field.name] || {}).length;
            setCount(r.count, items && !unset && !(found || []).length ? 'Reads nothing in these releases' : '', 'bad');
          });
          showRelease(picker.index < 0 || picker.index >= items ? firstMatch(data, items) : picker.index);
          return data;
        });
    }
    picker.refresh = refresh;
    // the first release that reads, from the second on: the first block is often an ad
    picker.matches = function(title) { return !!title; };
    function firstMatch(data, count) {
      var titles = (data.values || {}).title || [];
      for (var i = 1; i < count; i++) if (picker.matches(titles[i])) return i;
      if (count && picker.matches(titles[0])) return 0;
      return count > 1 ? 1 : 0;
    }
    function tell(message) {
      if (picker.ready) frame.contentWindow.postMessage(message, '*');
    }
    function paint() {
      var items = picker.marked.items || [];
      var fields = {};
      FIELDS.forEach(function(field) {
        var found = (picker.marked.fields || {})[field.name];
        if (Array.isArray(found)) fields[field.name] = found;
      });
      var solo = picker.phase === 'details' && items.length ? items[picker.index] : null;
      tell({type: 'mark', items: items, fields: fields, shown: solo, scroll: !picker.scrolled});
      if (picker.ready && items.length) picker.scrolled = true;
    }
    function focusField(name) {
      picker.activeField = name;
      Object.keys(rows).forEach(function(key) { rows[key].row.classList.toggle('active', key === name); });
    }
    window.addEventListener('message', function(event) {
      if (event.source !== frame.contentWindow) return;
      var message = event.data || {};
      if (message.type === 'ready') {
        picker.ready = true;
        tell({type: 'picking', on: !!picker.picking});
        paint();
      } else if (message.type === 'pick' && picker.picking) {
        choose(Number(message.q));
      } else if (message.type === 'cancel') {
        picker.stopPicking();
      } else if (message.type === 'refused') {
        refused(message.reason);
      }
    });
    var refusedTimer = null;
    function refused(reason) {
      var text = {
        idle: picker.phase === 'details'
          ? 'Click Pick next to a detail first, then click that detail in this release.'
          : 'Click Pick next to Release block first, then any release in the preview.',
        outside: 'Only the release shown here can be picked. Use the arrows to see others.',
        nothing: 'There is nothing to pick there. Click the text or link itself.'
      }[reason] || reason;
      if (!text) return;
      clearTimeout(refusedTimer);
      bar.classList.add('refused');
      barText.textContent = text;
      refusedTimer = setTimeout(function() {
        bar.classList.remove('refused');
        barText.textContent = picker.picking ? pickingText(picker.picking)
          : (picker.phase === 'details' ? 'One release of the loaded page' : 'Preview of the loaded page');
      }, 5000);
    }
    function pickingText(name) {
      return name === 'item'
        ? 'Click anywhere inside one release. Press Esc to cancel.'
        : 'Click the ' + rows[name].field.label.toLowerCase() + ' of this release. Press Esc to cancel.';
    }
    function startPicking(name, button) {
      if (picker.picking === name) { picker.stopPicking(); return; }
      picker.stopPicking();
      picker.picking = name;
      picker.pickButton = button;
      tell({type: 'picking', on: true});
      button.classList.add('picking');
      button.textContent = 'Cancel';
      bar.classList.add('picking');
      barText.textContent = pickingText(name);
      if (name !== 'item') focusField(name);
      // on a narrow screen the preview sits below the fields
      if (window.matchMedia('(max-width: 900px)').matches) bar.scrollIntoView({behavior: 'smooth', block: 'start'});
    }
    picker.stopPicking = function() {
      if (!picker.picking) return;
      picker.picking = null;
      tell({type: 'picking', on: false});
      picker.pickButton.classList.remove('picking');
      picker.pickButton.textContent = 'Pick';
      bar.classList.remove('picking');
      barText.textContent = picker.phase === 'details' ? 'One release of the loaded page' : 'Preview of the loaded page';
    };
    document.addEventListener('keydown', function(event) { if (event.key === 'Escape') picker.stopPicking(); });
    function choose(q) {
      var name = picker.picking;
      api('/api/custom-sources/pick', {token: picker.page.token, q: q, kind: name === 'item' ? 'item' : 'field',
        field: name, item_selector: itemInput.value.trim()}).then(function(data) {
        if (!data.success) { refused(data.error); return; }
        picker.stopPicking();
        if (name === 'item') { itemInput.value = data.selector; picker.index = -1; }
        else writeSpec(name, data.spec);
        // a headline picked as the name is replaced or flagged; say so next to the preview
        if (data.note) refused(data.note);
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
  nameTyped = !!draft.name;
  if (!nameTyped && $('w-hostname').value) $('w-hostname').dispatchEvent(new Event('input'));
  $('w-language').value = draft.language || 'en';
  $('w-flaresolverr').checked = !!draft.flaresolverr;
  var matchBox = el('div', {className: 'wizard-notes', id: 'site-matches', 'aria-live': 'polite'});
  $('site-notes').parentNode.insertBefore(matchBox, $('site-notes'));

  function useTemplate(key, button) {
    if (!host()) { $('w-hostname').focus(); return; }
    var done = busy(button, 'Saving…');
    api('/api/sites/' + encodeURIComponent(key.toLowerCase()), {hostname: host()}, 'PUT').then(function(data) {
      done();
      clear('site-matches');
      if (!data.success) { note('site-matches', 'error', 'Could not use ' + key + ': ' + data.error + '.'); return; }
      // the built-in template is the whole setup: the wizard ends here
      document.querySelectorAll('.wizard-step').forEach(function(section) { section.hidden = true; });
      $('wizard-steps').hidden = true;
      $('wizard-steps').parentNode.appendChild(el('section', {className: 'wizard-done'}, [
        el('p', {className: 'wizard-lead', text: key + ' now reads ' + host() + '. It needs no further setup.'}),
        el('div', {className: 'button-row'}, [
          el('button', {type: 'button', className: 'btn-primary', text: 'Back to your sites',
            onclick: function() { window.location.href = config.sites_url; }})
        ])
      ]));
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
  // importing is a detour from the wizard, so it opens on top of it
  var importBox = $('import-box');
  var importButton = el('button', {type: 'button', className: 'btn-primary', id: 'import-apply', text: 'Import'});
  $('import-open').onclick = function() {
    showModal('Import a template', '', '<button type="button" class="btn-secondary" onclick="closeModal()">Close</button>');
    importBox.hidden = false;
    $('global-modal-content').appendChild(importBox);
    // Import sits next to Close, as the dialog's main action
    $('global-modal-buttons').insertBefore(importButton, $('global-modal-buttons').firstChild);
    $('w-import').focus();
  };
  importButton.onclick = function() {
    clear('import-notes');
    var text = $('w-import').value.trim();
    if (!text) { $('w-import').focus(); return; }
    var done = busy(importButton, 'Checking…');
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
    var waiting = note('site-notes', 'busy', 'Quasarr opens the site and looks through its menu for release pages. On a slow connection this takes a moment.');
    api('/api/custom-sources/page', {hostname: host(), url: '/', language: $('w-language').value,
      flaresolverr: $('w-flaresolverr').checked})
      .then(function(data) {
        done();
        waiting.remove();
        clear('site-matches');
        if (data.builtin && data.builtin.length) {
          note('site-matches', 'warn', ['Quasarr already reads this hostname as ' + data.builtin.join(', ') +
            '. Adding it again would list every release twice. See ', el('a', {href: config.sites_url, text: 'your sites'}), '.']);
        }
        if (data.templates && data.templates.length) {
          offerTemplates(data.templates.map(function(match) { return {key: match.key}; }),
            'A built-in template matches this site and read ' + data.templates[0].rows + ' of its releases:');
        }
        // a browser check in front of the site: load it through FlareSolverr and try again
        if (data.suggest_flaresolverr && !$('w-flaresolverr').checked) {
          $('w-flaresolverr').checked = true;
          $('site-next').click();
          return;
        }
        if (!data.success) { note('site-notes', 'error', 'Could not open the site: ' + data.error + '.'); return; }
        state.feedSuggest = data.feeds || {};
        // a matching template is shown first; the next click sets the site up anyway
        var matched = (data.builtin && data.builtin.length) || (data.templates && data.templates.length);
        if (matched && state.matchedHost !== host()) {
          state.matchedHost = host();
          $('site-next').textContent = 'Set it up anyway';
          return;
        }
        show('feed');
        if (!document.querySelector('#feed-rows .feed-row')) loadFeedDefaults();
      });
  };

  // --- step 2: feed --------------------------------------------------------------
  var feedPicker = createPicker('feed-picker', 'feed-notes', 'Release list',
    'The preview marks each part in the color of the dot next to it.');
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
    $('feed-next').title = ok ? '' : 'Test the feed first';
  }
  // a new site starts with the kinds its menu links to, each on its own page
  function loadFeedDefaults() {
    clear('feed-info');
    if ($('w-flaresolverr').checked) {
      note('feed-info', 'ok', 'The site shows a browser check before its pages, so Quasarr loads it through FlareSolverr.');
    }
    if (!selectedCategories().length) {
      var suggested = Object.keys(state.feedSuggest || {});
      suggested.forEach(function(id) {
        $('cat-' + id).checked = true;
        feedUrls[id] = state.feedSuggest[id];
      });
      if (!suggested.length) { $('cat-2000').checked = true; $('cat-5000').checked = true; }
    }
    renderFeedRows();
    state.autoTest = true;
    lockStep('feed', true);
    loadFeedPage($('feed-page').value);
  }
  function renderFeedRows() {
    var wrap = $('feed-rows');
    wrap.textContent = '';
    selectedCategories().forEach(function(category) {
      var input = el('input', {spellcheck: 'false', placeholder: '/', 'aria-label': category.name + ' page'});
      input.value = feedUrls[category.id] || '/';
      feedUrls[category.id] = input.value;
      input.oninput = function() { feedUrls[category.id] = input.value.trim() || '/'; setFeedTested(false); renderPageChoice(); };
      wrap.appendChild(el('div', {className: 'feed-row inline'}, [el('span', {text: category.name}), input]));
    });
    if (selectedCategories().length) {
      wrap.appendChild(el('p', {className: 'hint', text: 'The page listing the newest releases of each kind. ' +
        'Quasarr reads each kind from its own page, so a release lands in the right app. Enter / only for a kind the site has no page of its own for.'}));
    }
    renderPageChoice();
  }
  // the release list is set up on one page and must read all of them alike
  function renderPageChoice() {
    var select = $('feed-page');
    var current = select.value;
    select.textContent = '';
    var pages = [];
    selectedCategories().forEach(function(category) {
      var url = ensureSlash(feedUrls[category.id] || '/');
      var known = pages.filter(function(page) { return page[0] === url; })[0];
      if (known) known[1] += ', ' + category.name;
      else pages.push([url, category.name + (url === '/' ? ' (main page)' : ' (' + url + ')')]);
    });
    pages.forEach(function(page) { select.appendChild(el('option', {value: page[0], text: page[1]})); });
    // the first kind's page unless another one was chosen
    select.value = pages.some(function(page) { return page[0] === current; }) ? current : (pages[0] || [''])[0];
  }
  $('feed-page').onchange = function() { loadFeedPage($('feed-page').value); };
  function loadFeedPage(url) {
    clear('feed-notes');
    $('feed-page').disabled = true;
    var waiting = note('feed-notes', 'busy', 'Loading ' + url + ' and looking for its release list…');
    api('/api/custom-sources/page', {hostname: host(), url: url, flaresolverr: $('w-flaresolverr').checked})
      .then(function(data) {
        $('feed-page').disabled = false;
        waiting.remove();
        if (!data.success) {
          lockStep('feed', false);
          note('feed-notes', 'error', 'Could not load the page: ' + data.error + '.');
          return;
        }
        state.feedIsRss = data.is_feed;
        if (data.is_feed) {
          feedPicker.hide();
          state.rssListing = data.listing;
          lockStep('feed', false);
          note('feed-notes', 'ok', 'This is an RSS feed. Quasarr reads its names, links and dates on its own.');
          return;
        }
        feedPicker.load(data);
        // switching pages keeps what is set up; it has to read the other pages too
        var listing = state.feedLoadedOnce ? feedPicker.listing()
          : (config.definition && draft.list) || data.listing || {};
        // Radarr and Sonarr expect dotted release names
        var video = selectedCategories().some(function(c) { return c.id === 2000 || c.id === 5000; });
        if (!state.feedLoadedOnce && !config.definition && video && !listing.title_cleanup) {
          listing = Object.assign({}, listing, {title_cleanup: 'dots'});
        }
        state.feedLoadedOnce = true;
        feedPicker.setListing(listing, data.best ? data.best.fields : {});
        if (!data.best) {
          lockStep('feed', false);
          note('feed-notes', 'warn', 'Quasarr found no release list on this page. Check the address, or click Pick next to Release block and then one release.');
        } else if (state.autoTest) {
          state.autoTest = false;
          state.autoRun = true;
          $('feed-test').click();
        }
      });
  }
  function feedListing() { return state.feedIsRss ? state.rssListing : feedPicker.listing(); }

  // --- results tables -------------------------------------------------------------
  function resultsTable(target, rows, columns) {
    // a column only some tables need stays out until a row fills it
    columns = columns.filter(function(column) {
      return !column.optional || rows.some(function(row) { return column.value(row); });
    });
    var table = el('table');
    var head = el('tr');
    columns.forEach(function(column) {
      head.appendChild(el('th', {scope: 'col', text: column.label, className: column.field ? 'col-' + column.field : ''}));
    });
    table.appendChild(el('thead', {}, [head]));
    var body = el('tbody');
    rows.forEach(function(row) {
      var tr = el('tr', {className: row.skipped ? 'skipped' : ''});
      columns.forEach(function(column) {
        tr.appendChild(el('td', {text: column.value(row), className: column.field ? 'col-' + column.field : ''}));
      });
      body.appendChild(tr);
    });
    table.appendChild(body);
    (typeof target === 'string' ? $(target) : target).appendChild(table);
  }
  function sizeText(mb) { return mb ? (mb >= 1024 ? (mb / 1024).toFixed(1) + ' GB' : mb + ' MB') : 'not shown'; }
  function dateText(value) { var d = new Date(value); return isNaN(d) ? value : d.toLocaleString(); }
  // a skipped item shows the text its fields read, and why it was left out
  var RELEASE_COLUMNS = [
    {label: 'Name', field: 'title', value: function(r) { return r.skipped ? r.title || '—' : r.title; }},
    {label: 'Size', field: 'size', value: function(r) { return r.size_mb !== undefined ? sizeText(r.size_mb) : r.size || '—'; }},
    {label: 'Date', field: 'date', value: function(r) { return r.date ? dateText(r.date) : '—'; }},
    {label: 'IMDb', value: function(r) { return r.imdb_id || ''; }},
    {label: 'Skipped', optional: true, value: function(r) { return r.skipped || ''; }}
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
    // a test Quasarr started on its own explains itself instead of moving the page
    var auto = state.autoRun;
    state.autoRun = false;
    var current = definition();
    var waiting = note('feed-results', 'busy', 'Testing the release list on ' + categories.length +
      (categories.length === 1 ? ' page…' : ' pages…'));
    Promise.all(categories.map(function(category) {
      return api('/api/custom-sources/preview', {definition: current, step: 'feed', category: category.id})
        .then(function(data) { return {category: category, data: data}; });
    })).then(function(results) {
      done();
      waiting.remove();
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
        resultsTable('feed-results', (data.table || data.rows).slice(0, 10), RELEASE_COLUMNS);
        state.feedRows = state.feedRows.concat(data.rows);
        state.feedByKind[run.category.id] = data.rows;
      });
      setFeedTested(allGood);
      if (auto) lockStep('feed', false);
      if (allGood && auto) {
        // a summary at the top informs without stopping the user
        var read = results.map(function(run) { return run.category.name + ' ' + run.data.parsed; });
        note('feed-notes', 'ok', 'Quasarr set this up on its own: it found a page for each kind in the site menu, ' +
          'chose the release list and read releases from every page (' + read.join(', ') + '). ' +
          'Nothing is saved yet. Check its choices and the results below, then continue.');
      } else if (allGood) {
        $('feed-next').focus();
      }
    });
  };
  setFeedTested(state.feedOk);
  $('feed-next').onclick = function() {
    show('search');
    // like the newest releases, the search is found on its own the first time
    if (!state.searchTried && !$('w-search-url').value.trim()) {
      state.searchTried = true;
      state.autoSearch = true;
      lockStep('search', true);
      var picking = note('search-notes', 'busy', 'Quasarr sets up the search on its own. Step 1 of 3: picking examples from the feed…');
      examplesFromFeed().then(function() { picking.remove(); $('search-discover').click(); });
    }
  };

  // --- step 3: search -----------------------------------------------------------------
  var searchPicker = createPicker('search-picker', 'search-notes', 'Results page',
    'These fields read the results page. They only apply when the results use their own layout.');
  searchPicker.onEdit = function() { setLayout('own'); };
  var search = draft.search || {};
  if (search.mode) document.querySelector('input[name="w-mode"][value="' + search.mode + '"]').checked = true;
  $('w-method').value = search.method || 'get';
  $('w-search-url').value = search.url ? path(search.url) : '';
  $('w-search-body').value = search.body || '';
  $('w-method').onchange = function() { $('w-body-wrap').hidden = $('w-method').value !== 'post'; };
  $('w-method').onchange();
  if (search.url) $('search-manual').open = true;
  state.searchList = draft.search_list || null;
  if (state.searchList) setLayout('own');

  // the examples cli_tester.py searches with, well known enough that sites list them
  var SEARCH_EXAMPLES = {2000: 'tt0499549', 5000: 'tt0944947', 3000: 'Taylor Swift', 7000: 'PC Gamer UK'};
  var searchQueries = {};
  function isVideo(category) { return category.id === 2000 || category.id === 5000; }
  function renderSearchQueries() {
    var wrap = $('search-queries');
    wrap.textContent = '';
    selectedCategories().forEach(function(category) {
      var input = el('input', {spellcheck: 'false', placeholder: isVideo(category) ? 'tt0111161' : 'a name',
        'aria-label': 'Search ' + category.name + ' for'});
      if (!(category.id in searchQueries)) searchQueries[category.id] = SEARCH_EXAMPLES[category.id] || '';
      input.value = searchQueries[category.id];
      var named = el('span', {className: 'imdb-name'});
      var timer = null;
      input.oninput = function() {
        searchQueries[category.id] = input.value.trim();
        renderSearchPages();
        clearTimeout(timer);
        timer = setTimeout(function() { nameImdb(category, named); }, 400);
      };
      var parts = [el('span', {text: category.name}), input];
      if (isVideo(category)) {
        // a title typed into the box becomes its IMDb ID
        var grab = el('button', {type: 'button', className: 'btn-secondary', text: 'Grab IMDb ID'});
        grab.onclick = function() { grabImdb(category, input, grab, named); };
        input.addEventListener('keydown', function(event) {
          if (event.key === 'Enter') { event.preventDefault(); grab.click(); }
        });
        parts.push(grab);
      }
      wrap.appendChild(el('div', {className: 'feed-row inline'}, parts));
      if (isVideo(category)) {
        wrap.appendChild(named);
        nameImdb(category, named);
      }
    });
    renderSearchPages();
  }
  function grabImdb(category, input, button, named) {
    var title = input.value.trim();
    if (!title || /^tt\d{5,10}$/.test(title)) { nameImdb(category, named); return; }
    var done = busy(button, 'Grabbing…');
    api('/api/custom-sources/imdb-lookup', {term: title, kind: category.id === 5000 ? 'tv' : 'movie'}).then(function(data) {
      done();
      var hit = data.success && data.results[0];
      if (!hit) { named.textContent = data.success ? 'No IMDb ID found for “' + title + '”.' : data.error + '.'; return; }
      input.value = hit.imdb_id;
      searchQueries[category.id] = hit.imdb_id;
      named.textContent = hit.title + (hit.year ? ' (' + hit.year + ')' : '');
      renderSearchPages();
    });
  }
  // the results page of each kind can be shown, as each kind's page in the newest releases
  function renderSearchPages() {
    var select = $('search-page');
    var current = select.value;
    select.textContent = '';
    searchRuns().forEach(function(category) {
      select.appendChild(el('option', {value: String(category.id), text: category.name + ' (' + searchQueries[category.id] + ')'}));
    });
    if (select.querySelector('option[value="' + current + '"]')) select.value = current;
  }
  function siteQuery(id) { return state.sentQueries[id] || searchQueries[id]; }
  $('search-page').onchange = function() { loadResults(siteQuery(Number($('search-page').value)), true); };
  // what an IMDb ID stands for, so the examples are not just numbers
  function nameImdb(category, target) {
    var id = searchQueries[category.id];
    target.textContent = '';
    if (!/^tt\d{5,10}$/.test(id || '')) return;
    api('/api/custom-sources/imdb-lookup', {term: id, kind: category.id === 5000 ? 'tv' : 'movie'}).then(function(data) {
      if (searchQueries[category.id] !== id) return;
      var hit = data.success && data.results[0];
      target.textContent = hit ? hit.title + (hit.year ? ' (' + hit.year + ')' : '') : '';
    });
  }
  // the newest release of each kind is the example most likely found again;
  // a movie or show name becomes its IMDb ID through Radarr or Sonarr
  // "Movie.Title.Foobar.1080p-GRP" -> "Movie Title Foobar": the name ends where year,
  // episode, resolution, source, codec, language or the group begin
  var RELEASE_TAGS = new RegExp('[ ._-](?:(?:19|20)\\d{2}|S\\d{1,2}(?:E\\d{1,3})?|\\d{3,4}p|german|english|dl|multi|dubbed|' +
    'web(?:-?dl|rip)?|blu-?ray|bdrip|hdtv|dvdrip|remux|uhd|hdr|x26[45]|h\\.?26[45]|hevc|avc|complete|proper|repack)(?=[ ._-]|$)', 'i');
  function feedName(title) {
    var name = title.split(RELEASE_TAGS)[0].replace(/-[A-Za-z0-9]+$/, '');
    return name.replace(/[._]+/g, ' ').trim().split(/\s+/).slice(0, 6).join(' ');
  }
  function examplesFromFeed() {
    var withId = false;
    return Promise.all(selectedCategories().map(function(category) {
      var row = (state.feedByKind[category.id] || [])[0];
      var name = row ? feedName(row.title) : '';
      if (!name) return null;
      if (!isVideo(category)) { searchQueries[category.id] = name; return null; }
      if (row.imdb_id) { withId = true; searchQueries[category.id] = row.imdb_id; return null; }
      return api('/api/custom-sources/imdb-lookup', {term: name, kind: category.id === 5000 ? 'tv' : 'movie'})
        .then(function(data) {
          // the release year tells apart movies of the same name
          var year = (row.title.match(/[ ._-]((?:19|20)\d{2})(?:[ ._-]|$)/) || [])[1];
          var results = data.success ? data.results : [];
          var hit = results.filter(function(r) { return year && String(r.year) === year; })[0] || results[0];
          if (hit) searchQueries[category.id] = hit.imdb_id;
        });
    })).then(function() {
      // a site that shows no IMDb IDs on its releases most likely searches by title
      var video = selectedCategories().some(isVideo);
      state.titleFromFeed = video && !withId;
      if (state.titleFromFeed) document.querySelector('input[name="w-mode"][value="title"]').checked = true;
      renderSearchQueries();
    });
  }
  function searchRuns() {
    return selectedCategories().filter(function(category) { return searchQueries[category.id]; });
  }
  // the language is the site's; it is shown again here because title searches depend on it
  $('w-language').querySelectorAll('option').forEach(function(option) {
    $('w-search-language').appendChild(el('option', {value: option.value, text: option.textContent}));
  });
  $('w-search-language').onchange = function() { $('w-language').value = $('w-search-language').value; };
  $('w-language').addEventListener('change', function() { $('w-search-language').value = $('w-language').value; });

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
    // music and books have no IMDb ID: they are always searched by name
    var phrase = selectedCategories().some(function(c) { return c.id === 3000 || c.id === 7000; });
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
    if (!first) { note('search-notes', 'error', 'Set up the feed first.'); return; }
    var done = busy($('search-discover'), 'Trying search addresses…');
    var auto = state.autoSearch;
    state.autoSearch = false;
    var waiting = note('search-notes', 'busy', auto
      ? 'Quasarr sets up the search on its own. Step 1 of 3: finding the search address of the site…'
      : 'Quasarr searches the site for one of its newest releases. This can take up to a minute.');
    api('/api/custom-sources/suggest-search', {hostname: host(), feed_url: ensureSlash(feedUrls[first.id]), list: feedListing()})
      .then(function(data) {
        if (!data.success) {
          done();
          waiting.remove();
          lockStep('search', false);
          note('search-notes', 'warn', (data.error || 'No search found') + '. Open the search settings below and enter the search address of the site.');
          $('search-manual').open = true;
          return;
        }
        $('w-method').value = data.search.method;
        $('w-method').onchange();
        $('w-search-url').value = path(data.search.url);
        $('w-search-body').value = data.search.body || '';
        // the mode is not taken from the feed: the test tries IMDb IDs first
        state.searchList = data.search_list;
        setLayout(data.search_list ? 'own' : 'same');
        note('search-notes', 'ok', 'Found the search: searching for “' + data.query + '” returned that release.');
        if (!auto) { done(); waiting.remove(); loadResults(data.query); return; }
        // set up on its own: test every kind, then show a results page of one that worked;
        // the button stays busy until all of it is done
        state.discoverDone = done;
        $('search-notes').appendChild(waiting);
        state.searchProgress = waiting;
        state.autoRun = true;
        $('search-test').click();
      });
  };

  // a results page starts on a result that names what was searched for
  var VIDEO_RELEASE = /\d{3,4}p|x26[45]|h\.?26[45]|hevc|web-?(dl|rip)|blu-?ray|hdtv/i;
  function resultMatcher(query, video) {
    var words = String(query || '').toLowerCase().split(/[^a-z0-9äöüß]+/).filter(function(w) { return w.length > 2 && !/^tt\d+$/.test(w); });
    return function(title) {
      if (!title) return false;
      var name = String(title).toLowerCase().replace(/[._]+/g, ' ');
      return words.every(function(w) { return name.indexOf(w) !== -1; }) && (!video || VIDEO_RELEASE.test(name));
    };
  }
  function loadResults(query, keepResults) {
    if (!keepResults) clear('search-results');
    var kind = Number($('search-page').value);
    searchPicker.matches = resultMatcher(query, kind === 2000 || kind === 5000);
    var settings = searchSettings();
    if (!settings) { note('search-results', 'error', 'Enter a search address in the search settings first.'); $('search-manual').open = true; return Promise.resolve(); }
    if (!query) { note('search-results', 'error', 'Enter something to search for.'); return Promise.resolve(); }
    $('search-page').disabled = true;
    var done = function() { $('search-page').disabled = false; };
    return api('/api/custom-sources/page', {hostname: host(), url: '/', search: settings, query: query, purpose: 'search',
      flaresolverr: $('w-flaresolverr').checked}).then(function(data) {
      done();
      if (!data.success) { note('search-results', 'error', 'Could not load the results: ' + data.error + '.'); return; }
      searchPicker.load(data);
      var own = document.querySelector('input[name="w-layout"]:checked').value === 'own';
      if (own && state.searchList) { searchPicker.setListing(state.searchList, data.best ? data.best.fields : {}); return; }
      // does the newest-releases layout read the results page?
      searchPicker.setListing(feedListing(), data.best ? data.best.fields : {});
      return searchPicker.refresh().then(function(marked) {
        var items = marked && marked.success ? marked.items.length : 0;
        var titles = items ? (marked.fields.title || []).length : 0;
        if (items && titles === items) {
          setLayout('same');
          clear('search-layout');
          note('search-layout', 'ok', 'The results page looks like the feed, so the same fields read it.');
        } else {
          setLayout('own');
          searchPicker.setListing(data.listing || {}, data.best ? data.best.fields : {});
          clear('search-layout');
          note('search-layout', 'warn', data.listing
            ? 'The results are laid out differently. Quasarr suggested fields for them below; check them before testing.'
            : 'The results are laid out differently and Quasarr found no list on them. Pick a release block below.');
        }
      });
    });
  }

  // every kind is searched with its own example, as Radarr and Sonarr would
  // one search after the other: slow sites time out when asked for several at once
  function runSearches(runs, progress) {
    var current = definition();
    var results = [];
    return runs.reduce(function(chain, category, index) {
      return chain.then(function() {
        if (progress) progress(category, index, runs.length);
        return api('/api/custom-sources/preview', {definition: current, step: 'search', query: searchQueries[category.id], category: category.id})
          .then(function(data) { results.push({category: category, data: data}); });
      });
    }, Promise.resolve()).then(function() { return results; });
  }
  function searchWorked(run) { return run.data.success && run.data.quality && run.data.quality.works; }
  function mode() { return document.querySelector('input[name="w-mode"]:checked').value; }
  // one block per kind: what was searched, how it went, and the results if there are any
  function showSearch(run) {
    var data = run.data;
    var id = run.category.id;
    if (data.query) state.sentQueries[id] = data.query;
    var how = !isVideo(run.category) ? 'by name' : mode() === 'imdb' ? 'by IMDb ID' : 'by title';
    var asked = data.query || searchQueries[id];
    var box = el('div', {className: 'kind-result', id: 'kind-result-' + id}, [
      el('h5', {text: run.category.name + ': searched ' + how + ' for “' + asked + '”'})
    ]);
    $('search-results').appendChild(box);
    if (!data.success) { note(box, 'error', 'The search failed: ' + (data.error || 'no answer') + '.'); return; }
    var rows = data.table || data.rows || [];
    var skipped = Object.keys(data.skipped || {}).map(function(reason) { return data.skipped[reason] + ' ' + reason; });
    var text;
    if (!rows.length) text = 'The site found nothing for it.';
    else if (!data.parsed) text = 'The site found ' + rows.length + (rows.length === 1 ? ' entry' : ' entries') +
      ', but none is usable: ' + skipped.join(', ') + '.';
    else {
      text = data.parsed + (data.parsed === 1 ? ' release' : ' releases') + ' found' + (skipped.length ? ', skipped ' + skipped.join(', ') : '') + '.';
      if (data.quality && data.quality.same_as_feed) text += ' They are the same as the feed, so the site may ignore the search.';
      else if (!searchWorked(run)) text += ' None of them names what was searched for.';
    }
    note(box, searchWorked(run) ? 'ok' : 'warn', text);
    if (rows.length) resultsTable(box, rows.slice(0, 10), RELEASE_COLUMNS);
  }
  $('search-test').onclick = function() {
    clear('search-results');
    var settings = searchSettings();
    var runs = searchRuns();
    if (!settings) { note('search-results', 'error', 'Enter a search address in the search settings first.'); $('search-manual').open = true; return; }
    if (!runs.length) { note('search-results', 'error', 'Enter an IMDb ID such as tt0111161 or a title.'); return; }
    var done = busy($('search-test'), 'Searching…');
    var auto = state.autoRun;
    state.autoRun = false;
    state.videoFound = null;
    // an automatic setup keeps one progress line at the top, where the user is looking
    var waiting = auto && state.searchProgress ? state.searchProgress : note('search-results', 'busy', 'Searching…');
    state.searchProgress = null;
    function progress(step) {
      return function(category, index, count) {
        waiting.textContent = (auto ? 'Quasarr sets up the search on its own. Step 2 of 3: ' : '') +
          step + ' ' + category.name + ' (' + (index + 1) + ' of ' + count + ')…';
      };
    }
    runSearches(runs, progress('searching')).then(function(results) {
      var failed = results.filter(function(run) { return isVideo(run.category) && !searchWorked(run); });
      if (mode() !== 'imdb' || !failed.length) return results;
      // the site does not find IMDb IDs: titles in the site's language may work
      document.querySelector('input[name="w-mode"][value="title"]').checked = true;
      var language = $('w-language').selectedOptions[0].textContent;
      return runSearches(failed.map(function(run) { return run.category; }),
        progress('IMDb IDs found nothing, trying ' + language + ' titles for')).then(function(retried) {
        if (!retried.some(searchWorked)) {
          document.querySelector('input[name="w-mode"][value="imdb"]').checked = true;
          state.videoFound = false;
          note('search-results', 'warn', 'Neither the IMDb ID nor the ' + language + ' title found the examples for ' +
            failed.map(function(run) { return run.category.name.toLowerCase(); }).join(' and ') + '. The site may not list them: ' +
            'type a movie or show the site has into its box, press Grab IMDb ID, then test the search again.');
          return results;
        }
        note('search-results', 'warn', 'Searching by IMDb ID found nothing, so Quasarr switched to searching movies and shows by their ' +
          language + ' title. Change “Titles in” if the site lists other titles.');
        return results.map(function(run) {
          return retried.filter(function(again) { return again.category === run.category; })[0] || run;
        });
      });
    }).then(function(results) {
      done();
      results.forEach(function(run) { showSearch(run); });
      var worked = results.filter(searchWorked)[0];
      if (auto && worked) {
        waiting.textContent = 'Quasarr sets up the search on its own. Step 3 of 3: loading the results page for ' +
          worked.category.name + '…';
        // the preview shows a search the site answered, not the one used to find the search
        $('search-page').value = String(worked.category.id);
        loadResults(siteQuery(worked.category.id), true).then(function() { waiting.remove(); explain(); });
      } else {
        waiting.remove();
        if (auto) explain();
      }
      function finished() {
        if (state.discoverDone) { state.discoverDone(); state.discoverDone = null; }
        lockStep('search', false);
      }
      function explain() {
        finished();
        var read = results.map(function(run) {
          return run.category.name + ' ' + (run.data.success ? run.data.parsed + (searchWorked(run) ? '' : ' (none matching)')
            : 'failed');
        });
        note('search-notes', 'ok', 'Quasarr set up the search on its own. ' +
          (state.videoFound === false ? 'No example movie or show was found, by IMDb ID or by title. '
            : mode() === 'imdb' ? 'Movies and shows are found by IMDb ID. '
            : state.titleFromFeed ? 'The feed shows no IMDb IDs, so movies and shows are searched by title. '
            : 'Searching by IMDb ID found nothing, so movies and shows are searched by title. ') +
          'Music and books are searched by name. Results: ' + read.join(', ') + '. ' +
          'Nothing is saved yet. Check the results below, change an example if the site does not list it, then continue.');
      }
    });
  };
  $('search-next').onclick = function() {
    show('download');
    // the newest release is opened and its links tested on their own the first time
    if (!state.downloadTried && !$('w-download-selector').value.trim() && $('download-release').value) {
      state.downloadTried = true;
      state.autoDownload = true;
      lockStep('download', true);
      loadDownloadPage();
    }
  };

  // --- step 4: downloads ---------------------------------------------------------------
  var download = draft.download || {};
  var links = download.links || {};
  $('w-download-selector').value = links.selector || '';
  $('w-mirror').value = links.mirror || 'text';
  // set from the links Quasarr finds on the release page, never by hand
  function setRedirects(on) { $('w-redirects').checked = on; $('redirect-note').hidden = !on; }
  setRedirects(!!download.redirects);
  // only offered when a release page shows neither download nor crypter links
  function offerUserscript(on) {
    $('userscript-box').hidden = !on;
    $('userscript-box').open = on;
    $('w-userscript').checked = on;
  }
  offerUserscript(!!download.userscript);
  // each naming choice shows what it calls the first link of the opened release
  var MIRROR_LABELS = {};
  $('w-mirror').querySelectorAll('option').forEach(function(option) { MIRROR_LABELS[option.value] = option.textContent; });
  function nameExamples(names) {
    $('w-mirror').querySelectorAll('option').forEach(function(option) {
      var name = (names || {})[option.value];
      option.textContent = MIRROR_LABELS[option.value] + (name ? ': “' + name + '”' : '');
    });
  }
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
    if (!pages.length) note('download-notes', 'warn', 'Test the feed first; its releases are the ones to check here.');
  }
  // the release page in a preview: links Quasarr found are framed, a click picks others
  var dl = {token: null, candidates: [], ready: false, picking: false, own: null};
  var dlFrame = document.querySelector('#download-preview iframe');
  var DL_BAR = 'Preview of the release page. Blue frames are the download links.';
  function dlTell(message) { if (dl.ready) dlFrame.contentWindow.postMessage(message, '*'); }
  var dlBarTimer = null;
  function dlBar(text, refused) {
    var bar = $('download-bar');
    bar.firstChild.textContent = text;
    bar.classList.toggle('refused', !!refused);
    bar.classList.toggle('picking', dl.picking && !refused);
    clearTimeout(dlBarTimer);
    if (refused) dlBarTimer = setTimeout(function() { dlBar(dl.picking ? 'Click one of the download links. Press Esc to cancel.' : DL_BAR); }, 5000);
  }
  function dlMark() {
    var selector = $('w-download-selector').value.trim();
    if (!dl.token || !selector) { dlTell({type: 'mark', items: [], fields: {}}); return; }
    api('/api/custom-sources/highlight', {token: dl.token, item_selector: selector, fields: {}}).then(function(data) {
      dlTell({type: 'mark', items: data.success ? data.items : [], fields: {}, scroll: true});
    });
  }
  function fillDownloadChoice() {
    var select = $('download-choice');
    var current = $('w-download-selector').value.trim();
    var index = -1;
    select.textContent = '';
    dl.candidates.forEach(function(candidate, i) {
      if (candidate.spec.selector === current) index = i;
      var example = candidate.names[candidate.spec.mirror] || candidate.names.text || '';
      select.appendChild(el('option', {value: String(i), text: candidate.known + (candidate.known === 1 ? ' link' : ' links') +
        (example ? ' · first: ' + example : '')}));
    });
    if (index === -1) {
      select.appendChild(el('option', {value: 'own', text: !current ? 'Not chosen yet: click Pick'
        : 'Your pick' + (dl.own ? ' · ' + dl.own.known + (dl.own.known === 1 ? ' link' : ' links') : '')}));
    }
    select.value = index === -1 ? 'own' : String(index);
  }
  function useLinks(candidate) {
    $('w-download-selector').value = candidate.spec.selector;
    $('w-mirror').value = candidate.spec.mirror;
    nameExamples(candidate.names);
    setRedirects(!!candidate.spec.redirects);
    fillDownloadChoice();
    dlMark();
  }
  $('download-choice').onchange = function() {
    var candidate = dl.candidates[Number($('download-choice').value)];
    if (candidate) { useLinks(candidate); $('download-test').click(); }
  };
  function dlStop() {
    if (!dl.picking) return;
    dl.picking = false;
    dlTell({type: 'picking', on: false});
    $('download-pick').textContent = 'Pick';
    $('download-pick').classList.remove('picking');
    dlBar(DL_BAR);
  }
  $('download-pick').onclick = function() {
    if (dl.picking) { dlStop(); return; }
    if (!dl.token) return;
    dl.picking = true;
    dlTell({type: 'picking', on: true});
    $('download-pick').textContent = 'Cancel';
    $('download-pick').classList.add('picking');
    dlBar('Click one of the download links. Press Esc to cancel.');
  };
  document.addEventListener('keydown', function(event) { if (event.key === 'Escape') dlStop(); });
  window.addEventListener('message', function(event) {
    if (event.source !== dlFrame.contentWindow) return;
    var message = event.data || {};
    if (message.type === 'ready') { dl.ready = true; dlTell({type: 'picking', on: dl.picking}); dlMark(); }
    else if (message.type === 'cancel') dlStop();
    else if (message.type === 'refused') {
      dlBar(message.reason === 'idle' ? 'Click Pick first, then one of the download links.'
        : 'There is nothing to pick there. Click a download link.', true);
    } else if (message.type === 'pick' && dl.picking) {
      api('/api/custom-sources/pick', {token: dl.token, q: Number(message.q), kind: 'download'}).then(function(data) {
        if (!data.success) { dlBar(data.error, true); return; }
        dlStop();
        var known = dl.candidates.filter(function(c) { return c.spec.selector === data.spec.selector; })[0];
        dl.own = known ? null : data;
        offerUserscript(false);
        useLinks(known || data);
        $('download-test').click();
      });
    }
  });
  $('download-release').onchange = function() { loadDownloadPage(); };
  function loadDownloadPage() {
    clear('download-notes');
    var url = $('download-release').value;
    if (!url) return;
    var waiting = note('download-notes', 'busy', 'Opening the release page and looking for its download links…');
    api('/api/custom-sources/page', {hostname: host(), url: url, purpose: 'download', flaresolverr: $('w-flaresolverr').checked})
      .then(function(data) {
        waiting.remove();
        if (!data.success) {
          lockStep('download', false);
          note('download-notes', 'error', 'Could not open the release: ' + data.error + '.');
          return;
        }
        dl.token = data.token;
        dl.candidates = data.download || [];
        dl.ready = false;
        $('download-preview').hidden = false;
        dlFrame.srcdoc = data.preview || '<!doctype html><p>No preview</p>';
        var auto = state.autoDownload;
        state.autoDownload = false;
        if (!dl.candidates.length) {
          lockStep('download', false);
          fillDownloadChoice();
          // links that only appear in a browser need the user's own userscript
          note('download-notes', 'warn', 'Quasarr found no download or crypter links on this page. They probably only ' +
            'appear in a browser, after a CAPTCHA or a click, so this site needs a userscript: see below. You can save the ' +
            'site now, but its downloads only work once your userscript collects the links. If you see the links in the ' +
            'preview, click Pick and then one of them.');
          offerUserscript(true);
          return;
        }
        var best = dl.candidates[0];
        note('download-notes', 'ok', 'Quasarr found ' + best.known + (best.known === 1 ? ' download link' : ' download links') +
          ' on this release page and framed ' + (best.known === 1 ? 'it' : 'them') + ' in blue in the preview. ' +
          'If other links are the downloads, choose them above or click Pick and then one of them.');
        offerUserscript(false);
        var current = $('w-download-selector').value.trim();
        var known = dl.candidates.filter(function(c) { return c.spec.selector === current; })[0];
        if (!current || auto) useLinks(known || dl.candidates[0]);
        else { fillDownloadChoice(); dlMark(); }
        if (auto) { state.downloadAutoTest = true; $('download-test').click(); }
        else lockStep('download', false);
      });
  }
  $('download-test').onclick = function() {
    clear('download-results');
    var url = $('download-release').value;
    if (!url || !$('w-download-selector').value.trim()) {
      note('download-results', 'error', 'Open a release page and choose its download links first.');
      return;
    }
    var done = busy($('download-test'), 'Collecting links…');
    var auto = state.downloadAutoTest;
    state.downloadAutoTest = false;
    api('/api/custom-sources/test-download', {definition: definition(), url: url}).then(function(data) {
      done();
      if (auto) lockStep('download', false);
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
    line('Feed', current.feeds.map(function(feed) {
      var category = config.categories.filter(function(c) { return c.id === feed.category; })[0];
      return category.name + ': ' + path(feed.url);
    }).join(', ') || 'None');
    var s = current.search;
    if (!s) {
      line('Search', 'Off');
    } else {
      var language = $('w-language').selectedOptions[0].textContent;
      line('Search address', s.method.toUpperCase() + ' ' + path(s.url) + (s.body ? ' with ' + s.body : ''));
      line('Searched kinds', s.categories.map(function(id) {
        return config.categories.filter(function(c) { return c.id === id; })[0].name;
      }).join(', '));
      if (s.categories.some(function(id) { return id === 2000 || id === 5000; })) {
        line('Movies and shows', s.mode === 'imdb' ? 'by IMDb ID' : s.mode === 'title' ? 'by their ' + language + ' title' : 'not searched');
      }
      if (s.phrase) line('Music and books', 'by name');
      line('Results page', current.search_list ? 'read with its own fields' : 'read like the feed');
    }
    line('Downloads', current.download.userscript ? 'Your own userscript collects the links'
      : (current.download.links && current.download.links.selector) || 'Releases link to their containers');
    $('w-template').value = JSON.stringify(shareable(current), null, 2);
    clear('save-notes');
    if (!state.feedOk) note('save-notes', 'warn', 'The feed has not passed a test yet.');
    if (!$('w-download-selector').value.trim() && !$('w-userscript').checked) {
      note('save-notes', 'warn', 'No download links are set up. You can save the site, but its downloads will not work ' +
        'until you set the links on the Downloads step or a userscript collects them.');
    }
  }
  // the template as others import it: no key and no hostname
  function shareable(definition) {
    var host = definition.hostname;
    var copy = JSON.parse(JSON.stringify(definition));
    delete copy.key;
    delete copy.hostname;
    var text = JSON.stringify(copy);
    if (host) text = text.split(host).join('{host}');
    return JSON.parse(text);
  }
  $('template-export').onclick = function() {
    var blob = new Blob([$('w-template').value + '\n'], {type: 'application/json'});
    var link = el('a', {href: URL.createObjectURL(blob), download: ($('w-name').value.trim() || 'site').replace(/[^\w-]+/g, '_') + '.json'});
    document.body.appendChild(link);
    link.click();
    link.remove();
  };
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
