# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import json
import re

import requests
from bottle import request, response

from quasarr.downloads.linkcrypters.filecrypt import get_filecrypt_links
from quasarr.providers import shared_state
from quasarr.providers.html_templates import render_button, render_centered_html
from quasarr.providers.log import info
from quasarr.providers.obfuscated import captcha_js, captcha_values


def setup_captcha_routes(app):
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
            <p>No protected packages found! CAPTCHA not needed.</p>
            <p>
                {render_button("Confirm", "secondary", {"onclick": "location.href='/'"})}
            </p>''')
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
                    <p>
                    {render_button("Solve another CAPTCHA", "secondary", {
            "onclick": "location.reload()",
        })}</p>
        </div>
                </div>
                </html>''')

        return content

    @app.post('/captcha/<captcha_id>.html')
    def proxy_html(captcha_id):
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
    def proxy_json(captcha_id):
        target_url = f"{captcha_values()["url"]}/captcha/{captcha_id}.json"

        headers = {key: value for key, value in request.headers.items() if key != 'Host'}
        data = request.body.read()
        resp = requests.post(target_url, headers=headers, data=data)

        response.content_type = resp.headers.get('Content-Type')
        return resp.content

    @app.get('/captcha/<captcha_id>/<uuid>/<filename>')
    def proxy_pngs(captcha_id, uuid, filename):
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
    def proxy_check(captcha_id):
        new_url = f"{captcha_values()["url"]}/captcha/{captcha_id}/check"
        headers = {key: value for key, value in request.headers.items()}

        data = request.body.read()
        resp = requests.post(new_url, headers=headers, data=data)

        response.status = resp.status_code
        for header in resp.headers:
            if header.lower() not in ['content-encoding', 'transfer-encoding', 'content-length', 'connection']:
                response.set_header(header, resp.headers[header])
        return resp.content

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
                info(f"Received token: {token}")
                info(f"Decrypting links for {title}")
                download_links = get_filecrypt_links(shared_state, token, title, link, password)

                info(f"Decrypted {len(download_links)} download links for {title}")

                if download_links:
                    downloaded = shared_state.download_package(download_links, title, password, package_id)
                    if downloaded:
                        shared_state.get_db("protected").delete(package_id)
                    else:
                        raise RuntimeError("Submitting Download to JDownloader failed")
                else:
                    raise ValueError("No download links found")

        except Exception as e:
            info(f"Error decrypting: {e}")

        return {"success": bool(download_links), "title": title}
