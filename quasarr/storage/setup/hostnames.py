# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import json
from urllib.parse import urlparse

import requests
from bottle import Bottle, request, response

import quasarr.providers.sessions.al
import quasarr.providers.sessions.dd
import quasarr.providers.sessions.dl
import quasarr.providers.sessions.nx
import quasarr.providers.web_server
from quasarr.constants import (
    SEARCH_CAT_BOOKS,
    SEARCH_CAT_MOVIES,
    SEARCH_CAT_MUSIC,
    SEARCH_CAT_SHOWS,
    SEARCH_CAT_SHOWS_ANIME,
    SEARCH_CAT_SHOWS_DOCUMENTARY,
    SEARCH_CATEGORY_DEFINITIONS,
)
from quasarr.providers.hostname_issues import get_all_hostname_issues
from quasarr.providers.html_images import FLAG_SVGS, LANGUAGE_FLAG_EMOJI
from quasarr.providers.html_templates import (
    render_button,
    render_fail,
    render_form,
    render_success,
)
from quasarr.providers.log import info
from quasarr.providers.shared_state import extract_valid_hostname
from quasarr.providers.utils import extract_allowed_keys, extract_kv_pairs
from quasarr.providers.web_server import Server
from quasarr.search.sources.helpers import (
    get_login_required_hostnames,
    get_radarr_required_hostnames,
    get_sonarr_required_hostnames,
    get_source_metadata,
)
from quasarr.storage.config import Config
from quasarr.storage.setup.common import (
    add_no_cache_headers,
    render_reconnect_success,
    setup_auth,
)
from quasarr.storage.setup.flaresolverr import save_flaresolverr_url
from quasarr.storage.sqlite_database import DataBase

_CATEGORY_CHIP_ORDER = (
    (SEARCH_CAT_MOVIES, "MOVIES", "Movies"),
    (SEARCH_CAT_SHOWS, "SHOWS", "TV"),
    (SEARCH_CAT_SHOWS_ANIME, "SHOWS_ANIME", "Anime"),
    (SEARCH_CAT_SHOWS_DOCUMENTARY, "SHOWS_DOCUMENTARY", "Docs"),
    (SEARCH_CAT_MUSIC, "MUSIC", "Music"),
    (SEARCH_CAT_BOOKS, "BOOKS", "Books"),
)

_LANGUAGE_LABELS = {
    "en": "English",
    "de": "German",
    "fr": "French",
}


def _capabilities_html(meta):
    """Render the per-source capability chips (categories + flags) row."""
    if not meta:
        return ""

    categories = set(meta.get("categories", []))
    chips = []

    language = meta.get("language")
    if language in LANGUAGE_FLAG_EMOJI:
        label = _LANGUAGE_LABELS[language]
        chips.append(
            f'<span class="cap-chip cap-flag" title="{label}">'
            f"{_language_flag_html(language)} {label}</span>"
        )

    if meta.get("invite_only"):
        chips.append('<span class="cap-chip cap-danger">🔒 Invite Only</span>')
    if meta.get("requires_login"):
        chips.append('<span class="cap-chip cap-warn">🔑 Login Required</span>')
    elif meta.get("requires_account"):
        chips.append('<span class="cap-chip cap-warn">👤 Account Required</span>')
    if meta.get("requires_flaresolverr"):
        chips.append('<span class="cap-chip cap-warn">🛡️ FlareSolverr Required</span>')

    for cat_id, definition_key, label in _CATEGORY_CHIP_ORDER:
        if cat_id in categories:
            emoji = SEARCH_CATEGORY_DEFINITIONS[definition_key]["emoji"]
            chips.append(
                f'<span class="cap-chip cap-cat" title="{label}">{emoji} {label}</span>'
            )

    if meta.get("requires_radarr"):
        chips.append('<span class="cap-chip">📡 Radarr Required</span>')
    if meta.get("requires_sonarr"):
        chips.append('<span class="cap-chip">📡 Sonarr Required</span>')

    if not chips:
        return ""
    return f'<div class="hostname-caps">{"".join(chips)}</div>'


def _language_flag_html(language):
    """Render the language flag emoji span (swapped to SVG on Windows via JS)."""
    if not language or language not in LANGUAGE_FLAG_EMOJI:
        return ""
    return (
        f'<span class="lang-flag" data-flag data-lang="{language}">'
        f"{LANGUAGE_FLAG_EMOJI[language]}</span>"
    )


def _escape_js_for_html_attr(s):
    """Escape a string for use inside a JS string literal within an HTML attribute."""
    if s is None:
        return ""
    return (
        str(s)
        .replace("\\", "\\\\")
        .replace("'", "\\'")
        .replace('"', "&quot;")
        .replace("\n", "\\n")
        .replace("\r", "")
    )


def hostname_form_html(shared_state, message, show_skip_management=False):
    hostname_fields = """
    <div class="hostname-entry">
        <button type="button" class="{btn_class}" onclick="showStatusDetail(\'{id}\', \'{label}\', \'{status}\', \'{error_details_for_modal}\', \'{timestamp}\', \'{operation}\', \'{url}\', \'{user}\', \'{password}\', {supports_login}, {requires_flaresolverr})" title="{status_title}">
            <span class="status-indicator" id="status-{id}" data-status="{status}">{status_emoji}</span>
            {label}
        </button>
        <input type="text" id="{id}" name="{id}" placeholder="example.com" autocorrect="off" autocomplete="off" value="{value}">
        {caps_html}
    </div>
    """

    skip_indicator = """
    <div class="skip-indicator" id="skip-indicator-{id}" style="margin-top:-0.5rem; margin-bottom:0.75rem; padding:0.5rem; background:var(--code-bg, #f8f9fa); border-radius:0.25rem; font-size:0.875rem;">
        <span style="color:#dc3545;">⚠️ Login skipped. Please click header to enable!</span>
    </div>
    """

    field_html = []
    hostnames = Config("Hostnames")
    skip_login_db = DataBase("skip_login")
    hostname_issues = get_all_hostname_issues()
    source_metadata = get_source_metadata()

    from quasarr.storage.setup.radarr import (
        is_radarr_configured,
        is_radarr_skipped,
    )
    from quasarr.storage.setup.sonarr import (
        is_sonarr_configured,
        is_sonarr_skipped,
    )

    radarr_required = set(get_radarr_required_hostnames())
    radarr_ok = is_radarr_configured(shared_state)
    radarr_skipped = is_radarr_skipped()
    sonarr_required = set(get_sonarr_required_hostnames())
    sonarr_ok = is_sonarr_configured(shared_state)
    sonarr_skipped = is_sonarr_skipped()

    for label in shared_state.values["sites"]:
        field_id = label.lower()
        current_value = hostnames.get(field_id) or ""

        is_login_skipped = (
            field_id in get_login_required_hostnames()
            and skip_login_db.retrieve(field_id)
        )
        needs_radarr = field_id in radarr_required and not radarr_ok
        needs_sonarr = field_id in sonarr_required and not sonarr_ok
        issue = hostname_issues.get(field_id)
        timestamp = ""
        operation = ""

        if not current_value:
            status = "unset"
            status_emoji = "⚫️"
            status_title = "Hostname not configured"
            error_details_for_modal = "This hostname is not configured."
        elif is_login_skipped:
            status = "skipped"
            status_emoji = "🟡"
            status_title = "Login was skipped"
            error_details_for_modal = "Login was skipped for this site."
        elif needs_radarr:
            status = "skipped" if radarr_skipped else "error"
            status_emoji = "🟡" if radarr_skipped else "🔴"
            status_title = (
                "Radarr setup was skipped"
                if radarr_skipped
                else "Radarr not configured"
            )
            error_details_for_modal = (
                "This site requires Radarr. Configure the Radarr URL and API key "
                "in the Radarr Configuration section on the home page."
            )
        elif needs_sonarr:
            status = "skipped" if sonarr_skipped else "error"
            status_emoji = "🟡" if sonarr_skipped else "🔴"
            status_title = (
                "Sonarr setup was skipped"
                if sonarr_skipped
                else "Sonarr not configured"
            )
            error_details_for_modal = (
                "This site requires Sonarr. Configure the Sonarr URL and API key "
                "in the Sonarr Configuration section on the home page."
            )
        elif issue:
            status = "error"
            status_emoji = "🔴"
            operation = issue.get("operation", "unknown")
            error_details_for_modal = issue.get("error", "Unknown error")
            timestamp = issue.get("timestamp", "")
            status_title = f"Error in {operation}"
        else:
            status = "ok"
            status_emoji = "🟢"
            status_title = "Working normally"
            error_details_for_modal = "Configured and working normally."

        user = ""
        password = ""
        supports_login = "false"
        if field_id in get_login_required_hostnames():
            supports_login = "true"
            section = "JUNKIES" if field_id in ["dj", "sj"] else field_id.upper()
            site_config = Config(section)
            user = site_config.get("user") or ""
            password = site_config.get("password") or ""

        btn_class = "btn-secondary" if status == "unset" else "btn-primary"

        meta = source_metadata.get(field_id, {})
        caps_html = _capabilities_html(meta)
        requires_flaresolverr = "true" if meta.get("requires_flaresolverr") else "false"

        field_html.append(
            hostname_fields.format(
                id=field_id,
                label=_escape_js_for_html_attr(label),
                value=current_value,
                status=status,
                status_emoji=status_emoji,
                status_title=status_title,
                caps_html=caps_html,
                requires_flaresolverr=requires_flaresolverr,
                error_details_for_modal=_escape_js_for_html_attr(
                    error_details_for_modal
                ),
                timestamp=timestamp,
                operation=_escape_js_for_html_attr(operation),
                url=_escape_js_for_html_attr(current_value),
                user=_escape_js_for_html_attr(user),
                password=_escape_js_for_html_attr(password),
                supports_login=supports_login,
                btn_class=btn_class,
            )
        )

        if show_skip_management and field_id in get_login_required_hostnames():
            if current_value and skip_login_db.retrieve(field_id):
                field_html.append(skip_indicator.format(id=field_id))

    hostname_form_content = "".join(field_html)
    button_html = render_button(
        "Save", "primary", {"type": "submit", "id": "submitBtn"}
    )
    stored_url = Config("Settings").get("hostnames_url") or ""
    skip_flaresolverr_db = DataBase("skip_flaresolverr")
    is_flaresolverr_skipped = bool(skip_flaresolverr_db.retrieve("skipped"))

    template = """
<style>
    .url-import-section {{
        border: 1px solid var(--divider-color, #dee2e6);
        border-radius: 0.5rem;
        padding: 1rem;
        margin-bottom: 1.5rem;
        background: var(--code-bg, #f8f9fa);
    }}
    .url-import-section h3 {{
        margin: 0 0 0.75rem 0;
        font-size: 1rem;
        font-weight: 600;
    }}
    .url-import-row {{
        display: flex;
        gap: 0.5rem;
        align-items: stretch;
    }}
    .url-import-row input {{
        flex: 1;
        margin-bottom: 0;
    }}
    .url-import-row button {{
        margin-top: 0;
        white-space: nowrap;
    }}
    .import-status {{
        margin-top: 0.5rem;
        font-size: 0.875rem;
    }}
    .import-status.empty {{
        display: none;
    }}
    .import-status.success {{ color: #198754; }}
    .import-status.error {{ color: #dc3545; }}
    .import-status.loading {{ color: var(--secondary, #6c757d); }}
    .status-indicator {{
        transition: transform 0.1s ease;
    }}
    .status-indicator:hover {{
        transform: scale(1.2);
    }}
    .btn-subtle {{
        background: transparent;
        color: var(--fg-color, #212529);
        border: 1px solid var(--btn-subtle-border, #ced4da);
        padding: 0.25rem 0.5rem;
        border-radius: 0.25rem;
        cursor: pointer;
        font-size: 0.875rem;
    }}
    .btn-subtle:hover {{
        background: var(--btn-subtle-bg, #e9ecef);
    }}
    .hostname-entry {{
        display: flex;
        flex-direction: column;
        gap: 0.5rem;
        align-items: stretch;
        margin-bottom: 0.75rem;
        padding: 0.65rem;
        border: 1px solid var(--divider-color, #dee2e6);
        border-radius: 0.5rem;
        background: rgba(108, 117, 125, 0.045);
    }}
    .hostname-entry button {{
        margin-top: 0;
        margin-bottom: 0;
        white-space: nowrap;
        width: auto;
        min-width: 7rem;
        align-self: center;
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 0.4rem;
    }}
    .hostname-entry input {{
        margin-bottom: 0;
    }}
    .lang-flag {{
        display: inline-flex;
        align-items: center;
        line-height: 1;
    }}
    .lang-flag-svg {{
        height: 0.95em;
        width: auto;
        border-radius: 2px;
        vertical-align: middle;
    }}
    .hostname-caps {{
        display: flex;
        flex-wrap: wrap;
        gap: 0.25rem;
        align-items: center;
        justify-content: center;
        min-width: 0;
    }}
    .cap-chip {{
        display: inline-flex;
        align-items: center;
        gap: 0.3rem;
        font-size: 0.75rem;
        padding: 0.18rem 0.5rem;
        border-radius: 0.65rem;
        background: rgba(108, 117, 125, 0.08);
        color: var(--fg-color, #212529);
        border: 1px solid rgba(108, 117, 125, 0.22);
        line-height: 1.25;
        white-space: nowrap;
    }}
    .cap-chip.cap-flag {{
        background: rgba(13, 110, 253, 0.08);
        border-color: rgba(13, 110, 253, 0.2);
    }}
    .cap-chip.cap-warn {{
        background: #fff3cd;
        border-color: #d39e00;
        color: #856404;
    }}
    .cap-chip.cap-danger {{
        background: #f8d7da;
        border-color: #f5c2c7;
        color: #842029;
    }}
    @media (max-width: 700px) {{
        .hostname-entry {{
            gap: 0.45rem;
            padding: 0.6rem;
        }}
        .hostname-entry button {{
            min-width: 6.5rem;
        }}
    }}
</style>

<div id="message" style="margin-bottom:0.5em;">{message}</div>
<div id="error-msg" style="color:red; margin-bottom:1em;"></div>

<div class="url-import-section">
    <h3>📥 Import from URL</h3>
    <div class="url-import-row">
        <input type="url" id="hostnamesUrl" placeholder="https://quasarr-hostnames.pages.dev/ini?token=123..." value="{stored_url}">
        <button type="button" class="btn-secondary" id="importBtn" onclick="importHostnames()">Import</button>
    </div>
    <div id="importStatus" class="import-status"></div>
    <p style="font-size:0.75rem; color:var(--secondary, #6c757d); margin:0.5rem 0 0 0;">
        Paste a URL containing hostname definitions (one valid Hostname per line "ab = xyz")
    </p>
</div>

<form action="/api/hostnames" method="post" onsubmit="return validateHostnames(this)">
    <input type="hidden" id="hostnamesUrlHidden" name="hostnames_url" value="{stored_url}">
    {hostname_form_content}
    {button}
</form>

<script>
  var formSubmitted = false;
  var isFlaresolverrSkipped = {is_flaresolverr_skipped};

  function validateHostnames(form) {{
    if (formSubmitted) return false;

    var errorDiv = document.getElementById('error-msg');
    errorDiv.textContent = '';

    var inputs = form.querySelectorAll('input[type="text"]:not(#hostnamesUrl)');
    for (var i = 0; i < inputs.length; i++) {{
      if (inputs[i].value.trim() !== '') {{
        formSubmitted = true;
        var btn = document.getElementById('submitBtn');
        if (btn) {{ btn.disabled = true; btn.textContent = 'Saving...'; }}
        document.getElementById('hostnamesUrlHidden').value = document.getElementById('hostnamesUrl').value.trim();
        return true;
      }}
    }}

    errorDiv.textContent = 'Please fill in at least one hostname!';
    return false;
  }}

  function importHostnames() {{
    var urlInput = document.getElementById('hostnamesUrl');
    var url = urlInput.value.trim();
    var statusDiv = document.getElementById('importStatus');
    var importBtn = document.getElementById('importBtn');

    if (!url) {{
      statusDiv.className = 'import-status error';
      statusDiv.textContent = 'Please enter a URL';
      return;
    }}

    statusDiv.className = 'import-status loading';
    statusDiv.textContent = 'Importing...';
    importBtn.disabled = true;
    importBtn.textContent = 'Importing...';

    quasarrApiFetch('/api/hostnames/import-url', {{
      method: 'POST',
      headers: {{ 'Content-Type': 'application/json' }},
      body: JSON.stringify({{ url: url }})
    }})
    .then(response => response.json())
    .then(data => {{
      importBtn.disabled = false;
      importBtn.textContent = 'Import';

      if (data.success) {{
        var count = 0;
        for (var key in data.hostnames) {{
          var input = document.getElementById(key);
          if (input) {{
            input.value = data.hostnames[key];
            count++;
          }}
        }}
        statusDiv.className = 'import-status success';
        var msg = 'Imported ' + count + ' hostname(s)';
        if (data.errors && Object.keys(data.errors).length > 0) {{
          msg += ' (' + Object.keys(data.errors).length + ' invalid)';
        }}
        statusDiv.textContent = msg + '. Review and click Save.';
      }} else {{
        statusDiv.className = 'import-status error';
        statusDiv.textContent = data.error || 'Import failed';
      }}
    }})
    .catch(error => {{
      importBtn.disabled = false;
      importBtn.textContent = 'Import';
      statusDiv.className = 'import-status error';
      statusDiv.textContent = 'Network error: ' + error.message;
    }});
  }}

  function confirmRestart() {{
    showModal('Restart Quasarr?', 'Are you sure you want to restart Quasarr now? Any unsaved changes will be lost.',
        `<button class="btn-secondary" onclick="closeModal()">Cancel</button>
         <button class="btn-primary" onclick="performRestart()">Restart</button>`
    );
  }}

  function performRestart() {{
    closeModal();
    quasarrApiFetch('/api/restart', {{ method: 'POST' }})
    .then(response => response.json())
    .then(data => {{
      if (data.success) {{
        showRestartOverlay();
      }}
    }})
    .catch(function() {{
      showRestartOverlay();
    }});
  }}

  function showRestartOverlay() {{
    document.body.innerHTML = `
      <div style="text-align:center; padding:2rem; font-family:system-ui,-apple-system,sans-serif;">
        <h2>Restarting Quasarr...</h2>
        <p id="restartStatus">Waiting <span id="countdown">10</span> seconds...</p>
        <div id="spinner" style="display:none; margin-top:1rem;">
          <div style="display:inline-block; width:24px; height:24px; border:3px solid #ccc; border-top-color:#333; border-radius:50%; animation:spin 1s linear infinite;"></div>
          <style>@keyframes spin {{ to {{ transform: rotate(360deg); }} }}</style>
        </div>
      </div>
    `;
    startCountdown(10);
  }}

  function startCountdown(seconds) {{
    var countdownEl = document.getElementById('countdown');
    var statusEl = document.getElementById('restartStatus');
    var spinnerEl = document.getElementById('spinner');

    var remaining = seconds;
    var interval = setInterval(function() {{
      remaining--;
      if (countdownEl) countdownEl.textContent = remaining;

      if (remaining <= 0) {{
        clearInterval(interval);
        statusEl.textContent = 'Reconnecting...';
        spinnerEl.style.display = 'block';
        tryReconnect();
      }}
    }}, 1000);
  }}

  function tryReconnect() {{
    var statusEl = document.getElementById('restartStatus');
    var attempts = 0;

    function attempt() {{
      attempts++;
      fetch('/', {{ method: 'HEAD', cache: 'no-store' }})
      .then(response => {{
        if (response.ok) {{
          statusEl.textContent = 'Connected! Reloading...';
          setTimeout(function() {{ window.location.href = '/'; }}, 500);
        }} else {{
          scheduleRetry();
        }}
      }})
      .catch(function() {{
        scheduleRetry();
      }});
    }}

    function scheduleRetry() {{
      statusEl.textContent = 'Reconnecting... (attempt ' + attempts + ')';
      setTimeout(attempt, 1000);
    }}

    attempt();
  }}
</script>
<script>
    function showStatusDetail(id, label, status, error_details, timestamp, operation, url, user, password, supports_login, requires_flaresolverr) {{
        var statusTextMap = {{
            ok: 'Operational',
            error: 'Error',
            unset: 'Not configured',
            skipped: 'Login skipped',
            info: 'Information'
        }};

        var emojiMap = {{
            ok: '🟢',
            error: '🔴',
            unset: '⚫️',
            skipped: '🟡',
            info: 'ℹ️'
        }};

        var content_html = '';
        if (status === 'error') {{
            content_html += '<p>' + (error_details || 'No details available.') + '</p>';
        }} else {{
            content_html += '<p>' + (error_details || 'No additional details available.') + '</p>';
        }}

        var timestamp_html = '';
        if (timestamp) {{
            var d = new Date(timestamp);
            var day = ("0" + d.getDate()).slice(-2);
            var month = ("0" + (d.getMonth() + 1)).slice(-2);
            var year = d.getFullYear();
            var hours = ("0" + d.getHours()).slice(-2);
            var minutes = ("0" + d.getMinutes()).slice(-2);
            var seconds = ("0" + d.getSeconds()).slice(-2);
            var formattedTimestamp = day + "." + month + "." + year + " " + hours + ":" + minutes + ":" + seconds;

            if (operation) {{
                timestamp_html = '<p><small>Occurred in ' + operation + ' at ' + formattedTimestamp + '</small></p>';
            }} else {{
                timestamp_html = '<p><small>Occurred at: ' + formattedTimestamp + '</small></p>';
            }}
        }}

        var credentials_html = '';
        if (url && supports_login) {{
             var flaresolverrWarning = '';
             if (requires_flaresolverr && isFlaresolverrSkipped) {{
                flaresolverrWarning = `
                    <div style="margin-bottom: 1rem; padding: 0.75rem; background: #fff3cd; border: 1px solid #ffeeba; border-radius: 0.25rem; color: #856404; font-size: 0.875rem;">
                        <strong>⚠️ flaresolverr-next Required</strong><br>
                        This site requires flaresolverr-next, but it was skipped. You must configure it first.
                        <div style="margin-top: 0.5rem;">
                            <button class="btn-secondary" style="font-size: 0.75rem; padding: 0.25rem 0.5rem;" onclick="window.location.href='/flaresolverr'">Configure flaresolverr-next</button>
                        </div>
                    </div>
                `;
             }}

             credentials_html = `
                <div style="margin-top: 1rem; border-top: 1px solid var(--divider-color, #dee2e6); padding-top: 1rem;">
                    <h4 style="margin-top:0; font-size:1rem;">Credentials</h4>
                    ${{flaresolverrWarning}}
                    <div style="margin-bottom: 0.5rem;">
                        <label style="display:block; font-size: 0.875rem;">Login</label>
                        <input type="text" id="cred-user-${{id}}" value="${{user}}" style="width: 100%; padding: 0.375rem 0.75rem; border: 1px solid #ced4da; border-radius: 0.25rem;">
                    </div>
                    <div style="margin-bottom: 0.5rem;">
                        <label style="display:block; font-size: 0.875rem;">Password</label>
                        <input type="password" id="cred-pass-${{id}}" value="${{password}}" style="width: 100%; padding: 0.375rem 0.75rem; border: 1px solid #ced4da; border-radius: 0.25rem;">
                    </div>
                    <div id="cred-status-${{id}}" style="margin-bottom: 0.5rem; font-size: 0.875rem; min-height: 1.25em;"></div>
                    <button class="btn-primary" onclick="saveAndCheckCredentials('${{id}}')">Check & Save Session</button>
                    <div style="margin-top: 1rem; border-bottom: 1px solid var(--divider-color, #dee2e6);"></div>
                </div>
            `;
        }}

        var content = content_html + timestamp_html + credentials_html;
        var title = '<span>' + (emojiMap[status] || 'ℹ️') + '</span> ' + label + ' - ' + (statusTextMap[status] || status);

        var buttons = '';
        if (url) {{
            var href = url;
            if (!href.startsWith('http://') && !href.startsWith('https://')) {{
                href = 'https://' + href;
            }}
            buttons = `
                <button class="btn-primary" style="margin-right: auto;" onclick="window.open('${{href}}', '_blank')">Open ${{id.toUpperCase()}}</button>
                <button class="btn-secondary" onclick="closeModal()">Close</button>
            `;
        }} else {{
            buttons = '<button class="btn-secondary" onclick="closeModal()">Close</button>';
        }}

        showModal(title, content, buttons);
    }}

    function saveAndCheckCredentials(id) {{
        var user = document.getElementById('cred-user-' + id).value;
        var pass = document.getElementById('cred-pass-' + id).value;
        var statusDiv = document.getElementById('cred-status-' + id);

        statusDiv.innerHTML = 'Checking...';
        statusDiv.style.color = 'var(--secondary, #6c757d)';

        quasarrApiFetch('/api/hostnames/check-credentials/' + id, {{
            method: 'POST',
            headers: {{ 'Content-Type': 'application/json' }},
            body: JSON.stringify({{ user: user, password: pass }})
        }})
        .then(response => response.json())
        .then(data => {{
            if (data.success) {{
                statusDiv.innerHTML = '✅ ' + data.message;
                statusDiv.style.color = '#198754';
                var indicator = document.getElementById('status-' + id);
                if (indicator) {{
                    indicator.textContent = '🟢';
                    indicator.setAttribute('data-status', 'ok');
                }}
                var skipIndicator = document.getElementById('skip-indicator-' + id);
                if (skipIndicator) {{
                    skipIndicator.remove();
                }}
            }} else {{
                statusDiv.innerHTML = '❌ ' + data.message;
                statusDiv.style.color = '#dc3545';
            }}
        }})
        .catch(error => {{
            statusDiv.innerHTML = '❌ Error: ' + error.message;
            statusDiv.style.color = '#dc3545';
        }});
    }}
</script>
<script>
    // Windows lacks regional-indicator flag glyphs, so swap the language emoji
    // for the matching inline SVG (same approach as the hostnames web tool).
    (function() {{
        if (!/Windows/.test(navigator.userAgent)) return;
        var FLAG_SVG = {flag_svg_json};
        document.querySelectorAll('[data-flag][data-lang]').forEach(function(el) {{
            var svg = FLAG_SVG[el.getAttribute('data-lang')];
            if (svg) {{ el.innerHTML = svg; }}
        }});
    }})();
</script>
"""
    return template.format(
        message=message,
        hostname_form_content=hostname_form_content,
        button=button_html,
        stored_url=stored_url,
        flag_svg_json=json.dumps(FLAG_SVGS),
        is_flaresolverr_skipped="true" if is_flaresolverr_skipped else "false",
    )


def save_hostnames(shared_state, timeout=5, first_run=True):
    del timeout, first_run

    hostnames = Config("Hostnames")
    valid_domains = {}
    errors = {}

    for site_key in shared_state.values["sites"]:
        shorthand = site_key.lower()
        raw_value = request.forms.get(shorthand)
        if raw_value is None or raw_value.strip() == "":
            continue

        result = extract_valid_hostname(raw_value, shorthand)
        domain = result.get("domain")
        message = result.get("message", "Error checking the hostname you provided!")
        if domain:
            valid_domains[site_key] = domain
        else:
            errors[site_key] = message

    valid_domains = {k: d for k, d in valid_domains.items() if d}
    if not valid_domains:
        fail_msg = next(iter(errors.values()), "No valid hostname provided!")
        return render_fail(fail_msg)

    for site_key in shared_state.values["sites"]:
        shorthand = site_key.lower()
        raw_value = request.forms.get(shorthand)
        if site_key in valid_domains:
            new_val = valid_domains[site_key]
            old_val = hostnames.get(shorthand) or ""
            if old_val != new_val:
                hostnames.save(shorthand, new_val)
        elif raw_value is None:
            continue
        elif raw_value.strip() == "":
            old_val = hostnames.get(shorthand) or ""
            if old_val != "":
                hostnames.save(shorthand, "")

    hostnames_url = request.forms.get("hostnames_url", "").strip()
    Config("Settings").save("hostnames_url", hostnames_url)

    quasarr.providers.web_server.temp_server_success = True

    success_msg = "At least one valid hostname set!"
    if errors:
        optional_text = (
            "<br>".join(f"{site}: {msg}" for site, msg in errors.items()) + "<br>"
        )
    else:
        optional_text = "All provided hostnames are valid.<br>"

    full_message = f"{success_msg}<br><small>{optional_text}</small>"
    return render_reconnect_success(full_message)


def check_credentials(shared_state, shorthand):
    response.content_type = "application/json"
    try:
        data = request.json
        user = data.get("user")
        password = data.get("password")

        sh_lower = shorthand.lower()
        section = "JUNKIES" if sh_lower in ["dj", "sj"] else shorthand.upper()
        config = Config(section)
        old_user = config.get("user")
        old_password = config.get("password")

        config.save("user", user)
        config.save("password", password)

        success = False
        if sh_lower == "al":
            if quasarr.providers.sessions.al.create_and_persist_session(shared_state):
                success = True
                message = "Session valid!"
            else:
                message = "Session check failed (check logs)"
        elif sh_lower == "dd":
            if quasarr.providers.sessions.dd.create_and_persist_session(shared_state):
                success = True
                message = "Session valid!"
            else:
                message = "Session check failed (check logs)"
        elif sh_lower == "dl":
            if quasarr.providers.sessions.dl.create_and_persist_session(shared_state):
                success = True
                message = "Session valid!"
            else:
                message = "Session check failed (check logs)"
        elif sh_lower == "nx":
            if quasarr.providers.sessions.nx.create_and_persist_session(shared_state):
                success = True
                message = "Session valid!"
            else:
                message = "Session check failed (check logs)"
        elif sh_lower in ["dj", "sj"]:
            success = True
            message = "Credentials saved"
        else:
            success = True
            message = "Credentials saved"

        if success:
            DataBase("skip_login").delete(sh_lower)
            if sh_lower == "dj":
                DataBase("skip_login").delete("sj")
            elif sh_lower == "sj":
                DataBase("skip_login").delete("dj")
        else:
            config.save("user", old_user)
            config.save("password", old_password)

        return {"success": success, "message": message}

    except Exception as e:
        return {"success": False, "message": str(e)}


def import_hostnames_from_url():
    """Fetch URL and parse hostnames, return JSON for JS to populate fields."""
    response.content_type = "application/json"
    try:
        data = request.json
        url = data.get("url", "").strip()

        if not url:
            return {"success": False, "error": "No URL provided"}

        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            return {"success": False, "error": "Invalid URL format"}

        try:
            resp = requests.get(url, timeout=15)
            resp.raise_for_status()
            content = resp.text
        except requests.RequestException as e:
            info(f"Failed to fetch hostnames URL: {e}")
            return {
                "success": False,
                "error": "Failed to fetch URL. Check the console log for details.",
            }

        allowed_keys = extract_allowed_keys(Config._DEFAULT_CONFIG, "Hostnames")
        results = extract_kv_pairs(content, allowed_keys)

        if not results:
            return {
                "success": False,
                "error": "No hostnames found in the provided URL",
            }

        valid_hostnames = {}
        invalid_hostnames = {}
        for shorthand, hostname in results.items():
            domain_check = extract_valid_hostname(hostname, shorthand)
            domain = domain_check.get("domain")
            if domain:
                valid_hostnames[shorthand] = domain
            else:
                invalid_hostnames[shorthand] = domain_check.get("message", "Invalid")

        if not valid_hostnames:
            return {
                "success": False,
                "error": "No valid hostnames found in the provided URL",
            }

        return {
            "success": True,
            "hostnames": valid_hostnames,
            "errors": invalid_hostnames,
        }

    except Exception as e:
        return {"success": False, "error": f"Error: {str(e)}"}


def get_skip_login():
    """Return list of hostnames with skipped login."""
    response.content_type = "application/json"
    skip_db = DataBase("skip_login")
    skipped = []
    for site in get_login_required_hostnames():
        if skip_db.retrieve(site):
            skipped.append(site)
    return {"skipped": skipped}


def clear_skip_login(shorthand):
    """Clear skip login preference for a hostname."""
    response.content_type = "application/json"
    shorthand = shorthand.lower()
    if shorthand not in get_login_required_hostnames():
        return {"success": False, "error": f"Invalid shorthand: {shorthand}"}

    DataBase("skip_login").delete(shorthand)
    info(f'Skip login preference cleared for "{shorthand.upper()}"')
    return {"success": True}


def hostnames_config(shared_state):
    app = Bottle()
    add_no_cache_headers(app)
    setup_auth(app)

    @app.get("/")
    def hostname_form():
        message = """<p>
          If you're having trouble setting this up, take a closer look at 
          <a href="https://github.com/rix1337/Quasarr?tab=readme-ov-file#quasarr" target="_blank" rel="noopener noreferrer">
            the instructions.
          </a>
        </p>"""
        return render_form(
            "Set at least one valid hostname", hostname_form_html(shared_state, message)
        )

    @app.post("/api/hostnames")
    def set_hostnames():
        return save_hostnames(shared_state)

    @app.post("/api/hostnames/import-url")
    def import_hostnames_route():
        return import_hostnames_from_url()

    @app.get("/api/skip-login")
    def get_skip_login_route():
        return get_skip_login()

    @app.delete("/api/skip-login/<shorthand>")
    def clear_skip_login_route(shorthand):
        return clear_skip_login(shorthand)

    @app.post("/api/hostnames/check-credentials/<shorthand>")
    def check_credentials_route(shorthand):
        return check_credentials(shared_state, shorthand)

    info(
        f'Hostnames not set. Starting web server for config at: "{shared_state.values["external_address"]}".'
    )
    info("Please set at least one valid hostname there!")
    quasarr.providers.web_server.temp_server_success = False
    return Server(
        app, listen="0.0.0.0", port=shared_state.values["port"]
    ).serve_temporarily()


def hostname_credentials_config(shared_state, shorthand, domain):
    app = Bottle()
    add_no_cache_headers(app)
    setup_auth(app)

    shorthand = shorthand.upper()

    @app.post("/api/flaresolverr_inline")
    def set_flaresolverr_inline():
        return save_flaresolverr_url(shared_state, is_setup=False)

    @app.get("/")
    def credentials_form():
        flaresolverr_url = Config("FlareSolverr").get("url")
        source_meta = get_source_metadata().get(shorthand.lower(), {})
        is_missing_flaresolverr = (
            source_meta.get("requires_flaresolverr") and not flaresolverr_url
        )

        flaresolverr_section = ""
        if is_missing_flaresolverr:
            flaresolverr_section = """
             <div style="margin-bottom: 1.5rem; padding: 1rem; background: #fff3cd; border: 1px solid #ffeeba; border-radius: 0.5rem;">
                <h4 style="margin-top:0; font-size:1rem; color:#856404;">⚠️ flaresolverr-next Required</h4>
                <p style="font-size:0.875rem; margin-bottom:0.5rem; color:#856404;">
                    This site requires flaresolverr-next. Please configure it below before checking credentials.
                </p>
                <form action="/api/flaresolverr_inline" method="post" onsubmit="return handleFlareSolverrSubmit(this)">
                    <div style="display:flex; gap:0.5rem;">
                        <input type="text" name="url" placeholder="http://192.168.0.1:8191/v1" style="flex:1; margin-bottom:0;">
                        <button type="submit" class="btn-secondary" id="fsSubmitBtn" style="margin-top:0;">Save URL</button>
                    </div>
                </form>
             </div>
             <script>
             function handleFlareSolverrSubmit(form) {{
                 var btn = document.getElementById('fsSubmitBtn');
                 if (btn) {{ btn.disabled = true; btn.textContent = 'Saving...'; }}
                 return true;
             }}
             </script>
             """

        disabled_attr = "disabled" if is_missing_flaresolverr else ""

        credentials_inputs = f"""
        <span>If required register account at: <a href="https://{domain}">{domain}</a>!</span><br><br>
        <label for="user">Login</label>
        <input type="text" id="user" name="user" placeholder="User" autocorrect="off" {disabled_attr}><br>

        <label for="password">Password</label>
        <input type="password" id="password" name="password" placeholder="Password" {disabled_attr}><br>
        """

        form_html = f"""
        <style>
            .button-row {{
                display: flex;
                gap: 0.75rem;
                justify-content: center;
                flex-wrap: wrap;
                margin-top: 1rem;
            }}
            .btn-warning {{
                background-color: #ffc107;
                color: #212529;
                border: 1.5px solid #d39e00;
                padding: 0.5rem 1rem;
                font-size: 1rem;
                border-radius: 0.5rem;
                font-weight: 500;
                cursor: pointer;
            }}
            .btn-warning:hover {{
                background-color: #e0a800;
                border-color: #c69500;
            }}
        </style>
        {flaresolverr_section}
        <form id="credentialsForm" action="/api/credentials/{shorthand}" method="post" onsubmit="return handleSubmit(this)">
            {credentials_inputs}
            <div class="button-row">
                {render_button("Save", "primary", {"type": "submit", "id": "submitBtn"})}
                <button type="button" class="btn-warning" id="skipBtn" onclick="skipLogin()">Skip for now</button>
            </div>
        </form>
        <p style="font-size:0.875rem; color:var(--secondary, #6c757d); margin-top:1rem;">
            Skipping will allow Quasarr to start, but this site won't work until credentials are provided.
        </p>
        <script>
        var formSubmitted = false;
        var isMissingFlaresolverr = {"true" if is_missing_flaresolverr else "false"};

        function handleSubmit(form) {{
            if (isMissingFlaresolverr) {{
                showModal('flaresolverr-next Required', 'You must configure flaresolverr-next below or skip login for this site.');
                return false;
            }}

            if (formSubmitted) return false;
            formSubmitted = true;
            var btn = document.getElementById('submitBtn');
            if (btn) {{ btn.disabled = true; btn.textContent = 'Saving...'; }}
            document.getElementById('skipBtn').disabled = true;
            return true;
        }}
        function skipLogin() {{
            if (formSubmitted) return;
            formSubmitted = true;
            var skipBtn = document.getElementById('skipBtn');
            var submitBtn = document.getElementById('submitBtn');
            if (skipBtn) {{ skipBtn.disabled = true; skipBtn.textContent = 'Skipping...'; }}
            if (submitBtn) {{ submitBtn.disabled = true; }}

            quasarrApiFetch('/api/credentials/{shorthand}/skip', {{ method: 'POST' }})
            .then(response => {{
                if (response.ok) {{
                    window.location.href = '/skip-success';
                }} else {{
                    showModal('Error', 'Failed to skip login');
                    formSubmitted = false;
                    if (skipBtn) {{ skipBtn.disabled = false; skipBtn.textContent = 'Skip for now'; }}
                    if (submitBtn) {{ submitBtn.disabled = false; }}
                }}
            }})
            .catch(error => {{
                showModal('Error', 'Error: ' + error.message);
                formSubmitted = false;
                if (skipBtn) {{ skipBtn.disabled = false; skipBtn.textContent = 'Skip for now'; }}
                if (submitBtn) {{ submitBtn.disabled = false; }}
            }});
        }}
        </script>
        """

        return render_form(f"Set User and Password for {shorthand}", form_html)

    @app.get("/skip-success")
    def skip_success():
        return render_reconnect_success(
            f"{shorthand} login skipped. You can configure credentials later in the web UI."
        )

    @app.post("/api/credentials/<sh>/skip")
    def skip_credentials(sh):
        sh_lower = sh.lower()
        DataBase("skip_login").update_store(sh_lower, "true")
        if sh_lower == "dj":
            DataBase("skip_login").update_store("sj", "true")
        elif sh_lower == "sj":
            DataBase("skip_login").update_store("dj", "true")
        info(f'Login for "{sh}" skipped by user choice')
        quasarr.providers.web_server.temp_server_success = True
        return {"success": True}

    @app.post("/api/credentials/<sh>")
    def set_credentials(sh):
        if quasarr.providers.web_server.temp_server_success:
            return render_success(f"{sh} credentials already being processed", 5)

        user = request.forms.get("user")
        password = request.forms.get("password")
        sh_lower = sh.lower()
        section = "JUNKIES" if sh_lower in ["dj", "sj"] else sh.upper()
        config = Config(section)

        error_message = "User and Password wrong or empty!"
        if user and password:
            config.save("user", user)
            config.save("password", password)

            DataBase("skip_login").delete(sh_lower)
            if sh_lower == "dj":
                DataBase("skip_login").delete("sj")
            elif sh_lower == "sj":
                DataBase("skip_login").delete("dj")

            if sh_lower == "al":
                error_message = (
                    "User and Password wrong or empty.<br><br>"
                    "Or if you skipped Flaresolverr setup earlier, "
                    "you must chose to skip login for this site, "
                    "set up flaresolverr-next in the UI and then restart Quasarr!"
                )
                if quasarr.providers.sessions.al.create_and_persist_session(
                    shared_state
                ):
                    quasarr.providers.web_server.temp_server_success = True
                    return render_reconnect_success(
                        f"{sh} credentials set successfully"
                    )
            elif sh_lower == "dd":
                if quasarr.providers.sessions.dd.create_and_persist_session(
                    shared_state
                ):
                    quasarr.providers.web_server.temp_server_success = True
                    return render_reconnect_success(
                        f"{sh} credentials set successfully"
                    )
            elif sh_lower == "dl":
                if quasarr.providers.sessions.dl.create_and_persist_session(
                    shared_state
                ):
                    quasarr.providers.web_server.temp_server_success = True
                    return render_reconnect_success(
                        f"{sh} credentials set successfully"
                    )
            elif sh_lower == "nx":
                if quasarr.providers.sessions.nx.create_and_persist_session(
                    shared_state
                ):
                    quasarr.providers.web_server.temp_server_success = True
                    return render_reconnect_success(
                        f"{sh} credentials set successfully"
                    )
            elif sh_lower in ["dj", "sj"]:
                quasarr.providers.web_server.temp_server_success = True
                return render_reconnect_success(f"{sh} credentials set successfully")
            else:
                quasarr.providers.web_server.temp_server_success = False
                return render_fail(f"Unknown site shorthand! ({sh})")

        config.save("user", "")
        config.save("password", "")
        return render_fail(error_message)

    info(
        f'"{shorthand.lower()}" credentials required to access download links. '
        f'Starting web server for config at: "{shared_state.values["external_address"]}".'
    )
    info(f"If needed register here: 'https://{domain}'")
    info("Please set your credentials now, or skip to allow Quasarr to launch!")
    quasarr.providers.web_server.temp_server_success = False
    return Server(
        app, listen="0.0.0.0", port=shared_state.values["port"]
    ).serve_temporarily()
