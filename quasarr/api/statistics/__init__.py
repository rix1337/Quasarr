# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import os

from bottle import redirect

import quasarr.providers.html_images as images
from quasarr.api.statistics.chart import render_history_charts
from quasarr.providers.error_report import read_site_errors, site_error_issue_url
from quasarr.providers.html_templates import render_button, render_centered_html
from quasarr.providers.statistics import StatsHelper
from quasarr.providers.version import get_version


def setup_statistics(app, shared_state):
    @app.get("/statistics")
    def statistics():
        history = StatsHelper(shared_state).get_history()
        report_button = ""
        if read_site_errors(os.path.dirname(shared_state.values["configfile"])):
            report_button = render_button(
                "Report site errors",
                "secondary",
                {"onclick": "window.open('/statistics/report-site-errors', '_blank')"},
            )

        stats_html = f"""
        <h1><img src="{images.logo}" type="image/webp" alt="Quasarr logo" class="logo"/>Quasarr</h1>
        <h2>Statistics</h2>
        <div class="stats-container">
            {render_history_charts(history)}
        </div>

        <p>
            {render_button("Back", "secondary", {"onclick": "location.href='/'"})}
            {report_button}
        </p>

        <style>
            .stats-container {{
                max-width: 1000px;
                margin: 0 auto;
            }}

            .stats-container h3 {{
                margin: 25px 0 15px 0;
            }}
        </style>
        """

        return render_centered_html(stats_html)

    @app.get("/statistics/report-site-errors")
    def report_site_errors():
        configfile = shared_state.values["configfile"]
        url = site_error_issue_url(
            os.path.dirname(configfile),
            _configured_hostnames(shared_state),
            configfile,
        )
        if url:
            redirect(url)
        return render_centered_html(
            f"""
        <h1><img src="{images.logo}" type="image/webp" alt="Quasarr logo" class="logo"/>Quasarr</h1>
        <p>No site errors logged by v{get_version()}.</p>
        <p>{render_button("Back", "secondary", {"onclick": "location.href='/statistics'"})}</p>
        """
        )


def _configured_hostnames(shared_state):
    from quasarr.search.sources.helpers import get_hostnames
    from quasarr.storage.custom_sources import get_custom_sources

    config = shared_state.values["config"]("Hostnames")
    hostnames = {key: config.get(key) for key in get_hostnames()}
    hostnames.update(
        {key: source.hostname for key, source in get_custom_sources().items()}
    )
    return {key: host for key, host in hostnames.items() if host}
