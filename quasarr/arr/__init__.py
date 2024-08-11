# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

from base64 import urlsafe_b64decode
from xml.etree import ElementTree as ET

from bottle import Bottle, request, redirect

from quasarr.downloads import download_package, delete_package, get_packages
from quasarr.providers import shared_state
from quasarr.providers.html_templates import render_centered_html
from quasarr.providers.web_server import Server
from quasarr.search import get_search_results


def api(shared_state_dict, shared_state_lock):
    shared_state.set_state(shared_state_dict, shared_state_lock)

    app = Bottle()

    @app.get('/')
    def index():
        info = f"""
        <h1>Quasarr</h1>
        <p>
            <code id="current-url" style="background-color: #f0f0f0; padding: 5px; border-radius: 3px;">
                {shared_state.values["external_address"]}
            </code>
        </p>
        <p>Use this exact URL as 'Newznab Indexer' and 'SABnzbd Download Client' in Sonarr/Radarr. 
        Leave settings at default and use this API key: 'quasarr'</p>
        """
        return render_centered_html(info)

    @app.get('/download/')
    def fake_download_container():
        payload = request.query.payload
        decoded_payload = urlsafe_b64decode(payload).decode("utf-8").split("|")
        title = decoded_payload[0]
        url = decoded_payload[1]

        request_from = request.headers.get('User-Agent')
        if request_from:
            if not any(arr_client in request_from for arr_client in ["Radarr", "Sonarr"]):
                redirect(url, 302)

        return f'<nzb><file title="{title}" url="{url}"/></nzb>'

    @app.post('/api')
    def download():
        downloads = request.files.getall('name')
        nzo_ids = []
        for upload in downloads:
            file_content = upload.file.read()
            root = ET.fromstring(file_content)
            title = root.find(".//file").attrib["title"]
            url = root.find(".//file").attrib["url"]
            print(f"Attempting download for {title}")

            nzo_id = download_package(shared_state, title, url)
            if nzo_id:
                print(f"Download started for {title}")
                nzo_ids.append(nzo_id)
            else:
                print(f"Download failed for {title}")

        return {
            "status": True,
            "nzo_ids": nzo_ids
        }

    @app.get('/api')
    def fake_api():
        api_type = 'sabnzbd' if request.query.mode and request.query.apikey else 'newznab' if request.query.t else None

        if api_type == 'sabnzbd':
            try:
                mode = request.query.mode
                if mode == "version":
                    return {
                        "version": "4.3.2"
                    }
                elif mode == "get_config":
                    return {
                        "config": {
                            "misc": {
                                "quasarr": True,
                                "complete_dir": "/tmp/"
                            },
                            "categories": [
                                {
                                    "name": "*",
                                    "order": 0,
                                    "dir": "",
                                },
                                {
                                    "name": "movies",
                                    "order": 1,
                                    "dir": "",
                                },
                                {
                                    "name": "tv",
                                    "order": 2,
                                    "dir": "",
                                }
                            ]
                        }
                    }
                elif mode == "fullstatus":
                    return {
                        "status": {
                            "quasarr": True
                        }
                    }
                elif mode == "queue" or mode == "history":
                    if request.query.name and request.query.name == "delete":
                        package_id = request.query.value
                        deleted = delete_package(shared_state, package_id)
                        print(f"Package {package_id} deleted {"successfully" if deleted else "unsuccessfully"}")
                        return {
                            "status": deleted,
                            "nzo_ids": [package_id]
                        }

                    packages = get_packages(shared_state)
                    if mode == "queue":
                        return {
                            "queue": {
                                "paused": False,
                                "slots": packages["queue"]
                            }
                        }
                    elif mode == "history":
                        return {
                            "history": {
                                "paused": False,
                                "slots": packages["history"]
                            }
                        }
            except Exception as e:
                print(f"Error: {e}")
            return {
                "status": False
            }

        elif api_type == 'newznab':
            try:
                mode = request.query.t
                if mode == 'movie':
                    if request.query.imdbid:
                        imdb_id = f"tt{request.query.imdbid}"
                    else:
                        imdb_id = None

                    request_from = request.headers.get('User-Agent')

                    releases = get_search_results(shared_state, request_from, imdb_id=imdb_id)

                    items = ""

                    for release in releases:
                        release = release["details"]

                        items += f'''
                        <item>
                            <title>{release["title"]}</title>
                            <guid isPermaLink="True">{release["link"]}</guid>
                            <link>{release["link"]}</link>
                            <comments>{release["link"]}</comments>
                            <pubDate>{release["date"]}</pubDate>
                            <enclosure url="{release["link"]}" length="{release["size"]}" type="application/x-nzb" />
                        </item>'''

                    return f'''<?xml version="1.0" encoding="UTF-8"?>
                                <rss version="2.0">
                                    <channel>
                                        {items}
                                    </channel>
                                </rss>'''
                elif mode == 'caps':
                    return '''<?xml version="1.0" encoding="UTF-8"?>
                    <caps>
                      <categories>
                          <category id="2000" name="Movies">
                              <subcat id="2010" name="Foreign"/>
                              <subcat id="2020" name="Other"/>
                              <subcat id="2030" name="SD"/>
                              <subcat id="2040" name="HD"/>
                              <subcat id="2050" name="BluRay"/>
                              <subcat id="2060" name="3D"/>
                          </category>
                          <category id="5000" name="TV">
                              <subcat id="5020" name="Foreign"/>
                              <subcat id="5030" name="SD"/>
                              <subcat id="5040" name="HD"/>
                              <subcat id="5050" name="Other"/>
                              <subcat id="5060" name="Sport"/>
                          </category>
                      </categories>
                    </caps>'''
            except Exception as e:
                print(f"Error: {e}")
            return {"error": True}

    Server(app, listen='0.0.0.0', port=shared_state.values["port"]).serve_forever()
