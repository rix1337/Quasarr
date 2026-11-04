# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

from bottle import Bottle, request, response

import quasarr.providers.web_server
from quasarr.providers.html_templates import render_button, render_form
from quasarr.providers.log import debug, info
from quasarr.providers.radarr_api import (
    RadarrAPIClient,
    get_client,
    get_tmdb_id,
    set_client,
)
from quasarr.providers.web_server import Server
from quasarr.storage.config import Config
from quasarr.storage.setup.common import (
    add_no_cache_headers,
    render_reconnect_success,
    setup_auth,
)
from quasarr.storage.sqlite_database import DataBase

SKIP_RADARR_TABLE = "skip_radarr"
VERIFICATION_IMDB_ID = "tt0019422"
VERIFICATION_TMDB_ID = 53565


def _build_client(url, api_key):
    if not url or not api_key:
        return None
    try:
        return RadarrAPIClient(url, api_key)
    except ValueError as e:
        debug(f"Radarr client not built: {e}")
        return None


def refresh_radarr_client(shared_state):
    """Build (or rebuild) the cached Radarr client from current config."""
    config = Config("Radarr")
    url = config.get("url") or ""
    api_key = config.get("api_key") or ""
    client = _build_client(url, api_key)
    set_client(shared_state, client)
    return client


def initialize_radarr_client(shared_state):
    return refresh_radarr_client(shared_state)


def is_radarr_configured(shared_state):
    return bool(get_client(shared_state))


def is_radarr_skipped():
    return bool(DataBase(SKIP_RADARR_TABLE).retrieve("skipped"))


def get_radarr_settings_data(shared_state):
    response.content_type = "application/json"
    config = Config("Radarr")
    url = config.get("url") or ""
    api_key = config.get("api_key") or ""
    return {
        "success": True,
        "settings": {
            "url": url,
            "api_key": api_key,
            "configured": is_radarr_configured(shared_state),
            "skipped": is_radarr_skipped(),
        },
    }


def _normalize_inputs(url, api_key):
    """Validate input shape and return (url, api_key, error)."""
    url = (url or "").strip().rstrip("/")
    api_key = (api_key or "").strip()

    if url and not (url.startswith("http://") or url.startswith("https://")):
        return None, None, "Radarr URL must start with http:// or https://"

    if (url and not api_key) or (api_key and not url):
        return None, None, "Radarr URL and API key must both be set, or both empty."

    return url, api_key, None


def _configured_required_sites(shared_state):
    from quasarr.providers.sonarr_api import get_client as get_sonarr_client
    from quasarr.search.sources.helpers import (
        get_radarr_required_hostnames,
        get_sonarr_required_hostnames,
    )

    hostnames = Config("Hostnames")
    radarr_sites = {
        site for site in get_radarr_required_hostnames() if hostnames.get(site)
    }
    sonarr_sites = {
        site for site in get_sonarr_required_hostnames() if hostnames.get(site)
    }
    if get_sonarr_client(shared_state):
        return radarr_sites - sonarr_sites
    return radarr_sites


def _verify_credentials(shared_state, url, api_key):
    """Hit Radarr with a known IMDb ID. Returns (ok, error_message).

    Temporarily installs the freshly built client in ``shared_state`` so
    verification flows through ``get_tmdb_id`` like real lookups do. The
    previous cached client is restored on failure; on success the caller is
    expected to call ``refresh_radarr_client`` next.
    """
    try:
        client = RadarrAPIClient(url, api_key)
    except ValueError as e:
        return False, str(e)

    previous_client = get_client(shared_state)
    set_client(shared_state, client)

    tmdb_id = get_tmdb_id(shared_state, VERIFICATION_IMDB_ID)

    if not tmdb_id:
        set_client(shared_state, previous_client)
        return False, (
            "Radarr connection failed. Verify the URL & API key, and that Radarr is reachable."
        )

    if tmdb_id != VERIFICATION_TMDB_ID:
        debug(tmdb_id)
        set_client(shared_state, previous_client)
        return False, ("Radarr connection failed. Radarr returned bogus data.")

    return True, None


def _persist(url, api_key):
    config = Config("Radarr")
    config.save("url", url)
    config.save("api_key", api_key)
    if url and api_key:
        DataBase(SKIP_RADARR_TABLE).delete("skipped")


def save_radarr_settings(shared_state):
    response.content_type = "application/json"

    data = request.json
    if not isinstance(data, dict):
        response.status = 400
        return {
            "success": False,
            "message": "Request body must be a JSON object.",
        }
    url, api_key, err = _normalize_inputs(
        str(data.get("url", "")), str(data.get("api_key", ""))
    )
    if err:
        return {"success": False, "message": err}

    if not url and _configured_required_sites(shared_state):
        response.status = 400
        return {
            "success": False,
            "message": "Radarr is required while movie sources are configured.",
        }

    if url and api_key:
        ok, verify_err = _verify_credentials(shared_state, url, api_key)
        if not ok:
            return {"success": False, "message": verify_err}

    _persist(url, api_key)
    client = refresh_radarr_client(shared_state)

    if url and api_key:
        info(f'Radarr settings saved: "{url}"')
    else:
        info("Radarr settings cleared")

    return {
        "success": True,
        "message": "Radarr settings saved",
        "configured": bool(client),
    }


def delete_skip_radarr_preference():
    """Clear skip Radarr preference."""
    response.content_type = "application/json"
    DataBase(SKIP_RADARR_TABLE).delete("skipped")
    info("Skip Radarr preference cleared")
    return {"success": True}


def _radarr_setup_form_html(required_sites):
    config = Config("Radarr")
    current_url = config.get("url") or ""
    current_api_key = config.get("api_key") or ""
    site_list = ", ".join(sorted(s.upper() for s in required_sites))

    return f"""
    <p>One or more configured hostnames ({site_list}) require Radarr to look up
    movie metadata. Provide your Radarr URL and API key below.</p>

    <form action="/api/radarr/save" method="post" onsubmit="return handleSubmit(this)">
        <label for="url">Radarr URL</label>
        <input type="text" id="url" name="url" placeholder="http://192.168.0.1:7878" value="{current_url}" required><br>
        <label for="api_key">Radarr API Key</label>
        <input type="password" id="api_key" name="api_key" placeholder="Radarr API key" value="{current_api_key}" required><br>
        <div class="button-row">
            {render_button("Save", "primary", {"type": "submit", "id": "submitBtn"})}
        </div>
    </form>
    <script>
    var formSubmitted = false;
    function handleSubmit(form) {{
        if (formSubmitted) return false;
        formSubmitted = true;
        var btn = document.getElementById('submitBtn');
        if (btn) {{ btn.disabled = true; btn.textContent = 'Saving...'; }}
        return true;
    }}
    </script>
    <style>
        .button-row {{
            display: flex;
            gap: 0.75rem;
            justify-content: center;
            flex-wrap: wrap;
            margin-top: 1rem;
        }}
    </style>
    """


def _save_radarr_form(shared_state):
    """Handle form-encoded POST during the startup setup flow."""
    from quasarr.providers.html_templates import render_fail

    url = request.forms.get("url", "")
    api_key = request.forms.get("api_key", "")
    url, api_key, err = _normalize_inputs(url, api_key)
    if err:
        return render_fail(err)

    if not url:
        return render_fail("Radarr URL and API key are required.")

    if url and api_key:
        ok, verify_err = _verify_credentials(shared_state, url, api_key)
        if not ok:
            return render_fail(verify_err)

    _persist(url, api_key)
    refresh_radarr_client(shared_state)
    info(f'Radarr settings saved: "{url}"' if url else "Radarr settings cleared")

    quasarr.providers.web_server.temp_server_success = True
    return render_reconnect_success("Radarr settings saved successfully!")


def radarr_config(shared_state, required_sites):
    """Temporary web server prompting the user to configure Radarr."""
    app = Bottle()
    add_no_cache_headers(app)
    setup_auth(app)

    @app.get("/")
    def radarr_form():
        return render_form(
            "Set Radarr URL and API Key",
            _radarr_setup_form_html(required_sites),
        )

    @app.post("/api/radarr/save")
    def save_radarr_form_route():
        return _save_radarr_form(shared_state)

    site_list = ", ".join(sorted(s.upper() for s in required_sites))
    info(
        f'Radarr configuration required for: "{site_list}". '
        f'Starting web server for config at: "{shared_state.values["external_address"]}".'
    )
    info("Please enter your Radarr URL and API key now to allow Quasarr to launch!")
    quasarr.providers.web_server.temp_server_success = False
    return Server(
        app, listen="0.0.0.0", port=shared_state.values["port"]
    ).serve_temporarily()
