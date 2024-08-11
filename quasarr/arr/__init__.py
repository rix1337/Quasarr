# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import re
import traceback
from base64 import urlsafe_b64decode
from xml.etree import ElementTree as ET

import requests
from bottle import Bottle, request, response

from quasarr.captcha_solver import get_filecrypt_links
from quasarr.downloads import download_package, delete_package, get_packages
from quasarr.providers import shared_state
from quasarr.providers.html_templates import render_button, render_centered_html
from quasarr.providers.obfuscated import captcha_js, captcha_values
from quasarr.providers.web_server import Server
from quasarr.search import get_search_results


def api(shared_state_dict, shared_state_lock):
    shared_state.set_state(shared_state_dict, shared_state_lock)

    app = Bottle()

    @app.route('/captcha')
    def serve_captcha():
        protected = shared_state.get_db("protected").retrieve_all_titles()
        if not protected:
            return render_centered_html('<h1>Quasarr</h1><p>No protected packages found! CAPTCHA not needed.</p>')
        content = render_centered_html(r'''
            <script type="text/javascript">
                var api_key = "''' + captcha_values()["api_key"] + r'''";
                var endpoint = '/captcha/' + api_key + '.html';
                function handleToken(token) {
                    document.getElementById("puzzle-captcha").remove();
                    document.getElementById("captcha-key").innerText = 'Using result "' + token + '" to decrypt links...';
                    fetch('/decrypt-filecrypt', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                        },
                        body: JSON.stringify({ token: token })
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
                    <div id="puzzle-captcha" aria-style="mobile">
                        <strong>Your adblocker prevents the captcha from loading. Disable it!</strong>
                    </div>
        
                    <div id="captcha-key"></div>
                    <div id="reload-button" style="display: none;">
                    {render_button("Solve another CAPTCHA", "secondary", {
            "onclick": "location.reload()",
        })}</div>
        
                </div>
                </html>''')

        return content

    @app.post('/decrypt-filecrypt')
    def submit_token():
        protected = shared_state.get_db("protected").retrieve_all_titles()
        if not protected:
            return {"success": False, "title": "No protected packages found! CAPTCHA not needed."}
        else:
            first_protected = protected[0]
            package_id = first_protected[0]
            details = first_protected[1].split("|")
            title = details[0]
            link = details[1]
            password = details[3]

        links = []

        try:
            data = request.json
            token = data.get('token')
            if token:
                print(f"Received token: {token}")
                print(f"Decrypting links for {title}")
                links = get_filecrypt_links(shared_state, token, title, link, password)

                print(f"Decrypted {len(links)} download links for {title}")

                shared_state.get_device().linkgrabber.add_links(params=[
                    {
                        "autostart": True,
                        "links": str(links).replace(" ", ""),
                        "packageName": title,
                        "extractPassword": password,
                        "priority": "DEFAULT",
                        "downloadPassword": password,
                        "destinationFolder": "Quasarr/<jd:packagename>",
                        "comment": package_id,
                        "overwritePackagizerRules": True
                    }
                ])

                shared_state.get_db("protected").delete(package_id)

        except Exception as e:
            print(f"Error decrypting: {e}")

        return {"success": bool(links), "title": title}

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
            root = ET.fromstring(file_content)
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
                print(f"Error loading search results: {e}")
                print(traceback.format_exc())
            return {"error": True}

    Server(app, listen='0.0.0.0', port=shared_state.values["port"]).serve_forever()
