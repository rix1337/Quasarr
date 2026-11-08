# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

from bottle import Bottle, request

import quasarr.providers.web_server
from quasarr.providers.html_templates import render_fail, render_form
from quasarr.providers.log import warn
from quasarr.providers.web_server import Server
from quasarr.storage.setup.common import (
    add_no_cache_headers,
    render_reconnect_success,
    setup_auth,
)


def split_arr_required_sites(radarr_required_sites, sonarr_required_sites):
    """Split configured hostnames into movie-only, TV-only, and dual-category sets."""
    radarr_sites = set(radarr_required_sites)
    sonarr_sites = set(sonarr_required_sites)
    return (
        radarr_sites - sonarr_sites,
        sonarr_sites - radarr_sites,
        radarr_sites & sonarr_sites,
    )


def missing_arr_client_requirement(
    site, radarr_required, sonarr_required, radarr_ok, sonarr_ok
):
    """Return missing client label, allowing either client for dual-category sites."""
    requires_radarr = site in radarr_required
    requires_sonarr = site in sonarr_required
    if requires_radarr and requires_sonarr:
        return None if radarr_ok or sonarr_ok else "Radarr or Sonarr"
    if requires_radarr and not radarr_ok:
        return "Radarr"
    if requires_sonarr and not sonarr_ok:
        return "Sonarr"
    return None


def _arr_client_selection_form_html(radarr_required_sites, sonarr_required_sites):
    radarr_sites = ", ".join(sorted(site.upper() for site in radarr_required_sites))
    sonarr_sites = ", ".join(sorted(site.upper() for site in sonarr_required_sites))
    return f"""
    <p>Your sites support both movie and TV searches. Quasarr needs one
    *arr client to launch, but does not require both.</p>
    <p>Choose the client you use. You can configure the other later in Settings.</p>
    <form action="/api/arr/client" method="post">
        <p><button type="submit" name="client" value="radarr">Use Radarr</button>
        <small>Required by: {radarr_sites}</small></p>
        <p><button type="submit" name="client" value="sonarr">Use Sonarr</button>
        <small>Required by: {sonarr_sites}</small></p>
    </form>
    """


def select_arr_client_config(
    shared_state, radarr_required_sites, sonarr_required_sites
):
    """Ask which *arr client to configure when configured hostnames support both."""
    app = Bottle()
    add_no_cache_headers(app)
    setup_auth(app)
    selected_client = None

    @app.get("/")
    def arr_client_form():
        return render_form(
            "Choose your *arr client",
            _arr_client_selection_form_html(
                radarr_required_sites, sonarr_required_sites
            ),
        )

    @app.post("/api/arr/client")
    def save_arr_client_choice():
        nonlocal selected_client
        selected_client = request.forms.get("client")
        if selected_client not in {"radarr", "sonarr"}:
            return render_fail("Choose Radarr or Sonarr.")
        quasarr.providers.web_server.temp_server_success = True
        return render_reconnect_success(
            f"{selected_client.title()} selected. Continue setup in the next screen."
        )

    warn(
        "Your sites support both movie and TV searches. "
        "Choose Radarr or Sonarr; the other client remains optional."
    )
    quasarr.providers.web_server.temp_server_success = False
    if Server(
        app, listen="0.0.0.0", port=shared_state.values["port"]
    ).serve_temporarily():
        return selected_client
    return None
