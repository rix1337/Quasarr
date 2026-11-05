# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

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
)
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


def hostnames_config(shared_state):
    app = Bottle()
    add_no_cache_headers(app)
    setup_auth(app)

    from quasarr.storage.setup.custom_sources import setup_custom_source_pages
    from quasarr.storage.setup.sites import setup_site_routes, sites_page

    @app.get("/")
    def sites_form():
        return sites_page(shared_state, onboarding=True)

    setup_site_routes(app, shared_state, onboarding=True)
    from quasarr.api.config.custom_sources import setup_custom_source_routes

    setup_custom_source_routes(app, shared_state)
    setup_custom_source_pages(app, onboarding=True)

    @app.post("/api/hostnames/import-url")
    def import_hostnames_route():
        return import_hostnames_from_url()

    @app.post("/api/hostnames/check-credentials/<shorthand>")
    def check_credentials_route(shorthand):
        return check_credentials(shared_state, shorthand)

    info(
        f'No sites added yet. Add one at: "{shared_state.values["external_address"]}".'
    )
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
