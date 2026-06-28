# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import json
import time
from functools import wraps

from bottle import abort, request

from quasarr.downloads import fail, submit_final_download_urls
from quasarr.providers import shared_state
from quasarr.providers.auth import require_api_key
from quasarr.providers.log import info, warn
from quasarr.providers.notifications import update_release_notification
from quasarr.providers.notifications.helpers.notification_types import NotificationType
from quasarr.providers.statistics import StatsHelper
from quasarr.storage.categories import (
    get_download_category_from_package_id,
    get_download_category_mirrors,
)
from quasarr.storage.config import Config


def require_helper_active(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if shared_state.values.get("helper_active", False):
            last_seen = shared_state.values.get("helper_last_seen", 0)
            if last_seen > 0 and time.time() - last_seen > 300:
                warn(
                    "SponsorsHelper last seen more than 5 minutes ago. Deactivating..."
                )
                shared_state.update("helper_active", False)

        if not shared_state.values.get("helper_active"):
            abort(402, "Sponsors Payment Required")
        return func(*args, **kwargs)

    return wrapper


def normalize_helper_supported_urls(url_patterns):
    if not isinstance(url_patterns, (list, tuple, set)):
        return []

    normalized_patterns = []
    seen_patterns = set()

    for pattern in url_patterns:
        if pattern is None:
            continue

        normalized_pattern = str(pattern).strip().lower()
        if not normalized_pattern or normalized_pattern in seen_patterns:
            continue

        normalized_patterns.append(normalized_pattern)
        seen_patterns.add(normalized_pattern)

    return normalized_patterns


def extract_helper_candidate_url(link):
    if isinstance(link, (list, tuple)) and link:
        candidate = link[0]
    else:
        candidate = link

    if not isinstance(candidate, str):
        return ""

    return candidate.strip()


def is_rapidgator_link(link):
    if isinstance(link, (list, tuple)) and len(link) > 1:
        mirror_name = link[1]
        if isinstance(mirror_name, str) and "rapidgator" in mirror_name.lower():
            return True

    return "rapidgator" in extract_helper_candidate_url(link).lower()


def prioritize_helper_supported_links(links, supported_url_patterns):
    if not isinstance(links, list):
        return [], []

    normalized_patterns = normalize_helper_supported_urls(supported_url_patterns)
    if not normalized_patterns:
        return list(links), list(links)

    supported_links = []
    unsupported_links = []

    for link in links:
        candidate_url = extract_helper_candidate_url(link).lower()
        if candidate_url and any(
            pattern in candidate_url for pattern in normalized_patterns
        ):
            supported_links.append(link)
        else:
            unsupported_links.append(link)

    return supported_links + unsupported_links, supported_links


def select_helper_package(protected_packages, supported_url_patterns):
    for package in protected_packages:
        data = json.loads(package[1])
        if "disabled" in data:
            continue

        raw_links = data.get("links")
        if not isinstance(raw_links, list) or not raw_links:
            continue

        rapid = [ln for ln in raw_links if is_rapidgator_link(ln)]
        others = [ln for ln in raw_links if not is_rapidgator_link(ln)]
        prioritized_links = rapid + others

        prioritized_links, supported_links = prioritize_helper_supported_links(
            prioritized_links,
            supported_url_patterns,
        )
        if supported_url_patterns and not supported_links:
            continue

        return package[0], data, prioritized_links

    return None


def setup_sponsors_helper_routes(app):
    def get_protected_release(package_id):
        try:
            raw_data = shared_state.get_db("protected").retrieve(package_id)
            data = json.loads(raw_data) if raw_data else None
        except Exception as e:
            info(
                f'Error reading protected package "{package_id}" for notification: {e}'
            )
            return None
        return data if isinstance(data, dict) else None

    def get_supported_urls_from_request():
        payload = request.json if request.method == "POST" else None
        if isinstance(payload, dict) and "supported_urls" in payload:
            return normalize_helper_supported_urls(payload.get("supported_urls"))

        query_values = request.query.getall("supported_url")
        if query_values:
            return normalize_helper_supported_urls(query_values)

        query_csv = request.query.get("supported_urls")
        if query_csv:
            return normalize_helper_supported_urls(query_csv.split(","))

        return []

    def extract_failure_reason(data, default_reason=None):
        if not isinstance(data, dict):
            return default_reason

        reason = data.get("reason") or data.get("error")
        if reason:
            return str(reason)
        return default_reason

    def mark_helper_package_failed(package_id, title, reason):
        protected_release = get_protected_release(package_id)
        if protected_release and protected_release.get("title"):
            title = protected_release["title"]
        fail(title, package_id, shared_state, reason=reason)
        try:
            shared_state.get_db("protected").delete(package_id)
        except Exception as e:
            info(
                f'Error deleting protected package "{package_id}" after helper failure: {e}'
            )
        update_release_notification(
            shared_state,
            protected_release or {"title": title},
            NotificationType.FAILED,
            details={"reason": reason},
        )
        return {
            "success": False,
            "failed": True,
            "reason": reason,
        }

    @app.get("/sponsors_helper/api/ping/")
    @require_api_key
    def ping_api():
        """Health check endpoint for SponsorsHelper to verify connectivity."""
        return "pong"

    @app.get("/sponsors_helper/api/credentials/<hostname>/")
    @require_api_key
    @require_helper_active
    def credentials_api(hostname):
        section = hostname.upper()
        if section not in ["AL", "DD", "DL", "NX", "JUNKIES"]:
            return abort(404, f"No credentials for {hostname}")

        config = Config(section)
        user = config.get("user")
        password = config.get("password")

        if not user or not password:
            return abort(404, f"Credentials not set for {hostname}")

        return {"user": user, "pass": password}

    @app.get("/sponsors_helper/api/mirrors/<package_id>/")
    @require_api_key
    @require_helper_active
    def mirrors_api(package_id):
        category = get_download_category_from_package_id(package_id)
        mirrors = get_download_category_mirrors(category)
        return {"mirrors": mirrors}

    @app.get("/sponsors_helper/api/to_decrypt/")
    @app.post("/sponsors_helper/api/to_decrypt/")
    @require_api_key
    def to_decrypt_api():
        shared_state.update("helper_active", True)
        shared_state.update("helper_last_seen", int(time.time()))
        try:
            protected = shared_state.get_db("protected").retrieve_all_titles()
            if not protected:
                return abort(404, "No encrypted packages found")

            supported_url_patterns = get_supported_urls_from_request()

            # Issue #350: only hand SponsorsHelper packages where at least one URL
            # matches the helper's advertised support, and move that URL to the front.
            selected_package = select_helper_package(protected, supported_url_patterns)

            if not selected_package:
                return abort(404, "No valid packages found")

            package_id, data, prioritized_links = selected_package
            title = data["title"]
            mirror = None if (mirror := data.get("mirror")) == "None" else mirror
            password = data["password"]

            return {
                "to_decrypt": {
                    "name": title,
                    "id": package_id,
                    "url": prioritized_links,
                    "mirror": mirror,
                    "password": password,
                    "max_attempts": 3,
                }
            }
        except Exception as e:
            return abort(500, str(e))

    @app.post("/sponsors_helper/api/download/")
    @require_api_key
    @require_helper_active
    def download_api():
        try:
            data = request.json or {}
            if not isinstance(data, dict):
                return abort(400, "Missing or invalid JSON object")
            title = data.get("name")
            package_id = data.get("package_id")
            download_links = data.get("urls")
            password = data.get("password")
            notification = data.get("notification")

            if not isinstance(notification, dict):
                return abort(400, "Missing or invalid 'notification' object")
            if not isinstance(notification.get("solvers"), list):
                return abort(400, "Missing or invalid 'notification.solvers' list")
            if not package_id:
                return abort(400, "Missing or invalid 'package_id'")
            if not title:
                title = "Unknown"
            if not isinstance(download_links, list):
                StatsHelper(shared_state).increment_failed_decryptions_automatic()
                return mark_helper_package_failed(
                    package_id,
                    title,
                    "SponsorsHelper returned an invalid download payload.",
                )

            info(
                f"Received <green>{len(download_links)}</green> download links for <y>{title}</y>"
            )

            if download_links:
                submit_result = submit_final_download_urls(
                    shared_state,
                    download_links,
                    title,
                    password,
                    package_id,
                    remove_protected=True,
                    notification_details=notification,
                )
                if submit_result["success"]:
                    final_links = submit_result["links"]
                    StatsHelper(shared_state).increment_package_with_links(final_links)
                    StatsHelper(shared_state).increment_captcha_decryptions_automatic()

                    log_msg = f"Download successfully started for <y>{title}</y>"
                    providers = notification.get("solvers")
                    used_providers = []
                    if isinstance(providers, list) and providers:
                        for provider in providers:
                            if not isinstance(provider, dict):
                                continue
                            provider_name = provider.get("name")
                            if provider_name:
                                used_providers.append(str(provider_name))
                    if used_providers:
                        unique_providers = sorted(set(used_providers))
                        log_msg += f" | Providers: {', '.join(unique_providers)}"
                    if notification.get("duration_seconds") is not None:
                        log_msg += (
                            f" | Duration: {notification.get('duration_seconds')}s"
                        )
                    info(log_msg)
                    return f"Downloaded {len(final_links)} download links for {title}"
                elif submit_result.get("persisted_failure"):
                    StatsHelper(shared_state).increment_failed_decryptions_automatic()
                    return {
                        "success": False,
                        "failed": True,
                        "reason": submit_result["reason"],
                    }
                else:
                    info(f"Download failed for <y>{title}</y>")
            else:
                StatsHelper(shared_state).increment_failed_decryptions_automatic()
                return mark_helper_package_failed(
                    package_id,
                    title,
                    "SponsorsHelper returned no final download links.",
                )

        except Exception as e:
            info(f"Error decrypting: {e}")

        StatsHelper(shared_state).increment_failed_decryptions_automatic()
        return abort(500, "Failed")

    @app.post("/sponsors_helper/api/disable/")
    @require_api_key
    @require_helper_active
    def disable_api():
        try:
            data = request.json or {}
            if not isinstance(data, dict):
                return {"error": "Missing or invalid JSON object"}, 400
            package_id = data.get("package_id")
            reason = extract_failure_reason(data)

            if not package_id:
                return {"error": "Missing package_id"}, 400

            StatsHelper(shared_state).increment_failed_decryptions_automatic()

            blob = shared_state.get_db("protected").retrieve(package_id)
            package_data = json.loads(blob)
            title = package_data.get("title")

            package_data["disabled"] = True
            shared_state.get_db("protected").update_store(
                package_id, json.dumps(package_data)
            )
            info(f"Disabled package {title}")

            StatsHelper(shared_state).increment_captcha_decryptions_automatic()

            update_release_notification(
                shared_state,
                package_data,
                NotificationType.DISABLED,
                details={"reason": reason} if reason else None,
            )
            shared_state.get_db("protected").update_store(
                package_id, json.dumps(package_data)
            )

            return f"Package <y>{title}</y> disabled"

        except Exception as e:
            info(f"Error handling disable: {e}")
            return {"error": str(e)}, 500

    @app.delete("/sponsors_helper/api/fail/")
    @require_api_key
    @require_helper_active
    def fail_api():
        try:
            StatsHelper(shared_state).increment_failed_decryptions_automatic()

            data = request.json or {}
            package_id = data.get("package_id")
            # SponsorsHelper might send 'name' or 'title'
            title = data.get("name") or data.get("title")
            reason = extract_failure_reason(
                data,
                default_reason="Too many failed attempts by SponsorsHelper",
            )

            # 1. Try to find package in Protected DB if ID is missing but Title exists
            if not package_id and title:
                try:
                    protected_packages = shared_state.get_db(
                        "protected"
                    ).retrieve_all_titles()
                    for pkg in protected_packages:
                        # pkg is (id, json_str)
                        try:
                            pkg_data = json.loads(pkg[1])
                            if pkg_data.get("title") == title:
                                package_id = pkg[0]
                                info(
                                    f"Found package ID <y>{package_id}</y> for title <y>{title}</y>"
                                )
                                break
                        except Exception:
                            pass
                except Exception as e:
                    info(f"Error searching protected DB by title: {e}")

            # 2. If we have an ID, try to get canonical title from DB (if not provided or to verify)
            if package_id:
                protected_release = get_protected_release(package_id)
                try:
                    db_entry = shared_state.get_db("protected").retrieve(package_id)
                    if db_entry:
                        db_data = json.loads(db_entry)
                        # Prefer DB title if available
                        if db_data.get("title"):
                            title = db_data.get("title")
                except Exception:
                    # If retrieval fails, we stick with the title we have (or "Unknown")
                    pass

            if not title:
                title = "Unknown"

            if package_id:
                info(
                    f"Marking package <y>{title}</y> with ID <y>{package_id}</y> as failed"
                )
                failed = fail(
                    title,
                    package_id,
                    shared_state,
                    reason=reason,
                )

                # Always try to delete from protected, even if fail() returns False
                try:
                    shared_state.get_db("protected").delete(package_id)
                except Exception as e:
                    info(f"Error deleting from protected DB: {e}")

                # Verify deletion
                try:
                    if shared_state.get_db("protected").retrieve(package_id):
                        info(
                            f"Verification failed: Package {package_id} still exists in protected DB"
                        )
                except Exception:
                    pass

                if failed:
                    update_release_notification(
                        shared_state,
                        protected_release or {"title": title},
                        NotificationType.FAILED,
                        details={"reason": reason},
                    )
                    return f'Package <y>{title}</y> with ID <y>{package_id}</y> marked as failed!"'
                else:
                    return f"Package <y>{title}</y> processed."
            else:
                return abort(400, "Missing package_id")
        except Exception as e:
            info(f"Error moving to failed: {e}")

        return abort(500, "Failed")

    @app.put("/sponsors_helper/api/set_sponsor_status/")
    @require_api_key
    def set_sponsor_status_api():
        try:
            data = request.body.read().decode("utf-8")
            payload = json.loads(data)
            if payload["activate"]:
                shared_state.update("helper_active", True)
                shared_state.update("helper_last_seen", int(time.time()))
                info("Sponsor status activated successfully")
                return "Sponsor status activated successfully!"
        except:
            pass
        return abort(500, "Failed")
