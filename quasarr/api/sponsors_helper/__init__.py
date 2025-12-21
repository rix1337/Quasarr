# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import json

from bottle import request, abort

from quasarr.downloads import fail
from quasarr.providers import shared_state
from quasarr.providers.log import info
from quasarr.providers.notifications import send_discord_message
from quasarr.providers.statistics import StatsHelper


def setup_sponsors_helper_routes(app):
    @app.get("/sponsors_helper/api/to_decrypt/")
    def to_decrypt_api():
        try:
            if not shared_state.values["helper_active"]:
                shared_state.update("helper_active", True)
                info(f"Sponsor status activated successfully")

            protected = shared_state.get_db("protected").retrieve_all_titles()
            if not protected:
                return abort(404, "No encrypted packages found")

            # Find the first package without a "session" key
            selected_package = None
            for package in protected:
                data = json.loads(package[1])
                if "session" not in data:
                    selected_package = (package[0], data)
                    break

            if not selected_package:
                return abort(404, "No valid packages without session found")

            package_id, data = selected_package
            title = data["title"]
            links = data["links"]
            mirror = None if (mirror := data.get('mirror')) == "None" else mirror
            password = data["password"]

            rapid = [ln for ln in links if "rapidgator" in ln[1].lower()]
            others = [ln for ln in links if "rapidgator" not in ln[1].lower()]
            prioritized_links = rapid + others

            return {
                "to_decrypt": {
                    "name": title,
                    "id": package_id,
                    "url": prioritized_links,
                    "mirror": mirror,
                    "password": password,
                    "max_attempts": 3
                }
            }
        except Exception as e:
            return abort(500, str(e))

    @app.post("/sponsors_helper/api/to_download/")
    def to_download_api():
        try:
            data = request.json
            title = data.get('name')
            package_id = data.get('package_id')
            download_links = data.get('urls')
            password = data.get('password')

            info(f"Received {len(download_links)} download links for {title}")

            if download_links:
                downloaded = shared_state.download_package(download_links, title, password, package_id)
                if downloaded:
                    StatsHelper(shared_state).increment_package_with_links(download_links)
                    StatsHelper(shared_state).increment_captcha_decryptions_automatic()
                    shared_state.get_db("protected").delete(package_id)
                    send_discord_message(shared_state, title=title, case="solved")
                    info(f"Download successfully started for {title}")
                    return f"Downloaded {len(download_links)} download links for {title}"
                else:
                    info(f"Download failed for {title}")

        except Exception as e:
            info(f"Error decrypting: {e}")

        StatsHelper(shared_state).increment_failed_decryptions_automatic()
        return abort(500, "Failed")  #

    @app.post("/sponsors_helper/api/to_replace/")
    def to_replace_api():
        try:
            data = request.json
            name = data.get('name')
            package_id = data.get('package_id')
            password = data.get('password')
            replace_url = data.get('replace_url')
            mirror = data.get('mirror')
            session = data.get('session')

            if not all([name, package_id, replace_url, mirror, session]):
                info("Missing required replacement data")
                return {"error": "Missing required replacement data"}, 400

            if password is None:
                password = ""

            blob = json.dumps(
                {
                    "title": name,
                    "links": [replace_url, mirror],
                    "size_mb": 0,
                    "password": password,
                    "mirror": mirror,
                    "session": session
                })

            shared_state.get_db("protected").update_store(package_id, blob)

            info(f"Another CAPTCHA solution is required for {mirror} link: {replace_url}")

            StatsHelper(shared_state).increment_captcha_decryptions_automatic()

            return f"Replacement link stored for {name}"

        except Exception as e:
            StatsHelper(shared_state).increment_failed_decryptions_automatic()
            info(f"Error handling replacement: {e}")
            return {"error": str(e)}, 500

    @app.delete("/sponsors_helper/api/to_failed/")
    def move_to_failed_api():
        try:
            StatsHelper(shared_state).increment_failed_decryptions_automatic()

            data = request.json
            package_id = data.get('package_id')

            data = json.loads(shared_state.get_db("protected").retrieve(package_id))
            title = data.get('title')

            if package_id:
                info(f'Marking package "{title}" with ID "{package_id}" as failed')
                failed = fail(title, package_id, shared_state, reason="Too many failed attempts by SponsorsHelper")
                if failed:
                    shared_state.get_db("protected").delete(package_id)
                    send_discord_message(shared_state, title=title, case="failed")
                    return f'Package "{title}" with ID "{package_id} marked as failed!"'
        except Exception as e:
            info(f"Error moving to failed: {e}")

        return abort(500, "Failed")

    @app.put("/sponsors_helper/api/set_sponsor_status/")
    def activate_sponsor_status():
        try:
            data = request.body.read().decode("utf-8")
            payload = json.loads(data)
            if payload["activate"]:
                shared_state.update("helper_active", True)
                info(f"Sponsor status activated successfully")
                return "Sponsor status activated successfully!"
        except:
            pass
        return abort(500, "Failed")
