# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import json

from bottle import request, abort

from quasarr.downloads import delete_package
from quasarr.providers import shared_state
from quasarr.providers.log import info
from quasarr.providers.notifications import send_discord_message


def setup_sponsors_helper_routes(app):
    @app.get("/sponsors_helper/api/to_decrypt/")
    def to_decrypt_api():
        try:
            protected = shared_state.get_db("protected").retrieve_all_titles()
            if not protected:
                return abort(404, "No encrypted packages found")
            else:
                package = protected[0]
                package_id = package[0]
                data = json.loads(package[1])
                title = data["title"]
                links = data["links"]
                password = data["password"]

            return {
                "to_decrypt": {
                    "name": title,
                    "id": package_id,
                    "url": links,
                    "password": password,
                    "max_attempts": 3
                }
            }
        except:
            return abort(500, "Failed")

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
                    shared_state.get_db("protected").delete(package_id)
                    send_discord_message(shared_state, title=title, case="solved")
                    info(f"Download successfully started for {title}")
                    return f"Downloaded {len(download_links)} download links for {title}"
                else:
                    info(f"Download failed for {title}")

        except Exception as e:
            info(f"Error decrypting: {e}")

        return abort(500, "Failed")

    @app.delete("/sponsors_helper/api/to_delete/")
    def to_delete_api():
        try:
            data = request.json
            package_id = data.get('package_id')
            deleted = delete_package(shared_state, package_id)
            if deleted:
                send_discord_message(shared_state, title=deleted, case="deleted")
                return f'Deleted package "{deleted}" with ID "{package_id}"'

        except Exception as e:
            info(f"Error deleting: {e}")

        return abort(500, "Failed")

    @app.put("/sponsors_helper/api/activate_sponsor_status/")
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
