# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import quasarr.providers.html_images as images
from quasarr.api.statistics.chart import render_history_charts
from quasarr.providers.html_templates import render_button, render_centered_html
from quasarr.providers.statistics import StatsHelper


def setup_statistics(app, shared_state):
    @app.get("/statistics")
    def statistics():
        history = StatsHelper(shared_state).get_history()

        stats_html = f"""
        <h1><img src="{images.logo}" type="image/webp" alt="Quasarr logo" class="logo"/>Quasarr</h1>
        <h2>Statistics</h2>
        <div class="stats-container">
            {render_history_charts(history)}
        </div>

        <p>
            {render_button("Back", "secondary", {"onclick": "location.href='/'"})}
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
