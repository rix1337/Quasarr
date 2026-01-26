# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

from bottle import Bottle

import quasarr.providers.html_images as images
from quasarr.api.arr import setup_arr_routes
from quasarr.api.captcha import setup_captcha_routes
from quasarr.api.config import setup_config
from quasarr.api.packages import setup_packages_routes
from quasarr.api.sponsors_helper import setup_sponsors_helper_routes
from quasarr.api.statistics import setup_statistics
from quasarr.providers import shared_state
from quasarr.providers.auth import add_auth_hook, add_auth_routes, show_logout_link
from quasarr.providers.hostname_issues import get_all_hostname_issues
from quasarr.providers.html_templates import (
    render_button,
    render_centered_html,
    render_success,
)
from quasarr.providers.web_server import Server
from quasarr.storage.config import Config
from quasarr.storage.sqlite_database import DataBase


def get_api(shared_state_dict, shared_state_lock):
    shared_state.set_state(shared_state_dict, shared_state_lock)

    app = Bottle()

    # Auth: routes must come first, then hook
    add_auth_routes(app)
    add_auth_hook(
        app,
        whitelist_prefixes=["/api", "/api/", "/sponsors_helper/", "/download/"],
        whitelist_suffixes=[".user.js"],
    )

    setup_arr_routes(app)
    setup_captcha_routes(app)
    setup_config(app, shared_state)
    setup_statistics(app, shared_state)
    setup_sponsors_helper_routes(app)
    setup_packages_routes(app)

    @app.get("/")
    def index():
        protected = shared_state.get_db("protected").retrieve_all_titles()
        api_key = Config("API").get("key")

        # Get quick status summary
        try:
            device = shared_state.values.get("device")
            jd_connected = device is not None and device is not False
        except:
            jd_connected = False

        # Calculate hostname status
        hostnames_config = Config("Hostnames")
        skip_login_db = DataBase("skip_login")
        hostname_issues = get_all_hostname_issues()
        login_required_sites = ["al", "dd", "dl", "nx"]

        working_count = 0
        total_count = 0

        for site_key in shared_state.values["sites"]:
            shorthand = site_key.lower()
            current_value = hostnames_config.get(shorthand)

            # Skip unset hostnames and skipped logins
            if not current_value:
                continue
            if shorthand in login_required_sites:
                skip_val = skip_login_db.retrieve(shorthand)
                if skip_val and str(skip_val).lower() == "true":
                    continue

            # This hostname counts toward total
            total_count += 1

            # Check if it's working (no issues)
            if shorthand not in hostname_issues:
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
                <span class="status-pill {"success" if jd_connected else "error"}">
                    {"✅" if jd_connected else "❌"} JDownloader {"connected" if jd_connected else "disconnected"}
                </span>
                <span class="status-pill {hostname_status_class}">
                    {hostname_status_emoji} {hostname_status_text}
                </span>
            </div>
        """

        info = f"""
        <h1><img src="{images.logo}" type="image/png" alt="Quasarr logo" class="logo"/>Quasarr</h1>

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
            <a href="/flaresolverr" class="action-card">
                <span class="action-icon">🛡️</span>
                <span class="action-label">FlareSolverr</span>
            </a>
        </div>

        <div class="section">
            <details id="apiDetails">
                <summary id="apiSummary">⚙️ API Configuration</summary>
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
            #copyUrl, #copyKey {{
                background: var(--btn-primary-bg, #007bff);
                color: white;
            }}
            #copyUrl:hover, #copyKey:hover {{
                background: var(--btn-primary-hover, #0056b3);
            }}
            #toggleKey {{
                background: var(--btn-secondary-bg, #6c757d);
                color: white;
            }}
            #toggleKey:hover {{
                background: var(--btn-secondary-hover, #545b62);
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
                    --status-success-bg: #1b5e20;
                    --status-success-color: #a5d6a7;
                    --status-success-border: #2e7d32;
                    --status-warning-bg: #3d3520;
                    --status-warning-color: #ffb74d;
                    --status-warning-border: #d69e2e;
                    --status-error-bg: #b71c1c;
                    --status-error-color: #ef9a9a;
                    --status-error-border: #c62828;
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
        </script>
        """
        # Add logout link for form auth
        logout_html = '<a href="/logout">Logout</a>' if show_logout_link() else ""
        return render_centered_html(info, footer_content=logout_html)

    @app.get("/regenerate-api-key")
    def regenerate_api_key():
        shared_state.generate_api_key()
        return render_success(f"API Key replaced!", 5)

    Server(app, listen="0.0.0.0", port=shared_state.values["port"]).serve_forever()
