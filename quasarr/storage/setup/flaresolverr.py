# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import re

from bottle import Bottle, request, response

import quasarr.providers.web_server
from quasarr.constants import FALLBACK_USER_AGENT
from quasarr.providers.html_templates import (
    render_button,
    render_fail,
    render_form,
)
from quasarr.providers.log import info
from quasarr.providers.utils import check_flaresolverr
from quasarr.providers.web_server import Server
from quasarr.storage.config import Config
from quasarr.storage.setup.common import (
    add_no_cache_headers,
    render_reconnect_success,
    setup_auth,
)
from quasarr.storage.sqlite_database import DataBase


def save_flaresolverr_url(shared_state, is_setup=False):
    """Save flaresolverr-next URL from web UI."""
    url = request.forms.get("url", "").strip()
    config = Config("FlareSolverr")

    if not url:
        config.save("url", "")
        DataBase("skip_flaresolverr").update_store("skipped", "true")
        shared_state.update("user_agent", FALLBACK_USER_AGENT)
        info("flaresolverr-next URL cleared and setup skipped")

        if is_setup:
            quasarr.providers.web_server.temp_server_success = True

        return render_reconnect_success("flaresolverr-next URL cleared.")

    if not url.startswith("http://") and not url.startswith("https://"):
        url = "http://" + url

    if not re.search(r"/v\d+$", url):
        return render_fail(
            "flaresolverr-next URL must end with /v1 (or similar version path)."
        )

    if check_flaresolverr(shared_state, url):
        config.save("url", url)
        DataBase("skip_flaresolverr").delete("skipped")

        info(
            f'flaresolverr-next connection successful. Using User-Agent: "{shared_state.values["user_agent"]}"'
        )
        info(f'flaresolverr-next URL configured: "{url}"')

        if is_setup:
            quasarr.providers.web_server.temp_server_success = True

        return render_reconnect_success("flaresolverr-next URL saved successfully!")
    return render_fail("Could not reach flaresolverr-next!")


def get_flaresolverr_status_data(shared_state):
    """Return flaresolverr-next configuration status."""
    response.content_type = "application/json"
    skip_db = DataBase("skip_flaresolverr")
    is_skipped = bool(skip_db.retrieve("skipped"))
    current_url = Config("FlareSolverr").get("url") or ""

    is_working = False
    if current_url and not is_skipped:
        is_working = check_flaresolverr(shared_state, current_url)

    return {"skipped": is_skipped, "url": current_url, "working": is_working}


def delete_skip_flaresolverr_preference():
    """Clear skip flaresolverr-next preference."""
    response.content_type = "application/json"
    DataBase("skip_flaresolverr").delete("skipped")
    info("Skip flaresolverr-next preference cleared")
    return {"success": True}


def flaresolverr_form_html(shared_state, is_setup=False):
    skip_db = DataBase("skip_flaresolverr")
    is_skipped = skip_db.retrieve("skipped")
    current_url = Config("FlareSolverr").get("url") or ""

    skip_indicator = ""
    if is_skipped and not is_setup:
        skip_indicator = """
        <div class="skip-indicator" style="margin-bottom:1rem; padding:0.75rem; background:var(--code-bg, #f8f9fa); border-radius:0.25rem; font-size:0.875rem;">
            <span style="color:#dc3545;">⚠️ flaresolverr-next setup was skipped</span>
            <p style="margin:0.5rem 0 0 0; font-size:0.75rem; color:var(--secondary, #6c757d);">
                Some sites (like AL) won't work until flaresolverr-next is configured.
            </p>
        </div>
        """

    form_content = f'''
    {skip_indicator}
    <span><a href="https://github.com/rix1337/flaresolverr-next" target="_blank">flaresolverr-next</a>
    must be running and reachable to Quasarr for some sites to work.</span><br><br>
    <label for="url">flaresolverr-next URL</label>
    <input type="text" id="url" name="url" autocapitalize="off" autocorrect="off" spellcheck="false" placeholder="http://192.168.0.1:8191/v1" value="{current_url}"><br>
    '''

    buttons = render_button("Save", "primary", {"type": "submit", "id": "submitBtn"})
    extra_js = ""

    if is_setup:
        buttons += ' <button type="button" class="btn-warning" id="skipBtn" onclick="skipFlaresolverr()">Skip for now</button>'
        extra_js = """
        function skipFlaresolverr() {
            if (formSubmitted) return;
            formSubmitted = true;
            var skipBtn = document.getElementById('skipBtn');
            var submitBtn = document.getElementById('submitBtn');
            if (skipBtn) { skipBtn.disabled = true; skipBtn.textContent = 'Skipping...'; }
            if (submitBtn) { submitBtn.disabled = true; }

            quasarrApiFetch('/api/flaresolverr/skip', { method: 'POST' })
            .then(response => {
                if (response.ok) {
                    window.location.href = '/skip-success';
                } else {
                    showModal('Error', 'Failed to skip flaresolverr-next setup');
                    formSubmitted = false;
                    if (skipBtn) { skipBtn.disabled = false; skipBtn.textContent = 'Skip for now'; }
                    if (submitBtn) { submitBtn.disabled = false; }
                }
            })
            .catch(error => {
                showModal('Error', 'Error: ' + error.message);
                formSubmitted = false;
                if (skipBtn) { skipBtn.disabled = false; skipBtn.textContent = 'Skip for now'; }
                if (submitBtn) { submitBtn.disabled = false; }
            });
        }
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
    <form action="/api/flaresolverr" method="post" onsubmit="return handleSubmit(this)">
        {form_content}
        <div class="button-row">
            {buttons}
        </div>
    </form>
    <script>
    var formSubmitted = false;
    function handleSubmit(form) {{
        if (formSubmitted) return false;
        formSubmitted = true;
        var btn = document.getElementById('submitBtn');
        if (btn) {{ btn.disabled = true; btn.textContent = 'Saving...'; }}
        var skipBtn = document.getElementById('skipBtn');
        if (skipBtn) {{ skipBtn.disabled = true; }}
        return true;
    }}
    {extra_js}
    </script>
    """

    if not is_setup:
        form_html += f"""<p>{render_button("Back", "secondary", {"onclick": "location.href='/'"})}</p>"""

    return form_html


def flaresolverr_config(shared_state):
    app = Bottle()
    add_no_cache_headers(app)
    setup_auth(app)

    @app.get("/")
    def url_form():
        return render_form(
            "Set flaresolverr-next URL",
            flaresolverr_form_html(shared_state, is_setup=True),
        )

    @app.get("/skip-success")
    def skip_success():
        return render_reconnect_success(
            "flaresolverr-next setup skipped. Some sites (like AL) won't work. You can configure it later in the web UI."
        )

    @app.post("/api/flaresolverr/skip")
    def skip_flaresolverr():
        DataBase("skip_flaresolverr").update_store("skipped", "true")
        shared_state.update("user_agent", FALLBACK_USER_AGENT)
        info("flaresolverr-next setup skipped by user choice")
        quasarr.providers.web_server.temp_server_success = True
        return {"success": True}

    @app.post("/api/flaresolverr")
    def set_flaresolverr_url_route():
        return save_flaresolverr_url(shared_state, is_setup=True)

    info(
        '"flaresolverr-next" URL is required for some sites (like AL). '
        f'Starting web server for config at: "{shared_state.values["external_address"]}".'
    )
    info(
        "Please enter your flaresolverr-next URL now, or skip to allow Quasarr to launch!"
    )
    quasarr.providers.web_server.temp_server_success = False
    return Server(
        app, listen="0.0.0.0", port=shared_state.values["port"]
    ).serve_temporarily()
