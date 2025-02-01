# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

from bottle import Bottle

from quasarr.api.arr import setup_arr_routes
from quasarr.api.captcha import setup_captcha_routes
from quasarr.api.sponsors_helper import setup_sponsors_helper_routes
from quasarr.providers import shared_state
from quasarr.providers.html_templates import render_button, render_centered_html
from quasarr.providers.web_server import Server
from quasarr.storage.config import Config


def get_api(shared_state_dict, shared_state_lock):
    shared_state.set_state(shared_state_dict, shared_state_lock)

    app = Bottle()

    setup_arr_routes(app)
    setup_captcha_routes(app)
    setup_sponsors_helper_routes(app)

    @app.get('/')
    def index():
        protected = shared_state.get_db("protected").retrieve_all_titles()
        api_key = Config('API').get('key')

        captcha_hint = ""
        if protected:
            package_count = len(protected)
            package_text = f"Package{'s' if package_count > 1 else ''} protected by CAPTCHA"
            amount_info = f": {package_count}" if package_count > 1 else ""
            button_text = f"Solve CAPTCHA{'s' if package_count > 1 else ''} manually to decrypt links!"

            captcha_hint = f'''
            <h2>Protected links</h2>
            <p>{package_text}{amount_info}</p>
            <p>{render_button(button_text, "primary", {"onclick": "location.href='/captcha'"})}</p>
            <a href="https://github.com/users/rix1337/sponsorship" target="_blank">
                For automated CAPTCHA Solutions use SponsorsHelper!
            </a>
            '''

        small = 'small style="background-color: #f0f0f0; padding: 5px; border-radius: 3px;"'

        info = f"""
        <h1>Quasarr</h1>
        {captcha_hint}
        <h2>Setup Instructions</h2>
        <p>
            <h3>Radarr/Sonarr</h3>
            Use this exact URL as <{small}>Newznab Indexer</small> and <{small}>SABnzbd Download Client</small>:<br><br>
            <code style="background-color: #f0f0f0; padding: 5px; border-radius: 3px;">
                {shared_state.values["internal_address"]}
            </code>
        </p>
        <p>
            Leave settings at default and use this API key:<br><br>
            <{small}>{api_key}</small>
        </p>
        <p>
            {render_button("Regenerate API key",
                           "secondary",
                           {"onclick": "if(confirm('Are you sure you want to regenerate the API key?')) { location.href='/regenerate-api-key'; }"})}
        </p>
        <p>Some JDownloader settings will be enforced by Quasarr on startup.</p>
        """
        return render_centered_html(info)

    @app.get('/regenerate-api-key')
    def regenerate_api_key():
        api_key = shared_state.generate_api_key()
        return f"""
        <script>
            alert('API key replaced with: "{api_key}!"');
            window.location.href = '/';
        </script>
        """

    Server(app, listen='0.0.0.0', port=shared_state.values["port"]).serve_forever()
