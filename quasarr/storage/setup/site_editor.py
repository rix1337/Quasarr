# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

"""Editing built-in sites in the site wizard, tested live, saved apart.

Changes lay over the shipped template (see ``storage.template_overrides``);
resetting deletes them. A changed site is the user's to maintain, so the page
says that issues about it are not supported.
"""

from bottle import abort, request, response

from quasarr.providers.auth import require_api_key
from quasarr.providers.log import info
from quasarr.storage.config import Config
from quasarr.storage.setup.sites import CATEGORY_LABELS

# wizard steps a site may run in its own code instead of the template
_STEPS = ("feed", "search", "download")


def _template_key(key):
    from quasarr.search.sources.templates import get_template_keys

    key = str(key or "").lower()
    return key if key in get_template_keys() else None


def template_state(key):
    """Shipped and current editable parts of one built-in site."""
    from quasarr.search.sources.templates import get_templates, shipped_definition
    from quasarr.storage.template_overrides import EDITABLE_PARTS, load_overrides

    shipped = shipped_definition(key)
    editable = {part: shipped[part] for part in EDITABLE_PARTS if part in shipped}
    changes = load_overrides().get(key) or {}
    source = get_templates()[key]
    return {
        "key": key.upper(),
        "shipped": editable,
        "current": {**editable, **changes},
        "modified": bool(changes),
        "code_steps": [step for step in _STEPS if step in shipped.get("hooks", {})],
        "parts": list(EDITABLE_PARTS),
        "categories": [
            {"id": cat, "name": label}
            for cat, label in CATEGORY_LABELS
            if cat in source.supported_categories
        ],
        "hostname": str(Config("Hostnames").get(key) or ""),
    }


def _changed_parts(key, current):
    """Only editable parts that differ from the shipped template count as changes.

    The wizard sends the whole definition; its name, hostname, language and
    hooks are not the user's to change and are left out.
    """
    from quasarr.search.sources.templates import shipped_definition
    from quasarr.storage.template_overrides import EDITABLE_PARTS

    if not isinstance(current, dict):
        raise ValueError("The template must be a JSON object")
    shipped = shipped_definition(key)
    # a part the shipped template leaves out stays unchanged while it is empty
    return {
        part: current[part]
        for part in EDITABLE_PARTS
        if part in current
        and shipped.get(part) != current[part]
        and (part in shipped or current[part])
    }


def builtin_definition(key):
    """The definition the wizard edits: the shipped template with the changes over it."""
    from quasarr.search.sources.templates import shipped_definition
    from quasarr.storage.template_overrides import load_overrides

    definition = shipped_definition(key)
    definition.update(load_overrides().get(key) or {})
    definition["hostname"] = str(Config("Hostnames").get(key) or "")
    return definition


def setup_site_editor_routes(app, shared_state, onboarding=False):
    @app.get("/sites/edit/<key>")
    def edit_builtin_site(key):
        from quasarr.storage.setup.custom_sources import custom_source_wizard_page

        key = _template_key(key)
        if not key:
            abort(404, "Unknown built-in site")
        return custom_source_wizard_page(builtin=key, onboarding=onboarding)

    @app.get("/api/sites/<key>/template")
    @require_api_key
    def get_site_template(key):
        response.content_type = "application/json"
        key = _template_key(key)
        if not key:
            response.status = 404
            return {"success": False, "error": "Unknown built-in site"}
        return {"success": True, **template_state(key)}

    @app.put("/api/sites/<key>/template")
    @require_api_key
    def save_site_template(key):
        from quasarr.storage.template_overrides import delete_override, save_override

        response.content_type = "application/json"
        key = _template_key(key)
        if not key:
            response.status = 404
            return {"success": False, "error": "Unknown built-in site"}
        try:
            changes = _changed_parts(key, (request.json or {}).get("template"))
            if changes:
                save_override(key, changes)
            else:
                delete_override(key)
        except Exception as e:
            response.status = 400
            return {"success": False, "error": str(e)}
        info(
            f"{key.upper()} now runs your changes to its built-in template"
            if changes
            else f"{key.upper()} runs its shipped template again"
        )
        return {"success": True, **template_state(key)}

    @app.delete("/api/sites/<key>/template")
    @require_api_key
    def reset_site_template(key):
        from quasarr.storage.template_overrides import delete_override

        response.content_type = "application/json"
        key = _template_key(key)
        if not key:
            response.status = 404
            return {"success": False, "error": "Unknown built-in site"}
        if delete_override(key):
            info(f"{key.upper()} runs its shipped template again")
        return {"success": True, **template_state(key)}

    @app.post("/api/sites/<key>/template/changes")
    @require_api_key
    def site_template_changes(key):
        """The parts an unsaved template changes against the shipped one."""
        response.content_type = "application/json"
        key = _template_key(key)
        if not key:
            response.status = 404
            return {"success": False, "error": "Unknown built-in site"}
        try:
            changed = _changed_parts(key, (request.json or {}).get("template"))
        except Exception as e:
            return {"success": False, "error": str(e)}
        return {"success": True, "changed": sorted(changed)}
