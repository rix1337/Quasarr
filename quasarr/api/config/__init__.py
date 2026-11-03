# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import json
import os
import signal
import threading
import time

from bottle import request, response

from quasarr.constants import (
    DOWNLOAD_CATEGORIES,
    RECOMMENDED_HOSTERS,
    SHARE_HOSTERS,
)
from quasarr.providers.auth import require_api_key
from quasarr.providers.html_templates import render_button, render_form
from quasarr.providers.log import info
from quasarr.providers.utils import (
    get_search_capability_category,
    has_source_capability_for_category,
)
from quasarr.search.sources import get_sources
from quasarr.search.sources.helpers import get_hostnames
from quasarr.storage.categories import (
    add_custom_search_category,
    add_download_category,
    delete_download_category,
    delete_search_category,
    get_download_categories,
    get_download_category_mirrors,
    get_search_categories,
    get_search_category_sources,
    get_search_category_ui_heading,
    get_search_category_whitelist_owner,
    update_download_category_mirrors,
    update_search_category_sources,
)
from quasarr.storage.setup import (
    check_credentials,
    clear_skip_login,
    delete_skip_flaresolverr_preference,
    get_crypter_settings_data,
    get_flaresolverr_status_data,
    get_notification_settings_data,
    get_radarr_settings_data,
    get_skip_login,
    get_sonarr_settings_data,
    get_timeout_slow_mode_settings_data,
    hostname_form_html,
    import_hostnames_from_url,
    save_crypter_settings,
    save_flaresolverr_url,
    save_hostnames,
    save_jdownloader_settings,
    save_notification_settings,
    save_radarr_settings,
    save_sonarr_settings,
    save_timeout_slow_mode_settings,
    send_notification_test,
    verify_jdownloader_credentials,
)


def setup_config(app, shared_state):
    @app.get("/api/hostname-issues")
    @require_api_key
    def get_hostname_issues_api():
        response.content_type = "application/json"
        from quasarr.providers.hostname_issues import get_all_hostname_issues

        return {"issues": get_all_hostname_issues()}

    @app.get("/hostnames")
    def hostnames_ui():
        message = """<p>
            Use status buttons to change credentials and check for errors.
        </p>"""
        back_button = f"""<p>
                        {render_button("Back", "secondary", {"onclick": "location.href='/'"})}
                    </p>"""
        return render_form(
            "Hostnames",
            hostname_form_html(
                shared_state,
                message,
                show_skip_management=True,
            )
            + back_button,
        )

    @app.post("/api/hostnames")
    @require_api_key
    def hostnames_api():
        return save_hostnames(shared_state, timeout=1, first_run=False)

    @app.post("/api/hostnames/check-credentials/<shorthand>")
    @require_api_key
    def check_credentials_api(shorthand):
        return check_credentials(shared_state, shorthand)

    @app.post("/api/hostnames/import-url")
    @require_api_key
    def import_hostnames_route():
        return import_hostnames_from_url()

    @app.get("/api/skip-login")
    @require_api_key
    def get_skip_login_route():
        return get_skip_login()

    @app.delete("/api/skip-login/<shorthand>")
    @require_api_key
    def clear_skip_login_route(shorthand):
        return clear_skip_login(shorthand)

    @app.post("/api/flaresolverr")
    @require_api_key
    def set_flaresolverr_url():
        """Save FlareSolverr URL from web UI."""
        return save_flaresolverr_url(shared_state)

    @app.get("/api/flaresolverr/status")
    @require_api_key
    def get_flaresolverr_status():
        """Return FlareSolverr configuration status."""
        return get_flaresolverr_status_data(shared_state)

    @app.delete("/api/skip-flaresolverr")
    @require_api_key
    def clear_skip_flaresolverr():
        """Clear skip FlareSolverr preference."""
        return delete_skip_flaresolverr_preference()

    @app.post("/api/restart")
    @require_api_key
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

    @app.post("/api/jdownloader/verify")
    @require_api_key
    def verify_jdownloader_api():
        return verify_jdownloader_credentials(shared_state)

    @app.post("/api/jdownloader/save")
    @require_api_key
    def save_jdownloader_api():
        return save_jdownloader_settings(shared_state, is_setup=False)

    @app.get("/api/notifications/settings")
    @require_api_key
    def get_notification_settings_api():
        return get_notification_settings_data(shared_state)

    @app.post("/api/notifications/settings")
    @require_api_key
    def save_notification_settings_api():
        return save_notification_settings(shared_state)

    @app.post("/api/notifications/test")
    @require_api_key
    def send_notification_test_api():
        return send_notification_test(shared_state)

    @app.get("/api/radarr/settings")
    @require_api_key
    def get_radarr_settings_api():
        return get_radarr_settings_data(shared_state)

    @app.post("/api/radarr/settings")
    @require_api_key
    def save_radarr_settings_api():
        return save_radarr_settings(shared_state)

    @app.get("/api/sonarr/settings")
    @require_api_key
    def get_sonarr_settings_api():
        return get_sonarr_settings_data(shared_state)

    @app.post("/api/sonarr/settings")
    @require_api_key
    def save_sonarr_settings_api():
        return save_sonarr_settings(shared_state)

    @app.get("/api/timeouts/settings")
    @require_api_key
    def get_timeout_slow_mode_settings_api():
        return get_timeout_slow_mode_settings_data(shared_state)

    @app.post("/api/timeouts/settings")
    @require_api_key
    def save_timeout_slow_mode_settings_api():
        return save_timeout_slow_mode_settings(shared_state)

    @app.get("/api/crypters/settings")
    @require_api_key
    def get_crypter_settings_api():
        return get_crypter_settings_data(shared_state)

    @app.post("/api/crypters/settings")
    @require_api_key
    def save_crypter_settings_api():
        return save_crypter_settings(shared_state)

    @app.get("/categories")
    def categories_ui():
        """Web UI page for managing categories."""
        response.set_header("Cache-Control", "no-cache, no-store, must-revalidate")
        response.set_header("Pragma", "no-cache")
        response.set_header("Expires", "0")

        categories = get_download_categories()
        default_download_categories = [
            cat for cat in DOWNLOAD_CATEGORIES if cat in categories
        ]
        custom_download_categories = sorted(
            [cat for cat in categories if cat not in DOWNLOAD_CATEGORIES]
        )
        ordered_download_categories = (
            default_download_categories + custom_download_categories
        )
        can_add_download_category = len(custom_download_categories) < 10

        # Generate list items for Download Categories
        download_list_items = ""
        for cat in ordered_download_categories:
            emoji = (
                DOWNLOAD_CATEGORIES[cat]["emoji"]
                if cat in DOWNLOAD_CATEGORIES
                else "📁"
            )
            mirrors = get_download_category_mirrors(cat)
            mirrors_str = ", ".join(mirrors) if mirrors else "All"
            mirrors_json = json.dumps(mirrors)
            item_css_class = (
                "category-item custom-category-item"
                if cat not in DOWNLOAD_CATEGORIES
                else "category-item"
            )

            delete_btn = ""
            # Prevent deleting default categories
            if cat not in DOWNLOAD_CATEGORIES:
                delete_btn = f"""
                <button class="btn-danger" onclick="deleteCategory('{cat}')">Delete</button>
                """

            # Combined edit button
            edit_btn = f"""
            <button class="btn-primary" onclick='editCategory("{cat}", {mirrors_json})'>Edit</button>
            """

            download_list_items += f"""
            <div class="{item_css_class}">
                <span class="category-emoji">{emoji}</span>
                <div class="category-details">
                    <span class="category-name">{cat}</span>
                    <span class="category-mirrors">Mirrors: {mirrors_str}</span>
                </div>
                <div class="category-actions">
                    {delete_btn}
                    {edit_btn}
                </div>
            </div>
            """

        # Generate list items for Search Categories
        search_list_items = ""
        all_search_categories = get_search_categories()
        # Sort by ID
        sorted_search_cats = sorted(
            all_search_categories.items(), key=lambda x: int(x[0])
        )

        supported_categories_union = set()
        for source in get_sources().values():
            supported_categories_union.update(source.supported_categories)

        # filter search categories so that any categories without any supporting sources are removed
        sorted_search_cats = [
            (cat_id, details)
            for cat_id, details in sorted_search_cats
            if has_source_capability_for_category(cat_id, supported_categories_union)
        ]

        default_search_cats = []
        custom_search_cats = []
        grouped_default_subcategories = {}

        for cat_id, details in sorted_search_cats:
            cat_id = int(cat_id)
            if cat_id >= 100000:
                custom_search_cats.append((cat_id, details))
                continue

            owner_cat_id = get_search_category_whitelist_owner(cat_id)
            if owner_cat_id != cat_id:
                grouped_default_subcategories.setdefault(owner_cat_id, []).append(
                    (cat_id, details)
                )
                continue

            default_search_cats.append((cat_id, details))

        default_search_cats.sort(key=lambda x: int(x[0]))
        custom_search_cats.sort(key=lambda x: int(x[0]))
        for owner_cat_id in grouped_default_subcategories:
            grouped_default_subcategories[owner_cat_id].sort(key=lambda x: int(x[0]))

        used_custom_base_types = set()
        for custom_cat_id, custom_details in custom_search_cats:
            custom_base_type = custom_details.get("base_type")
            try:
                used_custom_base_types.add(int(custom_base_type))
            except (TypeError, ValueError):
                if int(custom_cat_id) >= 100000:
                    used_custom_base_types.add(int(custom_cat_id) - 100000)

        selectable_base_categories = [
            (int(cat_id), details)
            for cat_id, details in sorted_search_cats
            if int(cat_id) < 100000 and int(cat_id) not in used_custom_base_types
        ]
        base_category_options = "".join(
            [
                f'<option value="{int(cat_id)}">{details["name"]} ({int(cat_id)})</option>'
                for cat_id, details in selectable_base_categories
            ]
        )
        can_add_search_category = len(custom_search_cats) < 10 and bool(
            selectable_base_categories
        )

        for cat_id, details in default_search_cats:
            name = details["name"]
            heading_name = get_search_category_ui_heading(name)
            emoji = details["emoji"]
            search_sources = get_search_category_sources(cat_id)
            base_source_category_id = get_search_capability_category(cat_id) or cat_id
            search_sources_str = (
                ", ".join([s.upper() for s in search_sources])
                if search_sources
                else "All"
            )
            search_sources_json = json.dumps(search_sources)

            edit_btn = f"""
            <button class="btn-primary" onclick='editSearchCategory({cat_id}, "{name}", {search_sources_json}, {base_source_category_id})'>Edit</button>
            """

            inherited_subcats = grouped_default_subcategories.get(cat_id, [])
            category_pills = [f"{name} ({cat_id})"] + [
                f"{sub_details['name']} ({sub_cat_id})"
                for sub_cat_id, sub_details in inherited_subcats
            ]
            category_pills_html = "".join(
                [
                    f'<span class="category-badge">{pill}</span>'
                    for pill in category_pills
                ]
            )

            search_list_items += f"""
            <div class="category-item">
                <span class="category-emoji">{emoji}</span>
                <div class="category-details">
                    <span class="category-name">{heading_name}</span>
                    <span class="category-mirrors">Hostnames: {search_sources_str}</span>
                    <div class="category-subcategories">
                        {category_pills_html}
                    </div>
                </div>
                <div class="category-actions">
                    {edit_btn}
                </div>
            </div>
            """

        for cat_id, details in custom_search_cats:
            cat_id = int(cat_id)
            name = details["name"]
            emoji = details["emoji"]
            search_sources = get_search_category_sources(cat_id)
            base_source_category_id = get_search_capability_category(cat_id) or cat_id
            search_sources_str = (
                ", ".join([s.upper() for s in search_sources])
                if search_sources
                else "All"
            )
            search_sources_json = json.dumps(search_sources)

            delete_btn = f"""
            <button class="btn-danger" onclick="deleteSearchCategory('{cat_id}')">Delete</button>
            """
            edit_btn = f"""
            <button class="btn-primary" onclick='editSearchCategory({cat_id}, "{name}", {search_sources_json}, {base_source_category_id})'>Edit</button>
            """

            custom_base_type = details.get("base_type")
            try:
                custom_base_type = int(custom_base_type)
            except (TypeError, ValueError):
                custom_base_type = get_search_capability_category(cat_id) or cat_id

            custom_pills = [f"Custom ({cat_id} -> {custom_base_type})"]
            custom_pills_html = "".join(
                [f'<span class="category-badge">{pill}</span>' for pill in custom_pills]
            )

            search_list_items += f"""
            <div class="category-item custom-category-item">
                <span class="category-emoji">{emoji}</span>
                <div class="category-details">
                    <span class="category-name">{name}</span>
                    <span class="category-mirrors">Hostnames: {search_sources_str}</span>
                    <div class="category-subcategories">
                        {custom_pills_html}
                    </div>
                </div>
                <div class="category-actions">
                    {delete_btn}
                    {edit_btn}
                </div>
            </div>
            """

        # Prepare hosters list for JS
        hosters_js = json.dumps(SHARE_HOSTERS)
        recommended_js = json.dumps(RECOMMENDED_HOSTERS)
        search_sources_js = json.dumps(get_hostnames())
        supported_categories_per_source = {
            source.initials: source.supported_categories
            for source in get_sources().values()
        }

        download_add_form_html = ""
        if can_add_download_category:
            download_add_form_html = """
            <div class="add-category-form category-list">
                <div class="category-item">
                    <input type="text" id="newCategoryName" placeholder="New category name (a-z, 0-9, _)" pattern="[a-z0-9_]+" title="Lowercase letters, numbers and underscores only">
                    <button class="btn-primary" onclick="addCategory()">Add</button>
                </div>
            </div>
            """

        search_add_form_html = ""
        if can_add_search_category:
            search_add_form_html = f"""
            <div class="add-category-form category-list">
                <div class="category-item">
                    <select id="newSearchCategoryBase" style="flex: 1;">
                        <option value="" disabled selected>Select Base Category Type</option>
                        {base_category_options}
                    </select>
                    <button class="btn-primary" onclick="addSearchCategory()">Add Custom Category</button>
                </div>
            </div>
            """

        form_html = f"""
        <style>
            .category-list {{
                display: flex;
                flex-direction: column;
                gap: 0.5rem;
                margin-bottom: 1.5rem;
                border: 1px solid var(--border-color, #dee2e6);
                border-radius: 0.5rem;
                padding: 0.5rem;
            }}
            .category-item {{
                display: flex;
                align-items: center;
                padding: 0.75rem;
                background: var(--code-bg, #f8f9fa);
                border-radius: 0.5rem;
                gap: 1rem;
            }}
            .custom-category-item {{
                background: var(--custom-category-bg, #eef2ff);
            }}
            .category-emoji {{
                font-size: 1.5em;
                min-width: 1.5em;
                text-align: center;
            }}
            .category-details {{
                flex: 1;
                display: flex;
                flex-direction: column;
            }}
            .category-name {{
                font-weight: 600;
                font-size: 1.1em;
            }}
            .category-mirrors {{
                font-size: 0.85em;
                color: var(--text-muted);
            }}
            .category-subnote {{
                font-size: 0.82em;
                color: var(--text-muted);
                margin-top: 0.25rem;
            }}
            .category-subcategories {{
                margin-top: 0.35rem;
                display: flex;
                flex-wrap: wrap;
                gap: 0.35rem;
                align-items: center;
                justify-content: center;
            }}
            .category-badge {{
                font-size: 0.78em;
                border: 1px solid var(--border-color, #dee2e6);
                border-radius: 999px;
                padding: 0.15rem 0.5rem;
                background: var(--card-bg, #ffffff);
            }}
            .category-actions {{
                display: flex;
                gap: 0.5rem;
            }}
            .add-category-form {{
                display: flex;
                gap: 0.5rem;
                margin-bottom: 1rem;
                align-items: stretch;
            }}
            .add-category-form input, .add-category-form select {{
                margin-bottom: 0 !important;
            }}
            .add-category-form button {{
                margin-top: 0 !important;
            }}
            .add-category-form input[type="text"] {{
                flex: 1;
            }}
            .warning-box {{
                background: var(--error-bg);
                color: var(--error-color);
                border: 1px solid var(--error-border);
                padding: 0.75rem;
                border-radius: 0.5rem;
                margin-bottom: 1rem;
                font-size: 0.9em;
                text-align: left;
            }}
            
            /* Mirror Picker Redesign */
            .mirrors-grid {{
                display: flex;
                flex-wrap: wrap;
                gap: 0.5rem;
                margin-top: 0.5rem;
            }}
            .mirror-pill {{
                padding: 0.5rem 0.75rem;
                border: 1px solid var(--border-color);
                border-radius: 2rem;
                cursor: pointer;
                font-size: 0.9rem;
                transition: all 0.2s;
                user-select: none;
                background: var(--card-bg);
                display: flex;
                align-items: center;
                gap: 0.25rem;
            }}
            .mirror-pill:hover {{
                border-color: var(--primary);
            }}
            .mirror-pill.selected {{
                background-color: var(--primary);
                color: white;
                border-color: var(--primary);
            }}
            .mirror-pill.tier1 {{
                font-weight: 600;
                border-color: var(--success-color);
            }}
            .mirror-pill.tier1.selected {{
                background-color: var(--success-color);
                border-color: var(--success-color);
            }}
            .mirror-hint {{
                margin: 0.75rem 0 0.6rem;
                font-size: 0.85rem;
                line-height: 1.45;
                color: var(--text-muted);
            }}
            .mirrors-sortable {{
                display: flex;
                flex-direction: column;
                gap: 0.35rem;
                margin-top: 0.25rem;
            }}
            .mirror-row {{
                display: flex;
                align-items: center;
                gap: 0.6rem;
                padding: 0 0.55rem;
                border: 1px solid var(--border-color);
                border-radius: 0.6rem;
                background: var(--card-bg);
                min-height: 2.9rem;
                transition: background-color 0.15s ease, border-color 0.15s ease;
            }}
            .mirror-row:not(.selected) {{
                color: var(--text-muted);
            }}
            .mirror-row:not(.selected):hover {{
                border-color: var(--primary);
            }}
            .mirror-row.selected {{
                background-color: var(--primary);
                color: #fff;
                border-color: var(--primary);
            }}
            .mirror-row.tier1.selected {{
                background-color: var(--success-color);
                border-color: var(--success-color);
            }}
            .mirror-rank {{
                flex: 0 0 auto;
                width: 1.7rem;
                height: 1.7rem;
                display: inline-flex;
                align-items: center;
                justify-content: center;
                border-radius: 50%;
                font-size: 0.8rem;
                font-weight: 700;
                line-height: 1;
                background: rgba(255, 255, 255, 0.28);
                color: #fff;
            }}
            .mirror-row:not(.selected) .mirror-rank {{
                visibility: hidden;
            }}
            .mirror-row-label {{
                display: flex;
                align-items: center;
                gap: 0.45rem;
                flex: 1;
                align-self: stretch;
                min-width: 0;
                padding: 0.4rem 0;
                margin: 0;
                cursor: pointer;
                user-select: none;
                font-size: 0.95rem;
                font-weight: 600;
                line-height: 1.3;
            }}
            .mirror-label {{
                min-width: 0;
                overflow-wrap: anywhere;
            }}
            .mirror-star {{
                flex: 0 0 auto;
                font-weight: 400;
                line-height: 1;
            }}
            .mirror-move {{
                display: flex;
                align-items: center;
                gap: 0.25rem;
                flex: 0 0 auto;
            }}
            .mirror-row:not(.selected) .mirror-move {{
                visibility: hidden;
            }}
            .mirror-move-btn {{
                display: flex;
                align-items: center;
                justify-content: center;
                width: 2.2rem;
                height: 2.2rem;
                border: none;
                border-radius: 0.45rem;
                background: rgba(255, 255, 255, 0.22);
                cursor: pointer;
                font-size: 1rem;
                line-height: 1;
                padding: 0;
                margin: 0;
            }}
            .mirror-move-btn:hover {{
                background: rgba(255, 255, 255, 0.4);
            }}
            .mirror-move-btn:active {{
                transform: translateY(1px);
            }}
            .mirror-checkbox, .search-source-checkbox {{
                display: none;
            }}
            h3 {{
                margin-top: 0;
                margin-bottom: 0.5rem;
                font-size: 1.2em;
            }}
            p.description {{
                margin-bottom: 1rem;
                color: var(--text-muted);
                font-size: 0.9em;
            }}
        </style>

        <h3>Download Categories</h3>
        <p class="description">Manage categories used for organizing downloads in JDownloader.</p>
        <div class="category-list" id="downloadCategoryList">
            {download_list_items}
        </div>

        {download_add_form_html}

        <h3>Search Categories</h3>
        <p class="description">Manage hostname whitelists for Newznab search categories.</p>
        <div class="category-list" id="searchCategoryList">
            {search_list_items}
        </div>

        {search_add_form_html}

        <p>{render_button("Back", "secondary", {"onclick": "location.href='/'"})}</p>

        <script>
        const ALL_HOSTERS = {hosters_js};
        const TIER1_HOSTERS = {recommended_js};
        const HOSTNAMES = {search_sources_js};
        const SUPPORTED_CATEGORIES_PER_SOURCE = JSON.parse('{json.dumps(supported_categories_per_source)}');

        function addCategory() {{
            const nameInput = document.getElementById('newCategoryName');
            const name = nameInput.value.trim();
            
            if (!name) return;
            
            quasarrApiFetch('/api/categories', {{
                method: 'POST',
                headers: {{ 'Content-Type': 'application/json' }},
                body: JSON.stringify({{ name: name }})
            }})
            .then(response => response.json())
            .then(data => {{
                if (data.success) {{
                    window.location.reload();
                }} else {{
                    showModal('Error', data.message);
                }}
            }})
            .catch(error => {{
                showModal('Error', 'Failed to add category: ' + error.message);
            }});
        }}
        
        function addSearchCategory() {{
            const baseSelect = document.getElementById('newSearchCategoryBase');
            const baseType = baseSelect.value;
            
            if (!baseType) return;
            
            quasarrApiFetch('/api/categories_search', {{
                method: 'POST',
                headers: {{ 'Content-Type': 'application/json' }},
                body: JSON.stringify({{ base_type: baseType }})
            }})
            .then(response => response.json())
            .then(data => {{
                if (data.success) {{
                    window.location.reload();
                }} else {{
                    showModal('Error', data.message);
                }}
            }})
            .catch(error => {{
                showModal('Error', 'Failed to add search category: ' + error.message);
            }});
        }}

        function editCategory(name, currentMirrors) {{
            // Enabled mirrors first, in their saved priority order, then the rest.
            const selected = currentMirrors.filter(m => ALL_HOSTERS.includes(m));
            const unselected = ALL_HOSTERS.filter(h => !selected.includes(h));
            const ordered = selected.concat(unselected);

            let rows = '';
            ordered.forEach(hoster => {{
                const isChecked = currentMirrors.includes(hoster);
                const isTier1 = TIER1_HOSTERS.includes(hoster);
                const tierClass = isTier1 ? 'tier1' : '';
                const selectedClass = isChecked ? 'selected' : '';
                const star = isTier1 ? '<span class="mirror-star">⭐</span>' : '';

                rows += '<div class="mirror-row ' + tierClass + ' ' + selectedClass + '">' +
                        '<span class="mirror-rank"></span>' +
                        '<label class="mirror-row-label">' +
                        '<input type="checkbox" class="mirror-checkbox" value="' + hoster + '" ' + (isChecked ? 'checked' : '') + ' onchange="reflowMirrors()">' +
                        star +
                        '<span class="mirror-label">' + hoster + '</span>' +
                        '</label>' +
                        '<span class="mirror-move">' +
                        '<button type="button" class="mirror-move-btn" onclick="moveMirror(this, -1)" aria-label="Move up" title="Move up">⬆️</button>' +
                        '<button type="button" class="mirror-move-btn" onclick="moveMirror(this, 1)" aria-label="Move down" title="Move down">⬇️</button>' +
                        '</span>' +
                        '</div>';
            }});

            const content = '<div class="warning-box">' +
                            '<strong>⚠️ Heads up:</strong> the mirror-whitelist only affects downloads, not search. ' +
                            'If you enable specific mirrors, a release must include one of them or its download fails.' +
                            '</div>' +
                            '<p class="mirror-hint">' +
                            'Tap a mirror to enable it. Enabled mirrors move to the top and form a priority list. ' +
                            'The topmost found mirror is auto-decrypted. Use ⬆️ / ⬇️ to reorder. ⭐ marks recommended mirrors.' +
                            '</p>' +
                            '<div class="mirrors-sortable" id="mirrorSortable">' +
                            rows +
                            '</div>';

            showModal('Edit Download Category: ' + name, content,
                '<button class="btn-secondary" onclick="closeModal()">Cancel</button>' +
                '<button class="btn-primary" onclick="performEditCategory(\\'' + name + '\\')">Save</button>'
            );
            reflowMirrors();
        }}

        function reflowMirrors() {{
            const parent = document.getElementById('mirrorSortable');
            if (!parent) return;
            const rows = Array.from(parent.children);
            const isOn = row => row.querySelector('.mirror-checkbox').checked;
            // Stable partition: enabled rows on top (keep their order), disabled below.
            const enabled = rows.filter(isOn);
            const disabled = rows.filter(row => !isOn(row));
            enabled.concat(disabled).forEach(row => parent.appendChild(row));
            rows.forEach(row => row.classList.toggle('selected', isOn(row)));
            enabled.forEach((row, i) => {{
                row.querySelector('.mirror-rank').textContent = (i + 1);
            }});
            disabled.forEach(row => {{
                row.querySelector('.mirror-rank').textContent = '';
            }});
        }}

        function moveMirror(btn, dir) {{
            const row = btn.closest('.mirror-row');
            if (!row) return;
            // Step one position, staying inside the enabled (ranked) group.
            const sibling = dir < 0 ? row.previousElementSibling : row.nextElementSibling;
            if (!sibling || !sibling.querySelector('.mirror-checkbox').checked) return;
            if (dir < 0) {{
                row.parentNode.insertBefore(row, sibling);
            }} else {{
                row.parentNode.insertBefore(sibling, row);
            }}
            reflowMirrors();
        }}

        function editSearchCategory(catId, name, currentSearchSources, baseCategoryId) {{
            let searchPills = '';
            HOSTNAMES.forEach(source => {{
                if (SUPPORTED_CATEGORIES_PER_SOURCE[source]) {{
                    const parsedBaseCategoryId = parseInt(baseCategoryId, 10);
                    const categoryForFilter = Number.isNaN(parsedBaseCategoryId) ? catId : parsedBaseCategoryId;
                    const supportsCategory = SUPPORTED_CATEGORIES_PER_SOURCE[source].includes(categoryForFilter);
                    if (!supportsCategory) return; // Skip sources that don't support this category
                }}

                const isChecked = currentSearchSources.includes(source);
                const selectedClass = isChecked ? 'selected' : '';
                
                searchPills += '<label class="mirror-pill ' + selectedClass + '" onclick="this.classList.toggle(\\'selected\\')">' +
                         '<input type="checkbox" class="search-source-checkbox" value="' + source + '" ' + (isChecked ? 'checked' : '') + ' onchange="this.parentElement.classList.toggle(\\'selected\\', this.checked)">' +
                         source.toUpperCase() +
                         '</label>';
            }});

            const content = '<h4>Hostname-Whitelist:</h4>' +
                            '<div class="warning-box">' +
                            '<strong>⚠️ Warning:</strong><br>This affects search results.<br>' +
                            'If specific hostnames are set, only these will be searched.' +
                            '</div>' +
                            '<div class="mirrors-grid">' +
                            searchPills +
                            '</div>';
            
            showModal('Edit Search Category: ' + name, content, 
                '<button class="btn-secondary" onclick="closeModal()">Cancel</button>' +
                '<button class="btn-primary" onclick="performEditSearchCategory(\\'' + catId + '\\')">Save</button>'
            );
        }}

        function performEditCategory(name) {{
            const selectedMirrors = [];
            document.querySelectorAll('.mirror-checkbox:checked').forEach(cb => {{
                selectedMirrors.push(cb.value);
            }});
            
            closeModal();
            
            quasarrApiFetch('/api/categories/' + name + '/mirrors', {{
                method: 'POST',
                headers: {{ 'Content-Type': 'application/json' }},
                body: JSON.stringify({{ mirrors: selectedMirrors }})
            }})
            .then(response => response.json())
            .then(data => {{
                if (data.success) {{
                    window.location.reload();
                }} else {{
                    showModal('Error', data.message);
                }}
            }})
            .catch(error => {{
                showModal('Error', 'Failed to update category: ' + error.message);
            }});
        }}

        function performEditSearchCategory(catId) {{
            const selectedSearchSources = [];
            document.querySelectorAll('.search-source-checkbox:checked').forEach(cb => {{
                selectedSearchSources.push(cb.value);
            }});
            
            closeModal();
            
            quasarrApiFetch('/api/categories_search/' + catId + '/search_sources', {{
                method: 'POST',
                headers: {{ 'Content-Type': 'application/json' }},
                body: JSON.stringify({{ search_sources: selectedSearchSources }})
            }})
            .then(response => response.json())
            .then(data => {{
                if (data.success) {{
                    window.location.reload();
                }} else {{
                    showModal('Error', data.message);
                }}
            }})
            .catch(error => {{
                showModal('Error', 'Failed to update search category: ' + error.message);
            }});
        }}

        function deleteCategory(name) {{
            showModal('Delete Category?', 'Are you sure you want to delete category "' + name + '"?', 
                '<button class="btn-secondary" onclick="closeModal()">Cancel</button>' +
                '<button class="btn-danger" onclick="performDeleteCategory(\\'' + name + '\\')">Delete</button>'
            );
        }}
        
        function deleteSearchCategory(catId) {{
            showModal('Delete Search Category?', 'Are you sure you want to delete search category "' + catId + '"?', 
                '<button class="btn-secondary" onclick="closeModal()">Cancel</button>' +
                '<button class="btn-danger" onclick="performDeleteSearchCategory(\\'' + catId + '\\')">Delete</button>'
            );
        }}

        function performDeleteCategory(name) {{
            closeModal();
            quasarrApiFetch('/api/categories/' + name, {{
                method: 'DELETE'
            }})
            .then(response => response.json())
            .then(data => {{
                if (data.success) {{
                    window.location.reload();
                }} else {{
                    showModal('Error', data.message);
                }}
            }})
            .catch(error => {{
                showModal('Error', 'Failed to delete category: ' + error.message);
            }});
        }}
        
        function performDeleteSearchCategory(catId) {{
            closeModal();
            quasarrApiFetch('/api/categories_search/' + catId, {{
                method: 'DELETE'
            }})
            .then(response => response.json())
            .then(data => {{
                if (data.success) {{
                    window.location.reload();
                }} else {{
                    showModal('Error', data.message);
                }}
            }})
            .catch(error => {{
                showModal('Error', 'Failed to delete search category: ' + error.message);
            }});
        }}
        </script>
        """
        return render_form("Categories", form_html)

    @app.post("/api/categories")
    @require_api_key
    def add_category_api():
        response.content_type = "application/json"
        try:
            data = request.json
            name = data.get("name")
            success, message = add_download_category(name)
            return {"success": success, "message": message}
        except Exception as e:
            return {"success": False, "message": str(e)}

    @app.post("/api/categories_search")
    @require_api_key
    def add_search_category_api():
        response.content_type = "application/json"
        try:
            data = request.json
            base_type = data.get("base_type")
            success, message = add_custom_search_category(base_type)
            return {"success": success, "message": message}
        except Exception as e:
            return {"success": False, "message": str(e)}

    @app.post("/api/categories/<name>/mirrors")
    @require_api_key
    def update_category_mirrors_api(name):
        response.content_type = "application/json"
        try:
            data = request.json
            mirrors = data.get("mirrors", [])
            success, message = update_download_category_mirrors(name, mirrors)
            return {"success": success, "message": message}
        except Exception as e:
            return {"success": False, "message": str(e)}

    @app.post("/api/categories_search/<cat_id>/search_sources")
    @require_api_key
    def update_search_category_sources_api(cat_id):
        response.content_type = "application/json"
        try:
            data = request.json
            search_sources = data.get("search_sources", [])
            success, message = update_search_category_sources(cat_id, search_sources)
            return {"success": success, "message": message}
        except Exception as e:
            return {"success": False, "message": str(e)}

    @app.delete("/api/categories/<name>")
    @require_api_key
    def delete_category_api(name):
        response.content_type = "application/json"
        try:
            success, message = delete_download_category(name)
            return {"success": success, "message": message}
        except Exception as e:
            return {"success": False, "message": str(e)}

    @app.delete("/api/categories_search/<cat_id>")
    @require_api_key
    def delete_search_category_api(cat_id):
        response.content_type = "application/json"
        try:
            success, message = delete_search_category(cat_id)
            return {"success": success, "message": message}
        except Exception as e:
            return {"success": False, "message": str(e)}
