# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import os
import re
import signal
import threading
import time
from urllib.parse import urlparse

import requests
from bottle import request, response

from quasarr.providers.html_templates import render_button, render_fail, render_form
from quasarr.providers.log import info
from quasarr.providers.shared_state import extract_valid_hostname
from quasarr.providers.utils import (
    check_flaresolverr,
    extract_allowed_keys,
    extract_kv_pairs,
)
from quasarr.storage.config import Config
from quasarr.storage.setup import (
    hostname_form_html,
    render_reconnect_success,
    save_hostnames,
)
from quasarr.storage.sqlite_database import DataBase


def setup_config(app, shared_state):
    @app.get("/api/hostname-issues")
    def get_hostname_issues_api():
        response.content_type = "application/json"
        from quasarr.providers.hostname_issues import get_all_hostname_issues

        return {"issues": get_all_hostname_issues()}

    @app.get("/hostnames")
    def hostnames_ui():
        message = """<p>
            At least one hostname must be kept.
        </p>"""
        back_button = f"""<p>
                        {render_button("Back", "secondary", {"onclick": "location.href='/'"})}
                    </p>"""
        return render_form(
            "Hostnames",
            hostname_form_html(
                shared_state,
                message,
                show_restart_button=True,
                show_skip_management=True,
            )
            + back_button,
        )

    @app.post("/api/hostnames")
    def hostnames_api():
        return save_hostnames(shared_state, timeout=1, first_run=False)

    @app.post("/api/hostnames/import-url")
    def import_hostnames_from_url():
        """Fetch URL and parse hostnames, return JSON for JS to populate fields."""
        response.content_type = "application/json"
        try:
            data = request.json
            url = data.get("url", "").strip()

            if not url:
                return {"success": False, "error": "No URL provided"}

            # Validate URL
            parsed = urlparse(url)
            if parsed.scheme not in ("http", "https") or not parsed.netloc:
                return {"success": False, "error": "Invalid URL format"}

            # Fetch content
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

            # Parse hostnames
            allowed_keys = extract_allowed_keys(Config._DEFAULT_CONFIG, "Hostnames")
            results = extract_kv_pairs(content, allowed_keys)

            if not results:
                return {
                    "success": False,
                    "error": "No hostnames found in the provided URL",
                }

            # Validate each hostname
            valid_hostnames = {}
            invalid_hostnames = {}
            for shorthand, hostname in results.items():
                domain_check = extract_valid_hostname(hostname, shorthand)
                domain = domain_check.get("domain")
                if domain:
                    valid_hostnames[shorthand] = domain
                else:
                    invalid_hostnames[shorthand] = domain_check.get(
                        "message", "Invalid"
                    )

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

    @app.get("/api/skip-login")
    def get_skip_login():
        """Return list of hostnames with skipped login."""
        response.content_type = "application/json"
        skip_db = DataBase("skip_login")
        login_required_sites = ["al", "dd", "dl", "nx"]
        skipped = []
        for site in login_required_sites:
            if skip_db.retrieve(site):
                skipped.append(site)
        return {"skipped": skipped}

    @app.delete("/api/skip-login/<shorthand>")
    def clear_skip_login(shorthand):
        """Clear skip login preference for a hostname."""
        response.content_type = "application/json"
        shorthand = shorthand.lower()
        login_required_sites = ["al", "dd", "dl", "nx"]
        if shorthand not in login_required_sites:
            return {"success": False, "error": f"Invalid shorthand: {shorthand}"}

        skip_db = DataBase("skip_login")
        skip_db.delete(shorthand)
        info(f'Skip login preference cleared for "{shorthand.upper()}"')
        return {"success": True}

    @app.get("/flaresolverr")
    def flaresolverr_ui():
        """Web UI page for configuring FlareSolverr."""
        skip_db = DataBase("skip_flaresolverr")
        is_skipped = skip_db.retrieve("skipped")
        current_url = Config("FlareSolverr").get("url") or ""

        skip_indicator = ""
        if is_skipped:
            skip_indicator = """
            <div class="skip-indicator" style="margin-bottom:1rem; padding:0.75rem; background:var(--code-bg, #f8f9fa); border-radius:0.25rem; font-size:0.875rem;">
                <span style="color:#dc3545;">⚠️ FlareSolverr setup was skipped</span>
                <p style="margin:0.5rem 0 0 0; font-size:0.75rem; color:var(--secondary, #6c757d);">
                    Some sites (like AL) won't work until FlareSolverr is configured.
                </p>
            </div>
            """

        form_content = f'''
        {skip_indicator}
        <span><a href="https://github.com/FlareSolverr/FlareSolverr?tab=readme-ov-file#installation" target="_blank">FlareSolverr</a>
        must be running and reachable to Quasarr for some sites to work.</span><br><br>
        <label for="url">FlareSolverr URL</label>
        <input type="text" id="url" name="url" placeholder="http://192.168.0.1:8191/v1" value="{current_url}"><br>
        '''

        form_html = f"""
        <form action="/api/flaresolverr" method="post" onsubmit="return handleSubmit(this)">
            {form_content}
            {render_button("Save", "primary", {"type": "submit", "id": "submitBtn"})}
        </form>
        <p style="font-size:0.875rem; color:var(--secondary, #6c757d); margin-top:1rem;">
            A restart is recommended after configuring FlareSolverr.
        </p>
        <div class="section-divider" style="margin-top:1.5rem; padding-top:1rem; border-top:1px solid var(--divider-color, #dee2e6);">
            {render_button("Restart Quasarr", "secondary", {"type": "button", "onclick": "confirmRestart()"})}
        </div>
        <p>{render_button("Back", "secondary", {"onclick": "location.href='/';"})}</p>
        <script>
        var formSubmitted = false;
        function handleSubmit(form) {{
            if (formSubmitted) return false;
            formSubmitted = true;
            var btn = document.getElementById('submitBtn');
            if (btn) {{ btn.disabled = true; btn.textContent = 'Saving...'; }}
            return true;
        }}
        function confirmRestart() {{
            showModal('Restart Quasarr?', 'Are you sure you want to restart Quasarr now?', 
                `<button class="btn-secondary" onclick="closeModal()">Cancel</button>
                 <button class="btn-primary" onclick="performRestart()">Restart</button>`
            );
        }}
        function performRestart() {{
            closeModal();
            fetch('/api/restart', {{ method: 'POST' }})
            .then(response => response.json())
            .then(data => {{
                if (data.success) {{
                    showRestartOverlay();
                }}
            }})
            .catch(error => {{
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
        """
        return render_form("FlareSolverr", form_html)

    @app.post("/api/flaresolverr")
    def set_flaresolverr_url():
        """Save FlareSolverr URL from web UI."""
        url = request.forms.get("url", "").strip()
        config = Config("FlareSolverr")

        if not url:
            return render_fail("Please provide a FlareSolverr URL.")

        if not url.startswith("http://") and not url.startswith("https://"):
            url = "http://" + url

        # Validate URL format
        if not re.search(r"/v\d+$", url):
            return render_fail(
                "FlareSolverr URL must end with /v1 (or similar version path)."
            )

        try:
            headers = {"Content-Type": "application/json"}
            data = {
                "cmd": "request.get",
                "url": "http://www.google.com/",
                "maxTimeout": 30000,
            }
            resp = requests.post(url, headers=headers, json=data, timeout=30)
            if resp.status_code == 200:
                json_data = resp.json()
                if json_data.get("status") == "ok":
                    config.save("url", url)
                    # Clear skip preference since we now have a working URL
                    DataBase("skip_flaresolverr").delete("skipped")
                    # Update user agent from FlareSolverr response
                    solution = json_data.get("solution", {})
                    solution_ua = solution.get("userAgent")
                    if solution_ua:
                        shared_state.update("user_agent", solution_ua)
                    info(f'FlareSolverr URL configured: "{url}"')
                    return render_reconnect_success(
                        "FlareSolverr URL saved successfully! A restart is recommended."
                    )
                else:
                    return render_fail(
                        f"FlareSolverr returned unexpected status: {json_data.get('status')}"
                    )
        except requests.RequestException:
            return render_fail(f"Could not reach FlareSolverr!")

        return render_fail(
            "Could not reach FlareSolverr at that URL (expected HTTP 200)."
        )

    @app.get("/api/flaresolverr/status")
    def get_flaresolverr_status():
        """Return FlareSolverr configuration status."""
        response.content_type = "application/json"
        skip_db = DataBase("skip_flaresolverr")
        is_skipped = bool(skip_db.retrieve("skipped"))
        current_url = Config("FlareSolverr").get("url") or ""

        # Test connection if URL is set
        is_working = False
        if current_url and not is_skipped:
            is_working = check_flaresolverr(shared_state, current_url)

        return {"skipped": is_skipped, "url": current_url, "working": is_working}

    @app.delete("/api/skip-flaresolverr")
    def clear_skip_flaresolverr():
        """Clear skip FlareSolverr preference."""
        response.content_type = "application/json"
        skip_db = DataBase("skip_flaresolverr")
        skip_db.delete("skipped")
        info("Skip FlareSolverr preference cleared")
        return {"success": True}

    @app.post("/api/restart")
    def restart_quasarr():
        """Restart Quasarr. In Docker with the restart loop, exit(0) triggers restart."""
        response.content_type = "application/json"
        info("Restart requested via web UI")

        def delayed_exit():
            time.sleep(0.5)
            # Send SIGINT to main process - triggers KeyboardInterrupt handler
            os.kill(os.getpid(), signal.SIGINT)

        threading.Thread(target=delayed_exit, daemon=True).start()
        return {"success": True, "message": "Restarting..."}
