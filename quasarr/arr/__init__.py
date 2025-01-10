# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import json
import re
import traceback
import xml.sax.saxutils as sax_utils
from base64 import urlsafe_b64decode
from datetime import datetime
from xml.etree import ElementTree as element_tree

import requests
from bottle import Bottle, request, response, abort

from quasarr.captcha_solver import get_filecrypt_links
from quasarr.downloads import download_package, delete_package, get_packages
from quasarr.providers import shared_state
from quasarr.providers.html_templates import render_button, render_centered_html
from quasarr.providers.notifications import send_discord_message
from quasarr.providers.obfuscated import captcha_js, captcha_values
from quasarr.providers.tvmaze_metadata import get_title_from_tvrage_id
from quasarr.providers.web_server import Server
from quasarr.search import get_search_results


def api(shared_state_dict, shared_state_lock):
    shared_state.set_state(shared_state_dict, shared_state_lock)

    app = Bottle()

    @app.get('/captcha')
    def serve_captcha():
        try:
            device = shared_state.values["device"]
        except KeyError:
            device = None
        if not device:
            return render_centered_html(f'''<h1>Quasarr</h1>
            <p>JDownloader connection not established.</p>''')

        protected = shared_state.get_db("protected").retrieve_all_titles()
        if not protected:
            return render_centered_html(f'''<h1>Quasarr</h1>
            <p>No protected packages found! CAPTCHA not needed.</p>''')
        else:
            package = protected[0]
            package_id = package[0]
            data = json.loads(package[1])
            title = data["title"]
            links = data["links"]
            password = data["password"]

        link_options = ""
        if len(links) > 1:
            for link in links:
                if "filecrypt." in link[0]:
                    link_options += f'<option value="{link[0]}">{link[1]}</option>'
            link_select = f'''<div id="mirrors-select">
                    <label for="link-select">Mirror:</label>
                    <select id="link-select">
                        {link_options}
                    </select>
                </div>
                <script>
                    document.getElementById("link-select").addEventListener("change", function() {{
                        var selectedLink = this.value;
                        document.getElementById("link-hidden").value = selectedLink;
                    }});
                </script>
            '''
        else:
            link_select = f'<div id="mirrors-select">Mirror: <b>{links[0][1]}</b></div>'

        content = render_centered_html(r'''
            <script type="text/javascript">
                var api_key = "''' + captcha_values()["api_key"] + r'''";
                var endpoint = '/' + window.location.pathname.split('/')[1] + '/' + api_key + '.html';
                function handleToken(token) {
                    document.getElementById("puzzle-captcha").remove();
                    document.getElementById("mirrors-select").remove();
                    document.getElementById("captcha-key").innerText = 'Using result "' + token + '" to decrypt links...';
                    var link = document.getElementById("link-hidden").value;
                    const currentPath = window.location.pathname;
                    const endpoint = '/decrypt-filecrypt';
                    const fullPath = currentPath.endsWith('/') ? currentPath + endpoint.slice(1) : currentPath + endpoint;

                    fetch(fullPath, {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                        },
                        body: JSON.stringify({ 
                            token: token,
                            ''' + f'''package_id: '{package_id}',
                            title: '{title}',
                            link: link,
                            password: '{password}'
                        ''' + '''})
                    })
                    .then(response => response.json())
                    .then(data => {
                        if (data.success) {
                            document.getElementById("captcha-key").insertAdjacentHTML('afterend', 
                                '<p>Successful for: ' + data.title + '</p>');
                        } else {
                            document.getElementById("captcha-key").insertAdjacentHTML('afterend', 
                                '<p>Failed. Check console for details!</p>');
                        }
                        document.getElementById("reload-button").style.display = "block";
                    });
                }
                ''' + captcha_js() + f'''</script>
                <div>
                    <h1>Quasarr</h1>
                    <div id="captcha-key"></div>
                    {link_select}<br><br>
                    <input type="hidden" id="link-hidden" value="{links[0][0]}" />
                    <div id="puzzle-captcha" aria-style="mobile">
                        <strong>Your adblocker prevents the captcha from loading. Disable it!</strong>
                    </div>
                    <div id="reload-button" style="display: none;">
                    {render_button("Solve another CAPTCHA", "secondary", {
            "onclick": "location.reload()",
        })}</div>
                </div>
                </html>''')

        return content

    @app.post('/captcha/decrypt-filecrypt')
    def submit_token():
        protected = shared_state.get_db("protected").retrieve_all_titles()
        if not protected:
            return {"success": False, "title": "No protected packages found! CAPTCHA not needed."}

        download_links = []

        try:
            data = request.json
            token = data.get('token')
            package_id = data.get('package_id')
            title = data.get('title')
            link = data.get('link')
            password = data.get('password')
            if token:
                print(f"Received token: {token}")
                print(f"Decrypting links for {title}")
                download_links = get_filecrypt_links(shared_state, token, title, link, password)

                print(f"Decrypted {len(download_links)} download links for {title}")

                shared_state.download_package(download_links, title, password, package_id)

                shared_state.get_db("protected").delete(package_id)

        except Exception as e:
            print(f"Error decrypting: {e}")

        return {"success": bool(download_links), "title": title}

    @app.post('/captcha/<captcha_id>.html')
    def proxy(captcha_id):
        target_url = f"{captcha_values()["url"]}/captcha/{captcha_id}.html"

        headers = {key: value for key, value in request.headers.items() if key != 'Host'}
        data = request.body.read()
        resp = requests.post(target_url, headers=headers, data=data)

        response.content_type = resp.headers.get('Content-Type')

        content = resp.text
        content = re.sub(r'<script src="/(.*?)"></script>',
                         f'<script src="{captcha_values()["url"]}/\\1"></script>', content)
        response.content_type = 'text/html'
        return content

    @app.post('/captcha/<captcha_id>.json')
    def specific_proxy(captcha_id):
        target_url = f"{captcha_values()["url"]}/captcha/{captcha_id}.json"

        headers = {key: value for key, value in request.headers.items() if key != 'Host'}
        data = request.body.read()
        resp = requests.post(target_url, headers=headers, data=data)

        response.content_type = resp.headers.get('Content-Type')
        return resp.content

    @app.get('/captcha/<captcha_id>/<uuid>/<filename>')
    def captcha_proxy(captcha_id, uuid, filename):
        new_url = f"{captcha_values()["url"]}/captcha/{captcha_id}/{uuid}/{filename}"

        try:
            external_response = requests.get(new_url, stream=True)
            external_response.raise_for_status()
            response.content_type = 'image/png'
            response.headers['Content-Disposition'] = f'inline; filename="{filename}"'
            return external_response.iter_content(chunk_size=8192)

        except requests.RequestException as e:
            response.status = 502
            return f"Error fetching resource: {e}"

    @app.post('/captcha/<captcha_id>/check')
    def captcha_check_proxy(captcha_id):
        new_url = f"{captcha_values()["url"]}/captcha/{captcha_id}/check"
        headers = {key: value for key, value in request.headers.items()}

        data = request.body.read()
        resp = requests.post(new_url, headers=headers, data=data)

        response.status = resp.status_code
        for header in resp.headers:
            if header.lower() not in ['content-encoding', 'transfer-encoding', 'content-length', 'connection']:
                response.set_header(header, resp.headers[header])
        return resp.content

    @app.get('/')
    def index():
        protected = shared_state.get_db("protected").retrieve_all_titles()
        captcha_hint = ""
        if protected:
            package_count = len(protected)
            package_text = f"Package{'s' if package_count > 1 else ''} waiting for CAPTCHA"
            amount_info = f": {package_count}" if package_count > 1 else ""
            button_text = f"Solve CAPTCHA{'s' if package_count > 1 else ''} here to decrypt links!"

            captcha_hint = f'''
            <h2>Links protected by CAPTCHA</h2>
            <p>{package_text}{amount_info}</p>
            <p>{render_button(button_text, "primary", {"onclick": "location.href='/captcha'"})}</p>
            '''

        info = f"""
        <h1>Quasarr</h1>
        <p>
            <code id="current-url" style="background-color: #f0f0f0; padding: 5px; border-radius: 3px;">
                {shared_state.values["internal_address"]}
            </code>
        </p>
        <p>Use this exact URL as 'Newznab Indexer' and 'SABnzbd Download Client' in Sonarr/Radarr.<br>
        Leave settings at default and use this API key: 'quasarr'</p>
        {captcha_hint}
        """
        return render_centered_html(info)

    @app.get('/download/')
    def fake_download_container():
        payload = request.query.payload
        decoded_payload = urlsafe_b64decode(payload).decode("utf-8").split("|")
        title = decoded_payload[0]
        url = decoded_payload[1]
        size_mb = decoded_payload[2]
        password = decoded_payload[3]
        return f'<nzb><file title="{title}" url="{url}" size_mb="{size_mb}" password="{password}"/></nzb>'

    @app.post('/api')
    def download():
        downloads = request.files.getall('name')
        nzo_ids = []
        for upload in downloads:
            file_content = upload.file.read()
            root = element_tree.fromstring(file_content)
            title = root.find(".//file").attrib["title"]
            url = root.find(".//file").attrib["url"]
            size_mb = root.find(".//file").attrib["size_mb"]
            password = root.find(".//file").attrib.get("password")
            print(f"Attempting download for {title}")

            request_from = request.headers.get('User-Agent')

            nzo_id = download_package(shared_state, request_from, title, url, size_mb, password)
            if nzo_id:
                print(f"{title} added successfully!")
                nzo_ids.append(nzo_id)
            else:
                print(f"{title} could not be added!")

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
                print(f"Error loading packages: {e}")
                print(traceback.format_exc())
            return {
                "status": False
            }

        elif api_type == 'newznab':
            try:
                mode = request.query.t
                if mode == 'caps':
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
                elif mode in ['movie', 'tvsearch']:
                    request_from = request.headers.get('User-Agent')

                    releases = []

                    if mode == 'movie':
                        # only imdb is implemented
                        search_param = f"tt{getattr(request.query, 'imdbid', '')}" \
                            if getattr(request.query, 'imdbid', '') else ""

                        releases = get_search_results(shared_state, request_from, search_string=search_param)

                    elif mode == 'tvsearch':
                        season = getattr(request.query, 'season', "")
                        episode = getattr(request.query, 'ep', "")
                        # only plain search string and tvrage id is implemented
                        search_param = getattr(request.query, 'q', "")
                        if not search_param:
                            tvrage_id = getattr(request.query, 'rid', "")
                            if tvrage_id:
                                search_param = get_title_from_tvrage_id(tvrage_id)

                        offset = getattr(request.query, 'offset', "")  # ignoring offset higher than 0 on purpose
                        if int(offset) == 0:
                            releases = get_search_results(shared_state, request_from,
                                                          search_string=search_param,
                                                          season=season,
                                                          episode=episode
                                                          )

                    items = ""
                    if not releases:
                        items += f'''
                            <item>
                                <title>No releases found</title>
                                <link></link>
                                <pubDate>{datetime.now().strftime('%a, %d %b %Y %H:%M:%S %z')}</pubDate>
                                <enclosure url="_" length="0" type="application/x-nzb"/>
                                <guid></guid>
                                <comments></comments>
                                <description></description>
                            </item>'''

                    for release in releases:
                        release = release["details"]
                        items += f'''
                        <item>
                            <title>{sax_utils.escape(release["title"])}</title>
                            <guid isPermaLink="True">{release["link"]}</guid>
                            <link>{release["link"]}</link>
                            <comments>{release["source"]}</comments>
                            <pubDate>{release["date"]}</pubDate>
                            <enclosure url="{release["link"]}" length="{release["size"]}" type="application/x-nzb" />
                        </item>'''

                    return f'''<?xml version="1.0" encoding="UTF-8"?>
                                <rss version="2.0">
                                    <channel>
                                        {items}
                                    </channel>
                                </rss>'''
            except Exception as e:
                print(f"Error loading search results: {e}")
                print(traceback.format_exc())

            print(f"Unknown request: {request.query}")
            return {"error": True}

    @app.get("/sponsors_helper/api/to_decrypt/")
    def to_decrypt_api():
        global helper_active
        try:
            helper_active = True

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

            print(f"Received {len(download_links)} download links for {title}")

            if download_links:
                downloaded = shared_state.download_package(download_links, title, password, package_id)
                if downloaded:
                    shared_state.get_db("protected").delete(package_id)
                    send_discord_message(shared_state, title=title, case="solved")
                    print(f"Download successfully started for {title}")
                    return f"Downloaded {len(download_links)} download links for {title}"
                else:
                    print(f"Download failed for {title}")

        except Exception as e:
            print(f"Error decrypting: {e}")

        return abort(500, "Failed")

    @app.delete("/sponsors_helper/api/to_delete/")
    def to_delete_api():
        try:
            data = request.json
            package_id = data.get('package_id')
            deleted = delete_package(shared_state, package_id)
            if deleted:
                send_discord_message(shared_state, title=deleted, case="deleted")
                return f"Deleted package {deleted} with id {package_id}"

        except Exception as e:
            print(f"Error deleting: {e}")

        return abort(500, "Failed")

    @app.put("/sponsors_helper/api/activate_sponsor_status/")
    def activate_sponsor_status():
        try:
            data = request.body.read().decode("utf-8")
            payload = json.loads(data)
            if payload["activate"]:
                shared_state.update("helper_active", True)
                print(f"Sponsor status activated successfully")
                return "Sponsor status activated successfully!"
        except:
            pass
        return abort(500, "Failed")

    Server(app, listen='0.0.0.0', port=shared_state.values["port"]).serve_forever()
