# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import json

from bottle import Bottle

import quasarr.providers.html_images as images
from quasarr.api.arr import setup_arr_routes
from quasarr.api.captcha import setup_captcha_routes
from quasarr.api.config import setup_config
from quasarr.api.jdownloader import get_jdownloader_status
from quasarr.api.packages import setup_packages_routes
from quasarr.api.sponsors_helper import setup_sponsors_helper_routes
from quasarr.api.statistics import setup_statistics
from quasarr.constants import (
    NOTIFICATION_PROVIDERS,
    TIMEOUT_SLOW_MODE_DEFINITIONS,
    TIMEOUT_SLOW_MODE_MULTIPLIER,
)
from quasarr.providers import shared_state
from quasarr.providers.auth import (
    add_auth_hook,
    add_auth_routes,
    audit_route_auth_modes,
    show_logout_link,
)
from quasarr.providers.hostname_issues import get_all_hostname_issues
from quasarr.providers.html_templates import (
    render_button,
    render_centered_html,
    render_success,
)
from quasarr.providers.notifications.helpers.notification_types import (
    get_notification_type_label,
    get_user_configurable_notification_types,
)
from quasarr.providers.web_server import Server
from quasarr.search.sources.helpers import (
    get_login_required_hostnames,
    get_radarr_required_hostnames,
    get_sonarr_required_hostnames,
)
from quasarr.storage.config import Config
from quasarr.storage.setup.arr import missing_arr_client_requirement
from quasarr.storage.setup.radarr import is_radarr_configured
from quasarr.storage.setup.sonarr import is_sonarr_configured
from quasarr.storage.sqlite_database import DataBase


def get_api(shared_state_dict, shared_state_lock):
    shared_state.set_state(shared_state_dict, shared_state_lock)

    app = Bottle()

    # Install auth policy before the route modules are registered.
    add_auth_routes(app)
    add_auth_hook(app, whitelist=[".user.js"])

    setup_arr_routes(app)
    setup_captcha_routes(app)
    setup_config(app, shared_state)
    setup_statistics(app, shared_state)
    setup_sponsors_helper_routes(app)
    setup_packages_routes(app)
    audit_route_auth_modes(
        app,
        api_key_prefixes=("/api", "/download/", "/sponsors_helper/api/"),
        public_whitelist=(".user.js",),
    )

    @app.get("/")
    def index():
        protected = shared_state.get_db("protected").retrieve_all_titles()
        api_key = Config("API").get("key")

        # Get JDownloader status and modal script
        jd_status = get_jdownloader_status(shared_state)

        # Get JDownloader config for the inline form
        jd_config = Config("JDownloader")
        jd_user = jd_config.get("user") or ""
        jd_pass = jd_config.get("password") or ""
        jd_device = jd_config.get("device") or ""

        # Calculate hostname status
        hostnames_config = Config("Hostnames")
        skip_login_db = DataBase("skip_login")
        hostname_issues = get_all_hostname_issues()

        working_count = 0
        total_count = 0

        radarr_required = set(get_radarr_required_hostnames())
        radarr_ok = is_radarr_configured(shared_state)
        sonarr_required = set(get_sonarr_required_hostnames())
        sonarr_ok = is_sonarr_configured(shared_state)

        for site_key in shared_state.values["sites"]:
            shorthand = site_key.lower()
            current_value = hostnames_config.get(shorthand)

            # Skip unset hostnames and skipped logins
            if not current_value:
                continue
            if shorthand in get_login_required_hostnames():
                skip_val = skip_login_db.retrieve(shorthand)
                if skip_val and str(skip_val).lower() == "true":
                    continue
            # This hostname counts toward total
            total_count += 1

            # Check if it's working (no issues and dependencies met)
            if shorthand in hostname_issues:
                continue
            if missing_arr_client_requirement(
                shorthand, radarr_required, sonarr_required, radarr_ok, sonarr_ok
            ):
                continue
            working_count += 1

        # Determine status
        if total_count == 0:
            hostname_status_class = "error"
            hostname_status_emoji = "⚫️"
            hostname_status_text = "No hostnames configured"
        elif working_count == 0:
            hostname_status_class = "error"
            hostname_status_emoji = "🔴"
            hostname_status_text = f"0/{total_count} hostnames operational"
        elif working_count < total_count:
            hostname_status_class = "warning"
            hostname_status_emoji = "🟡"
            hostname_status_text = (
                f"{working_count}/{total_count} hostnames operational"
            )
        else:
            hostname_status_class = "success"
            hostname_status_emoji = "🟢"
            hostname_status_text = (
                f"{working_count}/{total_count} hostnames operational"
            )

        # CAPTCHA banner
        captcha_hint = ""
        if protected:
            plural = "s" if len(protected) > 1 else ""
            captcha_hint = f"""
            <div class="alert alert-warning">
                <span class="alert-icon">🔒</span>
                <div class="alert-content">
                    <strong>{len(protected)} link{plural} waiting for CAPTCHA</strong>
                    {"" if shared_state.values.get("helper_active") else '<br><a href="https://github.com/rix1337/Quasarr?tab=readme-ov-file#sponsorshelper" target="_blank">Sponsors get automated CAPTCHA solutions!</a>'}
                </div>
                <div class="alert-action">
                    {render_button(f"Solve CAPTCHA{plural}", "primary", {"onclick": "location.href='/captcha'"})}
                </div>
            </div>
            """

        # Status bars
        status_bars = f"""
            <div class="status-bar">
                <span class="status-pill {jd_status["status_class"]}" 
                      title="JDownloader Status">
                    {jd_status["status_text"]}
                </span>
                <span class="status-pill {hostname_status_class}"
                      title="Hostnames Status">
                    {hostname_status_emoji} {hostname_status_text}
                </span>
            </div>
        """

        # FlareSolverr status
        skip_flaresolverr_db = DataBase("skip_flaresolverr")
        is_flaresolverr_skipped = skip_flaresolverr_db.retrieve("skipped")
        flaresolverr_url = Config("FlareSolverr").get("url") or ""

        # Radarr settings
        radarr_config = Config("Radarr")
        radarr_url = radarr_config.get("url") or ""
        radarr_api_key = radarr_config.get("api_key") or ""

        # Sonarr settings
        sonarr_config = Config("Sonarr")
        sonarr_url = sonarr_config.get("url") or ""
        sonarr_api_key = sonarr_config.get("api_key") or ""

        flaresolverr_warning = ""
        if is_flaresolverr_skipped:
            flaresolverr_warning = """
            <div class="alert alert-warning" style="margin-bottom: 15px; padding: 10px;">
                <span style="font-size: 0.9em;">⚠️ flaresolverr-next setup was skipped. Some sites may not work.</span>
            </div>
            """

        notification_cases = [
            (
                notification_type.value,
                get_notification_type_label(notification_type),
            )
            for notification_type in get_user_configurable_notification_types()
        ]

        notification_settings = shared_state.values.get("notification_settings", {})
        notification_toggles = notification_settings.get("toggles")
        if not isinstance(notification_toggles, dict):
            notification_toggles = {provider: {} for provider in NOTIFICATION_PROVIDERS}
        notification_silent = notification_settings.get("silent")
        if not isinstance(notification_silent, dict):
            notification_silent = {provider: {} for provider in NOTIFICATION_PROVIDERS}

        discord_webhook = notification_settings.get("discord_webhook") or ""
        telegram_bot_token = notification_settings.get("telegram_bot_token") or ""
        telegram_chat_id = notification_settings.get("telegram_chat_id") or ""
        pushover_api_token = notification_settings.get("pushover_api_token") or ""
        pushover_user_key = notification_settings.get("pushover_user_key") or ""

        notification_cases_json = json.dumps(
            [case_key for case_key, _ in notification_cases]
        )
        timeout_slow_mode_keys_json = json.dumps(
            list(TIMEOUT_SLOW_MODE_DEFINITIONS.keys())
        )
        timeout_slow_mode_definitions_json = json.dumps(
            {
                timeout_key: {
                    "base_seconds": int(timeout_data["base_seconds"]),
                    "slow_seconds": int(
                        timeout_data["base_seconds"] * TIMEOUT_SLOW_MODE_MULTIPLIER
                    ),
                }
                for timeout_key, timeout_data in TIMEOUT_SLOW_MODE_DEFINITIONS.items()
            }
        )
        timeout_slow_mode_settings = shared_state.values.get("timeout_slow_mode", {})
        if not isinstance(timeout_slow_mode_settings, dict):
            timeout_slow_mode_settings = {}

        filecrypt_checked = (
            "checked" if shared_state.values.get("filecrypt_enabled", True) else ""
        )

        def render_switch(input_id, checked):
            return (
                '<label class="switch">'
                f'<input type="checkbox" id="{input_id}" {checked}>'
                '<span class="switch-slider" aria-hidden="true"></span>'
                "</label>"
            )

        def render_notification_toggle_rows(provider):
            provider_toggles = notification_toggles.get(provider, {})
            provider_silent = notification_silent.get(provider, {})
            cells = [
                '<div class="notification-toggle-header">Notification</div>',
                '<div class="notification-toggle-header toggle-cell">Enabled</div>',
                '<div class="notification-toggle-header toggle-cell">Silent</div>',
            ]
            for case_key, case_label in notification_cases:
                enabled_checked = (
                    "checked" if provider_toggles.get(case_key, True) else ""
                )
                silent_checked = (
                    "checked" if provider_silent.get(case_key, False) else ""
                )
                cells.append(
                    f"""
                    <div class="notification-toggle-label">{case_label}</div>
                    <div class="notification-toggle-input toggle-cell">
                        {render_switch(f"notif-{provider}-{case_key}", enabled_checked)}
                    </div>
                    <div class="notification-toggle-input toggle-cell">
                        {render_switch(f"notif-{provider}-{case_key}-silent", silent_checked)}
                    </div>
                    """
                )
            return '<div class="notification-toggle-grid">' + "".join(cells) + "</div>"

        discord_toggle_rows = render_notification_toggle_rows("discord")
        telegram_toggle_rows = render_notification_toggle_rows("telegram")
        pushover_toggle_rows = render_notification_toggle_rows("pushover")
        notification_providers_json = json.dumps(NOTIFICATION_PROVIDERS)

        timeout_slow_mode_cells = [
            '<div class="notification-toggle-header">Timeout</div>',
            '<div class="notification-toggle-header toggle-cell">Slow Mode</div>',
        ]
        for timeout_key, timeout_data in TIMEOUT_SLOW_MODE_DEFINITIONS.items():
            timeout_label = timeout_data["label"]
            checked = "checked" if timeout_slow_mode_settings.get(timeout_key) else ""
            timeout_slow_mode_cells.append(
                f"""
                <div class="notification-toggle-label">
                    {timeout_label}
                    <div class="timeout-slow-mode-value" id="timeout-slow-mode-value-{timeout_key}"></div>
                </div>
                <div class="notification-toggle-input toggle-cell">
                    {render_switch(f"timeout-slow-{timeout_key}", checked)}
                </div>
                """
            )
        timeout_slow_mode_rows = (
            '<div class="notification-toggle-grid timeout-toggle-grid">'
            + "".join(timeout_slow_mode_cells)
            + "</div>"
        )

        info = f"""
        <h1><img src="{images.logo}" type="image/webp" alt="Quasarr logo" class="logo"/>Quasarr</h1>

        {status_bars}
        {captcha_hint}

        <div class="quick-actions">
            <a href="/packages" class="action-card">
                <span class="action-icon">📦</span>
                <span class="action-label">Packages</span>
            </a>
            <a href="/statistics" class="action-card">
                <span class="action-icon">📊</span>
                <span class="action-label">Statistics</span>
            </a>
            <a href="/hostnames" class="action-card">
                <span class="action-icon">🌐</span>
                <span class="action-label">Hostnames</span>
            </a>
            <a href="/categories" class="action-card">
                <span class="action-icon">📁</span>
                <span class="action-label">Categories</span>
            </a>
        </div>

        <div class="section">
            <details id="apiDetails">
                <summary id="apiSummary">⚙️ API</summary>
                <div class="api-settings">
                    <p class="api-hint">Use these settings for <strong>Newznab Indexer</strong> and <strong>SABnzbd Download Client</strong> in Radarr/Sonarr</p>

                    <div class="input-group">
                        <label>URL</label>
                        <div class="input-row">
                            <input id="urlInput" type="text" readonly value="{shared_state.values["internal_address"]}" />
                            <button id="copyUrl" type="button">Copy</button>
                        </div>
                    </div>

                    <div class="input-group">
                        <label>API Key</label>
                        <div class="input-row">
                            <input id="apiKeyInput" type="password" readonly value="{api_key}" />
                            <button id="toggleKey" type="button">Show</button>
                            <button id="copyKey" type="button">Copy</button>
                        </div>
                    </div>

                    <p style="margin-top: 15px;">
                        {render_button("Regenerate API Key", "secondary", {"onclick": "confirmRegenerateApiKey()"})}
                    </p>

                    <div class="timeout-slow-mode-section">
                        <label class="timeout-slow-mode-heading">Timeouts</label>
                        <p class="api-hint">
                            By default, Quasarr uses strict request timeouts so manual searches stay within a reasonable timeframe.
                            Enable slow mode only if you are willing to wait longer on slow sites.
                        </p>
                        <div class="notification-toggle-list">
                            {timeout_slow_mode_rows}
                        </div>
                        <div id="timeout-slow-mode-status" class="notification-status"></div>
                        <p class="timeout-slow-mode-actions">{render_button("Save Timeout Settings", "primary", {"onclick": "saveTimeoutSlowModeSettings()", "type": "button", "id": "timeoutSlowModeSaveBtn"})}</p>
                    </div>
                </div>
            </details>
        </div>

        <div class="section">
            <details id="filecryptDetails">
                <summary id="filecryptSummary">🔒 Link Protection</summary>
                <div class="api-settings">
                    <div class="notification-provider-card">
                        <div class="notification-toggle-grid timeout-toggle-grid">
                            <div class="notification-toggle-header">Crypter</div>
                            <div class="notification-toggle-header toggle-cell">Enabled</div>
                            <div class="notification-toggle-label">
                                <span class="setting-row-title">Filecrypt</span>
                                <span class="setting-row-sub">Decrypt CAPTCHA-protected filecrypt links</span>
                            </div>
                            <div class="notification-toggle-input toggle-cell">
                                {render_switch("filecrypt-enabled", filecrypt_checked)}
                            </div>
                        </div>
                    </div>
                    <p class="api-hint setting-row-hint">
                        Disable while filecrypt CAPTCHAs are unsolvable. Affected releases fail so *arr grabs an alternative. Applies to new grabs only.
                    </p>
                    <div id="filecrypt-status" class="notification-status"></div>
                    <p>{render_button("Save Filecrypt Setting", "primary", {"onclick": "saveFilecryptSettings()", "type": "button", "id": "filecryptSaveBtn"})}</p>
                </div>
            </details>
        </div>

        <div class="section">
            <details id="jdDetails">
                <summary id="jdSummary"><img src="{images.jdownloader}" type="image/webp" alt="JDownloader logo" class="inline-icon"/> JDownloader</summary>
                <div class="api-settings">
                    <p class="api-hint"><strong>JDownloader must be running and connected to My JDownloader!</strong></p>
                    
                    <div id="jd-login-section">
                        <div class="input-group">
                            <label>E-Mail</label>
                            <div class="input-row">
                                <input type="text" id="jd-user" placeholder="user@example.org" value="{jd_user}">
                            </div>
                        </div>
                        <div class="input-group">
                            <label>Password</label>
                            <div class="input-row">
                                <input type="password" id="jd-pass" placeholder="Password" value="{jd_pass}">
                            </div>
                        </div>
                        <div id="jd-status" style="margin-bottom: 10px; font-size: 0.9em; min-height: 1.2em;"></div>
                        <p>{render_button("Verify Credentials", "primary", {"onclick": "verifyJDCredentials()"})}</p>
                    </div>

                    <div id="jd-device-section" style="display:none; margin-top: 15px; border-top: 1px solid var(--card-border, #dee2e6); padding-top: 15px;">
                        <input type="hidden" id="jd-current-device" value="{jd_device}">
                        <div class="input-group">
                            <label>Select Instance</label>
                            <div class="input-row">
                                <select id="jd-device-select" style="flex:1; padding:8px; border-radius:4px; border:1px solid var(--input-border, #ced4da); background:var(--input-bg, #e9ecef); color:var(--fg-color, #212529);"></select>
                            </div>
                        </div>
                        <div id="jd-save-status" style="margin-bottom: 10px; font-size: 0.9em; min-height: 1.2em;"></div>
                        <p>{render_button("Save", "primary", {"onclick": "saveJDSettings()"})}</p>
                    </div>
                </div>
            </details>
        </div>

        <div class="section">
            <details id="flaresolverrDetails">
                <summary id="flaresolverrSummary"><img src="{images.flaresolverr}" type="image/webp" alt="JDownloader logo" class="inline-icon"/> FlareSolverr</summary>
                <div class="api-settings">
                    {flaresolverr_warning}
                    <p class="api-hint">
                        <a href="https://github.com/rix1337/flaresolverr-next" target="_blank">flaresolverr-next</a>
                        must be running and reachable to Quasarr for some sites to work.
                    </p>

                    <form action="/api/flaresolverr" method="post" onsubmit="return handleFlareSolverrSubmit(this)">
                        <div class="input-group">
                            <label for="fsUrl">URL</label>
                            <div class="input-row">
                                <input type="text" id="fsUrl" name="url" placeholder="http://192.168.0.1:8191/v1" value="{flaresolverr_url}">
                                <button type="submit" id="fsSubmitBtn">Save</button>
                            </div>
                        </div>
                    </form>
                </div>
            </details>
        </div>

        <div class="section">
            <details id="notificationsDetails">
                <summary id="notificationsSummary">🔔 Notifications</summary>
                <div class="api-settings">
                    <p class="api-hint">
                        It is recommended to configure one provider below for an optimal user experience.
                    </p>

                    <div class="notification-provider-card">
                        <h4><img src="{images.discord}" type="image/webp" alt="Discord logo" class="inline-icon"/> Discord</h4>
                        <div class="input-group">
                            <label for="notification-discord-webhook">Webhook URL</label>
                            <div class="input-row">
                                <input type="text" id="notification-discord-webhook" placeholder="https://discord.com/api/webhooks/..." value="{discord_webhook}">
                            </div>
                        </div>
                        <div class="notification-toggle-list">
                            {discord_toggle_rows}
                        </div>
                        <div id="notification-discord-status" class="notification-status"></div>
                        <p>{render_button("Send Discord Test", "secondary", {"onclick": "sendNotificationTest('discord')", "type": "button"})}</p>
                    </div>

                    <div class="notification-provider-card">
                        <h4><img src="{images.telegram}" type="image/webp" alt="Telegram logo" class="inline-icon"/> Telegram</h4>
                        <div class="input-group">
                            <label for="notification-telegram-token">Bot Token</label>
                            <div class="input-row">
                                <input type="text" id="notification-telegram-token" placeholder="123456789:..." value="{telegram_bot_token}">
                            </div>
                        </div>
                        <div class="input-group">
                            <label for="notification-telegram-chat-id">Chat ID</label>
                            <div class="input-row">
                                <input type="text" id="notification-telegram-chat-id" placeholder="987654321 or @channel" value="{telegram_chat_id}">
                            </div>
                        </div>
                        <div class="notification-toggle-list">
                            {telegram_toggle_rows}
                        </div>
                        <div id="notification-telegram-status" class="notification-status"></div>
                        <p>{render_button("Send Telegram Test", "secondary", {"onclick": "sendNotificationTest('telegram')", "type": "button"})}</p>
                    </div>

                    <div class="notification-provider-card">
                        <h4><img src="{images.pushover}" type="image/webp" alt="Pushover logo" class="inline-icon"/> Pushover</h4>
                        <div class="input-group">
                            <label for="notification-pushover-token">Application API Token</label>
                            <div class="input-row">
                                <input type="text" id="notification-pushover-token" placeholder="30-character application token" value="{pushover_api_token}">
                            </div>
                        </div>
                        <div class="input-group">
                            <label for="notification-pushover-user-key">User or Group Key</label>
                            <div class="input-row">
                                <input type="text" id="notification-pushover-user-key" placeholder="30-character user or group key" value="{pushover_user_key}">
                            </div>
                        </div>
                        <div class="notification-toggle-list">
                            {pushover_toggle_rows}
                        </div>
                        <div id="notification-pushover-status" class="notification-status"></div>
                        <p>{render_button("Send Pushover Test", "secondary", {"onclick": "sendNotificationTest('pushover')", "type": "button"})}</p>
                    </div>

                    <div id="notification-save-status" class="notification-status"></div>
                    <p>{render_button("Save Notification Settings", "primary", {"onclick": "saveNotificationSettings()", "type": "button", "id": "notificationSaveBtn"})}</p>
                </div>
            </details>
        </div>

        <div class="section">
            <details id="arrDetails">
                <summary id="arrSummary">🎬 *arr</summary>
                <div class="api-settings">
                    <p class="api-hint">
                        Required for configured movie or TV sources. Configure the client(s) you use.
                    </p>

                    <div class="notification-provider-card">
                        <h4>🎬 Radarr</h4>
                        <p class="api-hint">Look up movie metadata via Radarr's API.</p>
                        <div class="input-group">
                            <label for="radarrUrl">URL</label>
                            <div class="input-row">
                                <input type="text" id="radarrUrl" placeholder="http://192.168.0.1:7878" value="{radarr_url}">
                            </div>
                        </div>
                        <div class="input-group">
                            <label for="radarrApiKey">API Key</label>
                            <div class="input-row">
                                <input type="text" id="radarrApiKey" placeholder="Radarr API key" value="{radarr_api_key}">
                            </div>
                        </div>
                        <div id="radarr-save-status" class="notification-status"></div>
                        <p>
                            {render_button("Save Radarr Settings", "primary", {"onclick": "saveRadarrSettings()", "type": "button", "id": "radarrSaveBtn"})}
                            {render_button("Clear", "secondary", {"onclick": "confirmClearRadarrSettings()", "type": "button", "id": "radarrClearBtn"})}
                        </p>
                    </div>

                    <div class="notification-provider-card">
                        <h4>📺 Sonarr</h4>
                        <p class="api-hint">Look up series metadata via Sonarr's API.</p>
                        <div class="input-group">
                            <label for="sonarrUrl">URL</label>
                            <div class="input-row">
                                <input type="text" id="sonarrUrl" placeholder="http://192.168.0.1:8989" value="{sonarr_url}">
                            </div>
                        </div>
                        <div class="input-group">
                            <label for="sonarrApiKey">API Key</label>
                            <div class="input-row">
                                <input type="text" id="sonarrApiKey" placeholder="Sonarr API key" value="{sonarr_api_key}">
                            </div>
                        </div>
                        <div id="sonarr-save-status" class="notification-status"></div>
                        <p>
                            {render_button("Save Sonarr Settings", "primary", {"onclick": "saveSonarrSettings()", "type": "button", "id": "sonarrSaveBtn"})}
                            {render_button("Clear", "secondary", {"onclick": "confirmClearSonarrSettings()", "type": "button", "id": "sonarrClearBtn"})}
                        </p>
                    </div>
                </div>
            </details>
        </div>

        <div class="section help-link">
            <a href="https://github.com/rix1337/Quasarr?tab=readme-ov-file#instructions" target="_blank">
                📖 Setup Instructions & Documentation
            </a>
        </div>

        <style>
            .status-bar {{
                display: flex;
                justify-content: center;
                gap: 20px;
                margin-bottom: 20px;
                flex-wrap: wrap;
            }}
            .status-pill {{
                font-size: 0.9em;
                padding: 8px 16px;
                border-radius: 0.5rem;
                font-weight: 500;
                cursor: default;
            }}
            .status-pill.success {{
                background: var(--status-success-bg, #e8f5e9);
                color: var(--status-success-color, #2e7d32);
                border: 1px solid var(--status-success-border, #a5d6a7);
            }}
            .status-pill.warning {{
                background: var(--status-warning-bg, #fff3e0);
                color: var(--status-warning-color, #f57c00);
                border: 1px solid var(--status-warning-border, #ffb74d);
            }}
            .status-pill.error {{
                background: var(--status-error-bg, #ffebee);
                color: var(--status-error-color, #c62828);
                border: 1px solid var(--status-error-border, #ef9a9a);
            }}

            .alert {{
                display: flex;
                flex-direction: column;
                align-items: center;
                text-align: center;
                gap: 12px;
                padding: 20px;
                border-radius: 8px;
                margin-bottom: 25px;
            }}
            .alert-warning {{
                background: var(--alert-warning-bg, #fff3e0);
                border: 1px solid var(--alert-warning-border, #ffb74d);
            }}
            .alert-icon {{ font-size: 1.5em; }}
            .alert-content {{ }}
            .alert-content a {{ color: var(--link-color, #0066cc); }}
            .alert-action {{ margin-top: 5px; }}

            .quick-actions {{
                display: grid;
                grid-template-columns: repeat(4, 1fr);
                gap: 12px;
                max-width: 500px;
                margin: 0 auto 30px auto;
            }}
            @media (max-width: 500px) {{
                .quick-actions {{
                    grid-template-columns: repeat(2, 1fr);
                }}
            }}
            .action-card {{
                display: flex;
                flex-direction: column;
                align-items: center;
                padding: 15px 10px;
                background: var(--card-bg, #f8f9fa);
                border: 1px solid var(--card-border, #dee2e6);
                border-radius: 10px;
                text-decoration: none;
                color: inherit;
                transition: transform 0.2s, box-shadow 0.2s;
            }}
            .action-card:hover {{
                transform: translateY(-2px);
                box-shadow: 0 4px 12px var(--card-shadow, rgba(0,0,0,0.1));
                border-color: var(--card-hover-border, #007bff);
            }}
            .action-icon {{ font-size: 1.8em; margin-bottom: 5px; }}
            .action-label {{ font-size: 0.85em; font-weight: 500; }}

            .section {{ margin: 20px 0; max-width: 500px; margin-left: auto; margin-right: auto; }}
            details {{ background: var(--card-bg, #f8f9fa); border: 1px solid var(--card-border, #dee2e6); border-radius: 8px; }}
            summary {{
                cursor: pointer;
                padding: 12px 15px;
                font-weight: 500;
                list-style: none;
            }}
            summary::-webkit-details-marker {{ display: none; }}
            summary::before {{ content: '▶ '; font-size: 0.8em; }}
            details[open] summary::before {{ content: '▼ '; }}
            summary:hover {{ color: var(--link-color, #0066cc); }}

            .api-settings {{ padding: 15px; border-top: 1px solid var(--card-border, #dee2e6); }}
            .api-hint {{ font-size: 0.9em; color: var(--text-muted, #666); margin-bottom: 15px; }}
            .input-group {{ margin-bottom: 15px; }}
            .input-group label {{ display: block; font-weight: 500; margin-bottom: 6px; font-size: 0.95em; text-align: left; }}
            .input-row {{
                display: flex;
                gap: 8px;
                align-items: stretch;
            }}
            .input-row input {{
                flex: 1;
                padding: 8px 12px;
                border: 1px solid var(--input-border, #ced4da);
                border-radius: 4px;
                font-family: monospace;
                font-size: 0.9em;
                background: var(--input-bg, #e9ecef);
                color: var(--fg-color, #212529);
                min-width: 0;
                margin: 0;
            }}
            .input-row select {{
                flex: 1;
                padding: 8px 12px;
                border: 1px solid var(--input-border, #ced4da);
                border-radius: 4px;
                font-size: 0.9em;
                background: var(--input-bg, #e9ecef);
                color: var(--fg-color, #212529);
                min-width: 0;
                margin: 0;
            }}
            .input-row button {{
                padding: 8px 16px;
                border: none;
                border-radius: 4px;
                cursor: pointer;
                font-size: 0.9em;
                font-weight: 500;
                transition: background 0.2s;
                white-space: nowrap;
                margin: 0;
                flex-shrink: 0;
            }}
            #copyUrl, #copyKey, #fsSubmitBtn {{
                background: var(--btn-primary-bg, #007bff);
                color: white;
            }}
            #copyUrl:hover, #copyKey:hover, #fsSubmitBtn:hover {{
                background: var(--btn-primary-hover, #0056b3);
            }}
            #toggleKey {{
                background: var(--btn-secondary-bg, #6c757d);
                color: white;
            }}
            #toggleKey:hover {{
                background: var(--btn-secondary-hover, #545b62);
            }}

            .timeout-slow-mode-section {{
                margin-top: 18px;
                padding-top: 14px;
                border-top: 1px solid var(--card-border, #dee2e6);
                text-align: left;
            }}
            .timeout-slow-mode-heading {{
                display: block;
                font-weight: 500;
                margin-bottom: 6px;
                font-size: 0.95em;
                text-align: left;
            }}
            .timeout-slow-mode-actions {{
                text-align: center;
            }}
            .timeout-slow-mode-value {{
                margin-top: 2px;
                font-size: 0.82em;
                color: var(--text-muted, #666);
            }}

            .notification-provider-card {{
                border: 1px solid var(--card-border, #dee2e6);
                border-radius: 8px;
                padding: 12px;
                margin-bottom: 14px;
                background: var(--card-bg, #f8f9fa);
            }}
            .notification-provider-card h4 {{
                margin: 0 0 10px 0;
                font-size: 1em;
                display: flex;
                align-items: center;
                gap: 8px;
            }}
            .notification-toggle-list {{
                margin-top: 6px;
                margin-bottom: 10px;
            }}
            .notification-toggle-grid {{
                display: grid;
                grid-template-columns: minmax(0, 1fr) repeat(2, 96px);
                align-items: center;
                column-gap: 24px;
                row-gap: 10px;
                font-size: 0.9em;
            }}
            .notification-toggle-grid .notification-toggle-header {{
                font-size: 0.85em;
                font-weight: 600;
                padding-bottom: 4px;
                min-width: 0;
            }}
            .notification-toggle-grid .notification-toggle-label {{
                text-align: left;
                min-width: 0;
                display: flex;
                flex-direction: column;
                gap: 3px;
            }}
            .notification-toggle-grid .notification-toggle-header.toggle-cell,
            .notification-toggle-grid .toggle-cell {{
                text-align: center;
                white-space: nowrap;
                justify-self: center;
                width: 96px;
            }}
            .notification-toggle-grid.timeout-toggle-grid {{
                grid-template-columns: minmax(0, 1fr) 96px;
            }}
            .notification-toggle-grid .notification-toggle-input {{
                display: flex;
                align-items: center;
                justify-content: center;
                min-height: 24px;
            }}
            .setting-row-title {{
                font-weight: 600;
                font-size: 0.95em;
                color: var(--fg-color, #212529);
            }}
            .setting-row-sub {{
                font-size: 0.82em;
                color: var(--text-muted, #666);
            }}
            .setting-row-hint {{
                margin: 12px 2px 0;
                text-align: left;
            }}
            .switch {{
                position: relative;
                flex: 0 0 auto;
                display: inline-block;
                width: 40px;
                height: 24px;
            }}
            .switch input {{
                position: absolute;
                inset: 0;
                width: 100%;
                height: 100%;
                margin: 0;
                opacity: 0;
                cursor: pointer;
                z-index: 1;
            }}
            .switch-slider {{
                position: absolute;
                inset: 0;
                border-radius: 999px;
                background: var(--input-border, #adb5bd);
                transition: background-color 0.2s ease;
            }}
            .switch-slider::before {{
                content: "";
                position: absolute;
                width: 18px;
                height: 18px;
                left: 3px;
                top: 3px;
                border-radius: 50%;
                background: #fff;
                box-shadow: 0 1px 2px rgba(0, 0, 0, 0.35);
                transition: transform 0.2s ease;
            }}
            .switch input:checked + .switch-slider {{
                background: var(--btn-primary-bg, #1a73e8);
            }}
            .switch input:checked + .switch-slider::before {{
                transform: translateX(16px);
            }}
            .switch input:focus-visible + .switch-slider {{
                outline: 2px solid var(--link-color, #0066cc);
                outline-offset: 2px;
            }}
            .switch input:disabled {{
                cursor: default;
            }}
            @media (max-width: 500px) {{
                .notification-toggle-grid {{
                    grid-template-columns: minmax(0, 1fr) repeat(2, 72px);
                    column-gap: 12px;
                }}
                .notification-toggle-grid.timeout-toggle-grid {{
                    grid-template-columns: minmax(0, 1fr) 72px;
                }}
                .notification-toggle-grid .notification-toggle-header.toggle-cell,
                .notification-toggle-grid .toggle-cell {{
                    width: 72px;
                }}
            }}
            @media (max-width: 380px) {{
                .notification-toggle-grid {{
                    grid-template-columns: minmax(0, 1fr) repeat(2, 64px);
                    column-gap: 8px;
                }}
                .notification-toggle-grid.timeout-toggle-grid {{
                    grid-template-columns: minmax(0, 1fr) 64px;
                }}
                .notification-toggle-grid .notification-toggle-header {{
                    font-size: 0.8em;
                }}
                .notification-toggle-grid .notification-toggle-header.toggle-cell,
                .notification-toggle-grid .toggle-cell {{
                    width: 64px;
                }}
            }}
            .notification-status {{
                min-height: 1.2em;
                font-size: 0.9em;
                margin-bottom: 8px;
                text-align: left;
            }}

            .help-link {{
                text-align: center;
                padding: 15px;
                background: var(--card-bg, #f8f9fa);
                border: 1px solid var(--card-border, #dee2e6);
                border-radius: 8px;
            }}
            .help-link a {{
                color: var(--link-color, #0066cc);
                text-decoration: none;
                font-weight: 500;
            }}
            .help-link a:hover {{ text-decoration: underline; }}

            .logout-link {{
                display: block;
                text-align: center;
                margin-top: 20px;
                font-size: 0.85em;
            }}
            .logout-link a {{
                color: var(--text-muted, #666);
                text-decoration: none;
            }}
            .logout-link a:hover {{ text-decoration: underline; }}

            /* Dark mode */
            @media (prefers-color-scheme: dark) {{
                :root {{
                    --status-success-bg: #1c4532;
                    --status-success-color: #68d391;
                    --status-success-border: #276749;
                    --status-warning-bg: #3d3520;
                    --status-warning-color: #ffb74d;
                    --status-warning-border: #d69e2e;
                    --status-error-bg: #3d2d2d;
                    --status-error-color: #fc8181;
                    --status-error-border: #c53030;
                    --alert-warning-bg: #3d3520;
                    --alert-warning-border: #d69e2e;
                    --card-bg: #2d3748;
                    --card-border: #4a5568;
                    --card-shadow: rgba(0,0,0,0.3);
                    --card-hover-border: #63b3ed;
                    --text-muted: #a0aec0;
                    --link-color: #63b3ed;
                    --input-bg: #1a202c;
                    --input-border: #4a5568;
                    --btn-primary-bg: #3182ce;
                    --btn-primary-hover: #2c5282;
                    --btn-secondary-bg: #4a5568;
                    --btn-secondary-hover: #2d3748;
                }}
            }}
        </style>

        <script>
            (function() {{
                var urlInput = document.getElementById('urlInput');
                var copyUrlBtn = document.getElementById('copyUrl');
                var apiInput = document.getElementById('apiKeyInput');
                var toggleBtn = document.getElementById('toggleKey');
                var copyKeyBtn = document.getElementById('copyKey');

                function copyToClipboard(text, button, callback) {{
                    if (navigator.clipboard && navigator.clipboard.writeText) {{
                        navigator.clipboard.writeText(text).then(function() {{
                            var originalText = button.innerText;
                            button.innerText = 'Copied!';
                            setTimeout(function() {{
                                button.innerText = originalText;
                                if (callback) callback();
                            }}, 1500);
                        }}).catch(function() {{
                            fallbackCopy(text, button, callback);
                        }});
                    }} else {{
                        fallbackCopy(text, button, callback);
                    }}
                }}

                function fallbackCopy(text, button, callback) {{
                    var textarea = document.createElement('textarea');
                    textarea.value = text;
                    textarea.style.position = 'fixed';
                    textarea.style.opacity = '0';
                    document.body.appendChild(textarea);
                    textarea.select();
                    try {{
                        document.execCommand('copy');
                        var originalText = button.innerText;
                        button.innerText = 'Copied!';
                        setTimeout(function() {{
                            button.innerText = originalText;
                            if (callback) callback();
                        }}, 1500);
                    }} catch (e) {{
                        showModal('Error', 'Copy failed. Please copy manually.');
                    }}
                    document.body.removeChild(textarea);
                }}

                if (copyUrlBtn) {{
                    copyUrlBtn.onclick = function() {{
                        copyToClipboard(urlInput.value, copyUrlBtn);
                    }};
                }}

                if (copyKeyBtn) {{
                    copyKeyBtn.onclick = function() {{
                        copyToClipboard(apiInput.value, copyKeyBtn, function() {{
                            // Re-hide the API Key after copying
                            apiInput.type = 'password';
                            toggleBtn.innerText = 'Show';
                        }});
                    }};
                }}

                if (toggleBtn) {{
                    toggleBtn.onclick = function() {{
                        if (apiInput.type === 'password') {{
                            apiInput.type = 'text';
                            toggleBtn.innerText = 'Hide';
                        }} else {{
                            apiInput.type = 'password';
                            toggleBtn.innerText = 'Show';
                        }}
                    }};
                }}
            }})();

            function confirmRegenerateApiKey() {{
                showModal(
                    'Regenerate API Key?', 
                    'Are you sure you want to regenerate the API Key? This will invalidate the current key.', 
                    `<button class="btn-secondary" onclick="closeModal()">Cancel</button>
                     <button class="btn-primary" onclick="location.href='/regenerate-api-key'">Regenerate</button>`
                );
            }}
            
            function handleFlareSolverrSubmit(form) {{
                var btn = document.getElementById('fsSubmitBtn');
                if (btn) {{ btn.disabled = true; btn.textContent = 'Saving...'; }}
                return true;
            }}

            function verifyJDCredentials() {{
                var user = document.getElementById('jd-user').value;
                var pass = document.getElementById('jd-pass').value;
                var statusDiv = document.getElementById('jd-status');
                
                statusDiv.innerHTML = 'Verifying...';
                statusDiv.style.color = 'var(--text-muted, #666)';
                
                quasarrApiFetch('/api/jdownloader/verify', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{ user: user, pass: pass }})
                }})
                .then(response => response.json())
                .then(data => {{
                    if (data.success) {{
                        var select = document.getElementById('jd-device-select');
                        select.innerHTML = '';
                        var currentDevice = document.getElementById('jd-current-device').value;
                        data.devices.forEach(device => {{
                            var opt = document.createElement('option');
                            opt.value = device;
                            opt.innerHTML = device;
                            if (device === currentDevice) {{
                                opt.selected = true;
                            }}
                            select.appendChild(opt);
                        }});
                        
                        document.getElementById('jd-device-section').style.display = 'block';
                        statusDiv.innerHTML = '✅ Credentials verified';
                        statusDiv.style.color = 'var(--status-success-color, #2e7d32)';
                    }} else {{
                        statusDiv.innerHTML = '❌ ' + (data.message || 'Verification failed');
                        statusDiv.style.color = 'var(--status-error-color, #c62828)';
                        document.getElementById('jd-device-section').style.display = 'none';
                    }}
                }})
                .catch(error => {{
                    statusDiv.innerHTML = '❌ Error: ' + error.message;
                    statusDiv.style.color = 'var(--status-error-color, #c62828)';
                }});
            }}

            function saveJDSettings() {{
                var user = document.getElementById('jd-user').value;
                var pass = document.getElementById('jd-pass').value;
                var device = document.getElementById('jd-device-select').value;
                var statusDiv = document.getElementById('jd-save-status');
                
                statusDiv.innerHTML = 'Saving...';
                statusDiv.style.color = 'var(--text-muted, #666)';
                
                quasarrApiFetch('/api/jdownloader/save', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{ user: user, pass: pass, device: device }})
                }})
                .then(response => response.json())
                .then(data => {{
                    if (data.success) {{
                        statusDiv.innerHTML = '✅ ' + data.message;
                        statusDiv.style.color = 'var(--status-success-color, #2e7d32)';
                        setTimeout(function() {{
                            window.location.reload();
                        }}, 1000);
                    }} else {{
                        statusDiv.innerHTML = '❌ ' + data.message;
                        statusDiv.style.color = 'var(--status-error-color, #c62828)';
                    }}
                }})
                .catch(error => {{
                    statusDiv.innerHTML = '❌ Error: ' + error.message;
                    statusDiv.style.color = 'var(--status-error-color, #c62828)';
                }});
            }}

            var notificationCases = {notification_cases_json};
            var timeoutSlowModeKeys = {timeout_slow_mode_keys_json};
            var timeoutSlowModeDefinitions = {timeout_slow_mode_definitions_json};

            function setNotificationStatus(elementId, message, isSuccess) {{
                var statusElement = document.getElementById(elementId);
                if (!statusElement) {{
                    return;
                }}

                statusElement.innerHTML = message || '';
                if (!message) {{
                    statusElement.style.color = '';
                    return;
                }}

                statusElement.style.color = isSuccess
                    ? 'var(--status-success-color, #2e7d32)'
                    : 'var(--status-error-color, #c62828)';
            }}

            function collectNotificationPayload() {{
                var payload = {{
                    discord_webhook: document.getElementById('notification-discord-webhook').value.trim(),
                    telegram_bot_token: document.getElementById('notification-telegram-token').value.trim(),
                    telegram_chat_id: document.getElementById('notification-telegram-chat-id').value.trim(),
                    pushover_api_token: document.getElementById('notification-pushover-token').value.trim(),
                    pushover_user_key: document.getElementById('notification-pushover-user-key').value.trim(),
                    toggles: {{}},
                    silent: {{}}
                }};

                {notification_providers_json}.forEach(function(provider) {{
                    payload.toggles[provider] = {{}};
                    payload.silent[provider] = {{}};
                    notificationCases.forEach(function(notificationCase) {{
                        var input = document.getElementById('notif-' + provider + '-' + notificationCase);
                        var silentInput = document.getElementById('notif-' + provider + '-' + notificationCase + '-silent');
                        payload.toggles[provider][notificationCase] = !!(input && input.checked);
                        payload.silent[provider][notificationCase] = !!(silentInput && silentInput.checked);
                    }});
                }});

                return payload;
            }}

            async function persistNotificationSettings(showSuccessMessage) {{
                var saveButton = document.getElementById('notificationSaveBtn');
                setNotificationStatus('notification-save-status', 'Saving notification settings...', true);

                if (saveButton) {{
                    saveButton.disabled = true;
                    saveButton.textContent = 'Saving...';
                }}

                try {{
                    var response = await quasarrApiFetch('/api/notifications/settings', {{
                        method: 'POST',
                        headers: {{ 'Content-Type': 'application/json' }},
                        body: JSON.stringify(collectNotificationPayload())
                    }});
                    var data = await response.json();

                    if (!response.ok || !data.success) {{
                        throw new Error(data.message || 'Failed to save notification settings');
                    }}

                    if (showSuccessMessage) {{
                        setNotificationStatus('notification-save-status', '✅ ' + data.message, true);
                    }} else {{
                        setNotificationStatus('notification-save-status', '', true);
                    }}

                    return {{ success: true, data: data }};
                }} catch (error) {{
                    setNotificationStatus('notification-save-status', '❌ ' + error.message, false);
                    return {{ success: false, error: error.message }};
                }} finally {{
                    if (saveButton) {{
                        saveButton.disabled = false;
                        saveButton.textContent = 'Save Notification Settings';
                    }}
                }}
            }}

            async function saveNotificationSettings() {{
                await persistNotificationSettings(true);
            }}

            async function sendNotificationTest(provider) {{
                var statusId = 'notification-' + provider + '-status';

                setNotificationStatus(statusId, 'Saving settings before test...', true);

                var saveResult = await persistNotificationSettings(false);
                if (!saveResult.success) {{
                    setNotificationStatus(statusId, '❌ Save failed. Fix settings and retry.', false);
                    return;
                }}

                setNotificationStatus(statusId, 'Sending test message...', true);

                try {{
                    var response = await quasarrApiFetch('/api/notifications/test', {{
                        method: 'POST',
                        headers: {{ 'Content-Type': 'application/json' }},
                        body: JSON.stringify({{ provider: provider }})
                    }});
                    var data = await response.json();

                    if (!response.ok || !data.success) {{
                        throw new Error(data.message || 'Failed to send test message');
                    }}

                    setNotificationStatus(statusId, '✅ ' + data.message, true);
                }} catch (error) {{
                    setNotificationStatus(statusId, '❌ ' + error.message, false);
                }}
            }}

            async function saveRadarrSettings() {{
                var saveButton = document.getElementById('radarrSaveBtn');
                var urlInput = document.getElementById('radarrUrl');
                var apiKeyInput = document.getElementById('radarrApiKey');
                setNotificationStatus('radarr-save-status', 'Saving Radarr settings...', true);

                if (saveButton) {{
                    saveButton.disabled = true;
                    saveButton.textContent = 'Saving...';
                }}

                try {{
                    var response = await quasarrApiFetch('/api/radarr/settings', {{
                        method: 'POST',
                        headers: {{ 'Content-Type': 'application/json' }},
                        body: JSON.stringify({{
                            url: urlInput ? urlInput.value : '',
                            api_key: apiKeyInput ? apiKeyInput.value : ''
                        }})
                    }});
                    var data = await response.json();
                    if (!response.ok || !data.success) {{
                        throw new Error(data.message || 'Failed to save Radarr settings');
                    }}
                    setNotificationStatus('radarr-save-status', '✅ ' + data.message, true);
                }} catch (error) {{
                    setNotificationStatus('radarr-save-status', '❌ ' + error.message, false);
                }} finally {{
                    if (saveButton) {{
                        saveButton.disabled = false;
                        saveButton.textContent = 'Save Radarr Settings';
                    }}
                }}
            }}

            function confirmClearRadarrSettings() {{
                showModal(
                    'Clear Radarr Settings?',
                    'This removes the saved Radarr URL and API key. Sites that require Radarr will stop working until you configure it again.',
                    `<button class="btn-secondary" onclick="closeModal()">Cancel</button>
                     <button class="btn-primary" onclick="closeModal(); clearRadarrSettings();">Clear</button>`
                );
            }}

            async function clearRadarrSettings() {{
                var clearButton = document.getElementById('radarrClearBtn');
                var saveButton = document.getElementById('radarrSaveBtn');
                var urlInput = document.getElementById('radarrUrl');
                var apiKeyInput = document.getElementById('radarrApiKey');
                setNotificationStatus('radarr-save-status', 'Clearing Radarr settings...', true);

                if (clearButton) {{
                    clearButton.disabled = true;
                    clearButton.textContent = 'Clearing...';
                }}
                if (saveButton) {{ saveButton.disabled = true; }}

                try {{
                    var response = await quasarrApiFetch('/api/radarr/settings', {{
                        method: 'POST',
                        headers: {{ 'Content-Type': 'application/json' }},
                        body: JSON.stringify({{ url: '', api_key: '' }})
                    }});
                    var data = await response.json();
                    if (!response.ok || !data.success) {{
                        throw new Error(data.message || 'Failed to clear Radarr settings');
                    }}
                    if (urlInput) {{ urlInput.value = ''; }}
                    if (apiKeyInput) {{ apiKeyInput.value = ''; }}
                    setNotificationStatus('radarr-save-status', '✅ Radarr settings cleared', true);
                }} catch (error) {{
                    setNotificationStatus('radarr-save-status', '❌ ' + error.message, false);
                }} finally {{
                    if (clearButton) {{
                        clearButton.disabled = false;
                        clearButton.textContent = 'Clear';
                    }}
                    if (saveButton) {{ saveButton.disabled = false; }}
                }}
            }}

            async function saveSonarrSettings() {{
                var saveButton = document.getElementById('sonarrSaveBtn');
                var urlInput = document.getElementById('sonarrUrl');
                var apiKeyInput = document.getElementById('sonarrApiKey');
                setNotificationStatus('sonarr-save-status', 'Saving Sonarr settings...', true);

                if (saveButton) {{
                    saveButton.disabled = true;
                    saveButton.textContent = 'Saving...';
                }}

                try {{
                    var response = await quasarrApiFetch('/api/sonarr/settings', {{
                        method: 'POST',
                        headers: {{ 'Content-Type': 'application/json' }},
                        body: JSON.stringify({{
                            url: urlInput ? urlInput.value : '',
                            api_key: apiKeyInput ? apiKeyInput.value : ''
                        }})
                    }});
                    var data = await response.json();
                    if (!response.ok || !data.success) {{
                        throw new Error(data.message || 'Failed to save Sonarr settings');
                    }}
                    setNotificationStatus('sonarr-save-status', '✅ ' + data.message, true);
                }} catch (error) {{
                    setNotificationStatus('sonarr-save-status', '❌ ' + error.message, false);
                }} finally {{
                    if (saveButton) {{
                        saveButton.disabled = false;
                        saveButton.textContent = 'Save Sonarr Settings';
                    }}
                }}
            }}

            function confirmClearSonarrSettings() {{
                showModal(
                    'Clear Sonarr Settings?',
                    'This removes the saved Sonarr URL and API key. Sites that require Sonarr will stop working until you configure it again.',
                    `<button class="btn-secondary" onclick="closeModal()">Cancel</button>
                     <button class="btn-primary" onclick="closeModal(); clearSonarrSettings();">Clear</button>`
                );
            }}

            async function clearSonarrSettings() {{
                var clearButton = document.getElementById('sonarrClearBtn');
                var saveButton = document.getElementById('sonarrSaveBtn');
                var urlInput = document.getElementById('sonarrUrl');
                var apiKeyInput = document.getElementById('sonarrApiKey');
                setNotificationStatus('sonarr-save-status', 'Clearing Sonarr settings...', true);

                if (clearButton) {{
                    clearButton.disabled = true;
                    clearButton.textContent = 'Clearing...';
                }}
                if (saveButton) {{ saveButton.disabled = true; }}

                try {{
                    var response = await quasarrApiFetch('/api/sonarr/settings', {{
                        method: 'POST',
                        headers: {{ 'Content-Type': 'application/json' }},
                        body: JSON.stringify({{ url: '', api_key: '' }})
                    }});
                    var data = await response.json();
                    if (!response.ok || !data.success) {{
                        throw new Error(data.message || 'Failed to clear Sonarr settings');
                    }}
                    if (urlInput) {{ urlInput.value = ''; }}
                    if (apiKeyInput) {{ apiKeyInput.value = ''; }}
                    setNotificationStatus('sonarr-save-status', '✅ Sonarr settings cleared', true);
                }} catch (error) {{
                    setNotificationStatus('sonarr-save-status', '❌ ' + error.message, false);
                }} finally {{
                    if (clearButton) {{
                        clearButton.disabled = false;
                        clearButton.textContent = 'Clear';
                    }}
                    if (saveButton) {{ saveButton.disabled = false; }}
                }}
            }}

            function collectTimeoutSlowModePayload() {{
                var settings = {{}};
                timeoutSlowModeKeys.forEach(function(timeoutKey) {{
                    var checkbox = document.getElementById('timeout-slow-' + timeoutKey);
                    settings[timeoutKey] = !!(checkbox && checkbox.checked);
                }});
                return {{ settings: settings }};
            }}

            function renderTimeoutSlowModeValue(timeoutKey) {{
                var meta = timeoutSlowModeDefinitions[timeoutKey];
                var checkbox = document.getElementById('timeout-slow-' + timeoutKey);
                var valueElement = document.getElementById('timeout-slow-mode-value-' + timeoutKey);
                if (!meta || !checkbox || !valueElement) {{
                    return;
                }}

                var effectiveSeconds = checkbox.checked
                    ? meta.slow_seconds
                    : meta.base_seconds;
                var modeLabel = checkbox.checked ? 'Slow Mode' : 'Normal';
                valueElement.textContent = 'Current: ' + effectiveSeconds + 's (' + modeLabel + ')';
            }}

            function bindTimeoutSlowModePreview() {{
                timeoutSlowModeKeys.forEach(function(timeoutKey) {{
                    var checkbox = document.getElementById('timeout-slow-' + timeoutKey);
                    if (!checkbox) {{
                        return;
                    }}

                    renderTimeoutSlowModeValue(timeoutKey);
                    checkbox.addEventListener('change', function() {{
                        renderTimeoutSlowModeValue(timeoutKey);
                    }});
                }});
            }}

            async function saveTimeoutSlowModeSettings() {{
                var saveButton = document.getElementById('timeoutSlowModeSaveBtn');
                setNotificationStatus('timeout-slow-mode-status', 'Saving timeout settings...', true);

                if (saveButton) {{
                    saveButton.disabled = true;
                    saveButton.textContent = 'Saving...';
                }}

                try {{
                    var response = await quasarrApiFetch('/api/timeouts/settings', {{
                        method: 'POST',
                        headers: {{ 'Content-Type': 'application/json' }},
                        body: JSON.stringify(collectTimeoutSlowModePayload())
                    }});
                    var data = await response.json();
                    if (!response.ok || !data.success) {{
                        throw new Error(data.message || 'Failed to save timeout settings');
                    }}

                    if (data.settings && typeof data.settings === 'object') {{
                        timeoutSlowModeKeys.forEach(function(timeoutKey) {{
                            if (Object.prototype.hasOwnProperty.call(data.settings, timeoutKey)) {{
                                var checkbox = document.getElementById('timeout-slow-' + timeoutKey);
                                if (checkbox) {{
                                    checkbox.checked = !!data.settings[timeoutKey];
                                }}
                            }}
                            renderTimeoutSlowModeValue(timeoutKey);
                        }});
                    }}

                    setNotificationStatus('timeout-slow-mode-status', '✅ ' + data.message, true);
                }} catch (error) {{
                    setNotificationStatus('timeout-slow-mode-status', '❌ ' + error.message, false);
                }} finally {{
                    if (saveButton) {{
                        saveButton.disabled = false;
                        saveButton.textContent = 'Save Timeout Settings';
                    }}
                }}
            }}

            async function saveFilecryptSettings() {{
                var saveButton = document.getElementById('filecryptSaveBtn');
                var checkbox = document.getElementById('filecrypt-enabled');
                setNotificationStatus('filecrypt-status', 'Saving filecrypt setting...', true);

                if (saveButton) {{
                    saveButton.disabled = true;
                    saveButton.textContent = 'Saving...';
                }}
                if (checkbox) {{
                    checkbox.disabled = true;
                }}

                try {{
                    var response = await quasarrApiFetch('/api/filecrypt/settings', {{
                        method: 'POST',
                        headers: {{ 'Content-Type': 'application/json' }},
                        body: JSON.stringify({{ enabled: !!(checkbox && checkbox.checked) }})
                    }});
                    var data = await response.json();
                    if (!response.ok || !data.success) {{
                        throw new Error(data.message || 'Failed to save filecrypt setting');
                    }}

                    if (checkbox) {{
                        checkbox.checked = !!data.enabled;
                    }}
                    setNotificationStatus('filecrypt-status', '✅ ' + data.message, true);
                }} catch (error) {{
                    setNotificationStatus('filecrypt-status', '❌ ' + error.message, false);
                }} finally {{
                    if (saveButton) {{
                        saveButton.disabled = false;
                        saveButton.textContent = 'Save Filecrypt Setting';
                    }}
                    if (checkbox) {{
                        checkbox.disabled = false;
                    }}
                }}
            }}

            bindTimeoutSlowModePreview();
        </script>
        """
        # Add logout link for form auth
        logout_html = '<a href="/logout">Logout</a>' if show_logout_link() else ""
        return render_centered_html(info, footer_content=logout_html)

    @app.get("/regenerate-api-key")
    def regenerate_api_key():
        shared_state.generate_api_key()
        return render_success("API Key replaced!", 5)

    Server(app, listen="0.0.0.0", port=shared_state.values["port"]).serve_forever()
