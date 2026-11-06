# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import os
import sys

from bottle import Bottle, request

import quasarr.providers.web_server
from quasarr.providers.html_templates import render_button, render_form
from quasarr.providers.log import info
from quasarr.providers.web_server import Server
from quasarr.storage.setup.common import (
    add_no_cache_headers,
    render_reconnect_success,
    setup_auth,
)


def path_config(shared_state):
    app = Bottle()
    add_no_cache_headers(app)
    setup_auth(app)

    current_path = os.path.dirname(os.path.abspath(sys.argv[0]))

    @app.get("/")
    def config_form():
        config_form_html = f'''
            <form action="/api/config" method="post" onsubmit="return handleSubmit(this)">
                <label for="config_path">Path</label>
                <input type="text" id="config_path" autocapitalize="off" autocorrect="off" spellcheck="false" name="config_path" placeholder="{current_path}"><br>
                {render_button("Save", "primary", {"type": "submit", "id": "submitBtn"})}
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
            '''
        return render_form(
            "Press 'Save' to set desired path for configuration", config_form_html
        )

    def set_config_path(config_path):
        config_path_file = "Quasarr.conf"

        if not config_path:
            config_path = current_path

        config_path = config_path.replace("\\", "/")
        config_path = config_path[:-1] if config_path.endswith("/") else config_path

        if not os.path.exists(config_path):
            os.makedirs(config_path)

        with open(config_path_file, "w") as f:
            f.write(config_path)

        return config_path

    @app.post("/api/config")
    def set_config():
        config_path = request.forms.get("config_path")
        config_path = set_config_path(config_path)
        quasarr.providers.web_server.temp_server_success = True
        return render_reconnect_success(f'Config path set to: "{config_path}"')

    info(
        f'Starting web server for config at: "{shared_state.values["external_address"]}".'
    )
    info("Please set desired config path there!")
    quasarr.providers.web_server.temp_server_success = False
    return Server(
        app, listen="0.0.0.0", port=shared_state.values["port"]
    ).serve_temporarily()
