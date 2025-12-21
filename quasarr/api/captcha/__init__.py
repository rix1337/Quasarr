# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import json
import re
from base64 import urlsafe_b64encode, urlsafe_b64decode
from urllib.parse import quote, unquote, urljoin

import requests
from bottle import request, response, redirect

import quasarr.providers.html_images as images
from quasarr.downloads.linkcrypters.filecrypt import get_filecrypt_links, DLC
from quasarr.downloads.packages import delete_package
from quasarr.providers import shared_state
from quasarr.providers.html_templates import render_button, render_centered_html
from quasarr.providers.log import info, debug
from quasarr.providers.obfuscated import captcha_js, captcha_values, filecrypt_user_js, junkies_user_js
from quasarr.providers.statistics import StatsHelper


def js_single_quoted_string_safe(text):
    return text.replace('\\', '\\\\').replace("'", "\\'")


def setup_captcha_routes(app):
    @app.get('/captcha')
    def check_captcha():
        try:
            device = shared_state.values["device"]
        except KeyError:
            device = None
        if not device:
            return render_centered_html(f'''<h1><img src="{images.logo}" type="image/png" alt="Quasarr logo" class="logo"/>Quasarr</h1>
            <p>JDownloader connection not established.</p>
            <p>
                {render_button("Back", "secondary", {"onclick": "location.href='/'"})}
            </p>''')

        protected = shared_state.get_db("protected").retrieve_all_titles()
        if not protected:
            return render_centered_html(f'''<h1><img src="{images.logo}" type="image/png" alt="Quasarr logo" class="logo"/>Quasarr</h1>
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
            try:
                desired_mirror = data["mirror"]
            except KeyError:
                desired_mirror = None

            # This is set for circle CAPTCHAs
            filecrypt_session = data.get("session", None)

            # This is required for cutcaptcha
            rapid = [ln for ln in links if "rapidgator" in ln[1].lower()]
            others = [ln for ln in links if "rapidgator" not in ln[1].lower()]
            prioritized_links = rapid + others

            # This is required for bypass on circlecaptcha
            original_url = data.get("original_url", "")

            payload = {
                "package_id": package_id,
                "title": title,
                "password": password,
                "mirror": desired_mirror,
                "session": filecrypt_session,
                "links": prioritized_links,
                "original_url": original_url
            }

            encoded_payload = urlsafe_b64encode(json.dumps(payload).encode()).decode()

            sj = shared_state.values["config"]("Hostnames").get("sj")
            dj = shared_state.values["config"]("Hostnames").get("dj")
            has_junkies_links = any(
                (sj and sj in link) or (dj and dj in link)
                for link in prioritized_links
            )

            if has_junkies_links:
                debug("Redirecting to Junkies CAPTCHA")
                redirect(f"/captcha/junkies?data={quote(encoded_payload)}")
            elif filecrypt_session:
                debug(f'Redirecting to circle CAPTCHA')
                redirect(f"/captcha/circle?data={quote(encoded_payload)}")
            else:
                debug(f"Redirecting to cutcaptcha")
                redirect(f"/captcha/cutcaptcha?data={quote(encoded_payload)}")

            return render_centered_html(f'''<h1><img src="{images.logo}" type="image/png" alt="Quasarr logo" class="logo"/>Quasarr</h1>
            <p>Unexpected Error!</p>
            <p>
                {render_button("Back", "secondary", {"onclick": "location.href='/'"})}
            </p>''')

    def decode_payload():
        encoded = request.query.get('data')
        try:
            decoded = urlsafe_b64decode(unquote(encoded)).decode()
            return json.loads(decoded)
        except Exception as e:
            return {"error": f"Failed to decode payload: {str(e)}"}

    @app.get("/captcha/junkies")
    def serve_junkies_captcha():
        payload = decode_payload()

        if "error" in payload:
            return render_centered_html(f'''<h1><img src="{images.logo}" type="image/png" alt="Quasarr logo" class="logo"/>Quasarr</h1>
            <p>{payload["error"]}</p>
            <p>
                {render_button("Back", "secondary", {"onclick": "location.href='/'"})}
            </p>''')

        package_id = payload.get("package_id")
        title = payload.get("title")
        password = payload.get("password")
        urls = payload.get("links")
        url = urls[0]

        return render_centered_html(f"""
        <!DOCTYPE html>
        <html>
          <body>
            <h1><img src="{images.logo}" type="image/png" alt="Quasarr logo" class="logo"/>Quasarr</h1>
            <p><b>Package:</b> {title}</p>
                {render_junkies_section(url, package_id, title, password)}
            <p>
                {render_button("Delete Package", "secondary", {"onclick": f"location.href='/captcha/delete/{package_id}'"})}
            </p>
            <p>
                {render_button("Back", "secondary", {"onclick": "location.href='/'"})}
            </p>
            
          </body>
        </html>""")

    def render_junkies_section(url, package_id, title, password):
        """Render the UI section for SJ and DJ pages"""

        # Generate userscript URL with transfer params
        # Get base URL of current request
        base_url = request.urlparts.scheme + '://' + request.urlparts.netloc
        transfer_url = f"{base_url}/captcha/quick-transfer"

        url_with_quick_transfer_params = (
            f"{url}?"
            f"transfer_url={quote(transfer_url)}&"
            f"pkg_id={quote(package_id)}&"
            f"pkg_title={quote(title)}&"
            f"pkg_pass={quote(password)}"
        )

        return f'''
            <div>
                <!-- One-time setup section - visually separated -->
                <div id="setup-instructions" style="background: #2a2a2a; border: 2px solid #444; border-radius: 8px; padding: 16px; margin-bottom: 24px;">
                    <h3 style="margin-top: 0; color: #58a6ff;">First Time Setup:</h3>
                    <p style="margin-bottom: 8px;">
                        <a href="https://www.tampermonkey.net/" target="_blank" rel="noopener noreferrer">1. Install Tampermonkey</a>
                    </p>
                    <p style="margin-top: 0; margin-bottom: 12px;">
                        <a href="/captcha/junkies.user.js" target="_blank">2. Install this userscript</a>
                    </p>
                    <p style="margin-top: 0;">
                        <button id="hide-setup-btn" type="button" style="background: #444; color: #fff; border: 1px solid #666; padding: 6px 12px; border-radius: 4px; cursor: pointer;">
                            ✅ Don't show this again
                        </button>
                    </p>
                </div>

                <!-- Hidden "show instructions" link -->
                <div id="show-instructions-link" style="display: none; margin-bottom: 16px;">
                    <a href="#" id="show-setup-btn" style="color: #58a6ff;">ℹ️ Show instructions again</a>
                </div>

                <strong><a href="{url_with_quick_transfer_params}" target="_blank">🔗 Obtain the download links here!</a></strong><br><br>

                <form id="bypass-form" action="/captcha/bypass-submit" method="post" enctype="multipart/form-data">
                    <input type="hidden" name="package_id" value="{package_id}" />
                    <input type="hidden" name="title" value="{title}" />
                    <input type="hidden" name="password" value="{password}" />

                    <div>
                        <strong>Paste the download links (one per line):</strong>
                        <textarea id="links-input" name="links" rows="5" style="width: 100%; padding: 8px; font-family: monospace; resize: vertical;"></textarea>
                    </div>

                    <div>
                        {render_button("Submit", "primary", {"type": "submit"})}
                    </div>
                </form>
            </div>
            <script>
              // Handle setup instructions hide/show
              const hideSetup = localStorage.getItem('hideJunkiesSetupInstructions');
              const setupBox = document.getElementById('setup-instructions');
              const showLink = document.getElementById('show-instructions-link');

              if (hideSetup === 'true') {{
                setupBox.style.display = 'none';
                showLink.style.display = 'block';
              }}

              // Hide setup instructions
              document.getElementById('hide-setup-btn').addEventListener('click', function() {{
                localStorage.setItem('hideJunkiesSetupInstructions', 'true');
                setupBox.style.display = 'none';
                showLink.style.display = 'block';
              }});

              // Show setup instructions again
              document.getElementById('show-setup-btn').addEventListener('click', function(e) {{
                e.preventDefault();
                localStorage.setItem('hideJunkiesSetupInstructions', 'false');
                setupBox.style.display = 'block';
                showLink.style.display = 'none';
              }});
            </script>
        '''

    @app.get('/captcha/junkies.user.js')
    def serve_junkies_user_js():
        sj = shared_state.values["config"]("Hostnames").get("sj")
        dj = shared_state.values["config"]("Hostnames").get("dj")

        content = junkies_user_js(sj, dj)
        response.content_type = 'application/javascript'
        return content

    @app.get('/captcha/filecrypt.user.js')
    def serve_filecrypt_user_js():
        content = filecrypt_user_js()
        response.content_type = 'application/javascript'
        return content

    def render_filecrypt_bypass_section(url, package_id, title, password):
        """Render the bypass UI section for both cutcaptcha and circle captcha pages"""

        # Generate userscript URL with transfer params
        # Get base URL of current request
        base_url = request.urlparts.scheme + '://' + request.urlparts.netloc
        transfer_url = f"{base_url}/captcha/quick-transfer"

        url_with_quick_transfer_params = (
            f"{url}?"
            f"transfer_url={quote(transfer_url)}&"
            f"pkg_id={quote(package_id)}&"
            f"pkg_title={quote(title)}&"
            f"pkg_pass={quote(password)}"
        )

        return f'''
            <div style="margin-top: 40px; padding-top: 20px; border-top: 2px solid #ccc;">
                <details id="bypassDetails">
                <summary id="bypassSummary">Show CAPTCHA Bypass</summary><br>

                    <!-- One-time setup section - visually separated -->
                    <div id="setup-instructions" style="background: #2a2a2a; border: 2px solid #444; border-radius: 8px; padding: 16px; margin-bottom: 24px;">
                        <h3 style="margin-top: 0; color: #58a6ff;">First Time Setup:</h3>
                        <p style="margin-bottom: 8px;">
                            <a href="https://www.tampermonkey.net/" target="_blank" rel="noopener noreferrer">1. Install Tampermonkey</a>
                        </p>
                        <p style="margin-top: 0; margin-bottom: 12px;">
                            <a href="/captcha/filecrypt.user.js" target="_blank">2. Install this userscript</a>
                        </p>
                        <p style="margin-top: 0;">
                            <button id="hide-setup-btn" type="button" style="background: #444; color: #fff; border: 1px solid #666; padding: 6px 12px; border-radius: 4px; cursor: pointer;">
                                ✅ Don't show this again
                            </button>
                        </p>
                    </div>

                    <!-- Hidden "show instructions" link -->
                    <div id="show-instructions-link" style="display: none; margin-bottom: 16px;">
                        <a href="#" id="show-setup-btn" style="color: #58a6ff;">ℹ️ Show instructions again</a>
                    </div>

                    <strong><a href="{url_with_quick_transfer_params}" target="_blank">🔗 Obtain the download links here!</a></strong><br><br>

                    <form id="bypass-form" action="/captcha/bypass-submit" method="post" enctype="multipart/form-data">
                        <input type="hidden" name="package_id" value="{package_id}" />
                        <input type="hidden" name="title" value="{title}" />
                        <input type="hidden" name="password" value="{password}" />

                        <div>
                            <strong>Paste the download links (one per line):</strong>
                            <textarea id="links-input" name="links" rows="5" style="width: 100%; padding: 8px; font-family: monospace; resize: vertical;"></textarea>
                        </div>

                        <div>
                            <strong>Or upload DLC file:</strong><br>
                            <input type="file" id="dlc-file" name="dlc_file" accept=".dlc" />
                        </div>

                        <div>
                            {render_button("Submit", "primary", {"type": "submit"})}
                        </div>
                    </form>
                </details>
            </div>
            <script>
              // Handle CAPTCHA Bypass toggle
              const bypassDetails = document.getElementById('bypassDetails');
              const bypassSummary = document.getElementById('bypassSummary');

              if (bypassDetails && bypassSummary) {{
                bypassDetails.addEventListener('toggle', () => {{
                  if (bypassDetails.open) {{
                    bypassSummary.textContent = 'Hide CAPTCHA Bypass';
                  }} else {{
                    bypassSummary.textContent = 'Show CAPTCHA Bypass';
                  }}
                }});
              }}

              // Handle setup instructions hide/show
              const hideSetup = localStorage.getItem('hideFileCryptSetupInstructions');
              const setupBox = document.getElementById('setup-instructions');
              const showLink = document.getElementById('show-instructions-link');

              if (hideSetup === 'true') {{
                setupBox.style.display = 'none';
                showLink.style.display = 'block';
              }}

              // Hide setup instructions
              document.getElementById('hide-setup-btn').addEventListener('click', function() {{
                localStorage.setItem('hideFileCryptSetupInstructions', 'true');
                setupBox.style.display = 'none';
                showLink.style.display = 'block';
              }});

              // Show setup instructions again
              document.getElementById('show-setup-btn').addEventListener('click', function(e) {{
                e.preventDefault();
                localStorage.setItem('hideFileCryptSetupInstructions', 'false');
                setupBox.style.display = 'block';
                showLink.style.display = 'none';
              }});
            </script>
        '''

    @app.get('/captcha/quick-transfer')
    def handle_quick_transfer():
        """Handle quick transfer from userscript"""
        import zlib

        try:
            package_id = request.query.get('pkg_id')
            compressed_links = request.query.get('links', '')

            if not package_id or not compressed_links:
                return render_centered_html(f'''<h1><img src="{images.logo}" type="image/png" alt="Quasarr logo" class="logo"/>Quasarr</h1>
                <p><b>Error:</b> Missing parameters</p>
                <p>
                    {render_button("Back", "secondary", {"onclick": "location.href='/captcha'"})}
                </p>''')

            # Decode the compressed links using urlsafe_b64decode
            # Add padding if needed
            padding = 4 - (len(compressed_links) % 4)
            if padding != 4:
                compressed_links += '=' * padding

            try:
                decoded = urlsafe_b64decode(compressed_links)
            except Exception as e:
                info(f"Base64 decode error: {e}")
                return render_centered_html(f'''<h1><img src="{images.logo}" type="image/png" alt="Quasarr logo" class="logo"/>Quasarr</h1>
                <p><b>Error:</b> Failed to decode data: {str(e)}</p>
                <p>
                    {render_button("Back", "secondary", {"onclick": "location.href='/captcha'"})}
                </p>''')

            # Decompress using zlib - use raw deflate format (no header)
            try:
                decompressed = zlib.decompress(decoded, -15)  # -15 = raw deflate, no zlib header
            except Exception as e:
                info(f"Decompression error: {e}, trying with header...")
                try:
                    # Fallback: try with zlib header
                    decompressed = zlib.decompress(decoded)
                except Exception as e2:
                    info(f"Decompression also failed with header: {e2}")
                    return render_centered_html(f'''<h1><img src="{images.logo}" type="image/png" alt="Quasarr logo" class="logo"/>Quasarr</h1>
                    <p><b>Error:</b> Failed to decompress data: {str(e)}</p>
                    <p>
                        {render_button("Back", "secondary", {"onclick": "location.href='/captcha'"})}
                    </p>''')

            links_text = decompressed.decode('utf-8')

            # Parse links and restore protocols
            raw_links = [link.strip() for link in links_text.split('\n') if link.strip()]
            links = []
            for link in raw_links:
                if not link.startswith(('http://', 'https://')):
                    link = 'https://' + link
                links.append(link)

            info(f"Quick transfer received {len(links)} links for package {package_id}")

            # Get package info
            raw_data = shared_state.get_db("protected").retrieve(package_id)
            if not raw_data:
                return render_centered_html(f'''<h1><img src="{images.logo}" type="image/png" alt="Quasarr logo" class="logo"/>Quasarr</h1>
                <p><b>Error:</b> Package not found</p>
                <p>
                    {render_button("Back", "secondary", {"onclick": "location.href='/captcha'"})}
                </p>''')

            data = json.loads(raw_data)
            title = data.get("title", "Unknown")
            password = data.get("password", "")

            # Download the package
            downloaded = shared_state.download_package(links, title, password, package_id)

            if downloaded:
                StatsHelper(shared_state).increment_package_with_links(links)
                StatsHelper(shared_state).increment_captcha_decryptions_manual()
                shared_state.get_db("protected").delete(package_id)

                info(f"Quick transfer successful: {len(links)} links processed")

                # Check if more CAPTCHAs remain
                remaining_protected = shared_state.get_db("protected").retrieve_all_titles()
                has_more_captchas = bool(remaining_protected)

                if has_more_captchas:
                    solve_button = render_button("Solve another CAPTCHA", "primary",
                                                 {"onclick": "location.href='/captcha'"})
                else:
                    solve_button = "<b>No more CAPTCHAs</b>"

                return render_centered_html(f'''<h1><img src="{images.logo}" type="image/png" alt="Quasarr logo" class="logo"/>Quasarr</h1>
                <p><b>✅ Quick Transfer Successful!</b></p>
                <p>Package "{title}" with {len(links)} link(s) submitted to JDownloader.</p>
                <p>
                    {solve_button}
                </p>
                <p>
                    {render_button("Back", "secondary", {"onclick": "location.href='/'"})}
                </p>''')
            else:
                StatsHelper(shared_state).increment_failed_decryptions_manual()
                return render_centered_html(f'''<h1><img src="{images.logo}" type="image/png" alt="Quasarr logo" class="logo"/>Quasarr</h1>
                <p><b>Error:</b> Failed to submit package to JDownloader</p>
                <p>
                    {render_button("Try Again", "secondary", {"onclick": "location.href='/captcha'"})}
                </p>''')

        except Exception as e:
            info(f"Quick transfer error: {e}")
            return render_centered_html(f'''<h1><img src="{images.logo}" type="image/png" alt="Quasarr logo" class="logo"/>Quasarr</h1>
            <p><b>Error:</b> {str(e)}</p>
            <p>
                {render_button("Back", "secondary", {"onclick": "location.href='/captcha'"})}
            </p>''')

    @app.get('/captcha/delete/<package_id>')
    def delete_captcha_package(package_id):
        success = delete_package(shared_state, package_id)

        # Check if there are more CAPTCHAs to solve after deletion
        remaining_protected = shared_state.get_db("protected").retrieve_all_titles()
        has_more_captchas = bool(remaining_protected)

        if has_more_captchas:
            solve_button = render_button("Solve another CAPTCHA", "primary", {
                "onclick": "location.href='/captcha'",
            })
        else:
            solve_button = "<b>No more CAPTCHAs</b>"

        if success:
            return render_centered_html(f'''<h1><img src="{images.logo}" type="image/png" alt="Quasarr logo" class="logo"/>Quasarr</h1>
            <p>Package successfully deleted!</p>
            <p>
                {solve_button}
            </p>
            <p>
                {render_button("Back", "secondary", {"onclick": "location.href='/'"})}
            </p>''')
        else:
            return render_centered_html(f'''<h1><img src="{images.logo}" type="image/png" alt="Quasarr logo" class="logo"/>Quasarr</h1>
            <p>Failed to delete package!</p>
            <p>
                {solve_button}
            </p>
            <p>
                {render_button("Back", "secondary", {"onclick": "location.href='/'"})}
            </p>''')

    # The following routes are for cutcaptcha
    @app.get('/captcha/cutcaptcha')
    def serve_cutcaptcha():
        payload = decode_payload()

        if "error" in payload:
            return render_centered_html(f'''<h1><img src="{images.logo}" type="image/png" alt="Quasarr logo" class="logo"/>Quasarr</h1>
            <p>{payload["error"]}</p>
            <p>
                {render_button("Back", "secondary", {"onclick": "location.href='/'"})}
            </p>''')

        package_id = payload.get("package_id")
        title = payload.get("title")
        password = payload.get("password")
        desired_mirror = payload.get("mirror")
        prioritized_links = payload.get("links")

        if not prioritized_links:
            # No links found, show an error message
            return render_centered_html(f'''
                <h1><img src="{images.logo}" type="image/png" alt="Quasarr logo" class="logo"/>Quasarr</h1>
                <p style="max-width: 370px; word-wrap: break-word; overflow-wrap: break-word;"><b>Package:</b> {title}</p>
                <p><b>Error:</b> No download links available for this package.</p>
                <p>
                    {render_button("Delete Package", "secondary", {"onclick": f"location.href='/captcha/delete/{package_id}'"})}
                </p>
                <p>
                    {render_button("Back", "secondary", {"onclick": "location.href='/'"})}
                </p>
            ''')

        link_options = ""
        if len(prioritized_links) > 1:
            for link in prioritized_links:
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
            link_select = f'<div id="mirrors-select">Mirror: <b>{prioritized_links[0][1]}</b></div>'

        # Pre-render button HTML in Python
        solve_another_html = render_button("Solve another CAPTCHA", "primary", {"onclick": "location.href='/captcha'"})
        back_button_html = render_button("Back", "secondary", {"onclick": "location.href='/'"})

        url = prioritized_links[0][0]

        # Add bypass section
        bypass_section = render_filecrypt_bypass_section(url, package_id, title, password)

        content = render_centered_html(r'''
            <script type="text/javascript">
                var api_key = "''' + captcha_values()["api_key"] + r'''";
                var endpoint = '/' + window.location.pathname.split('/')[1] + '/' + api_key + '.html';
                var solveAnotherHtml = `<p>''' + solve_another_html + r'''</p><p>''' + back_button_html + r'''</p>`;
                var noMoreHtml = `<p><b>No more CAPTCHAs</b></p><p>''' + back_button_html + r'''</p>`;

                function handleToken(token) {
                    document.getElementById("puzzle-captcha").remove();
                    document.getElementById("mirrors-select").remove();
                    document.getElementById("delete-package-section").style.display = "none";
                    document.getElementById("back-button-section").style.display = "none";
                    document.getElementById("bypass-section").style.display = "none";

                    // Remove width limit on result screen
                    var packageTitle = document.getElementById("package-title");
                    packageTitle.style.maxWidth = "none";

                    document.getElementById("captcha-key").innerText = 'Using result "' + token + '" to decrypt links...';
                    var link = document.getElementById("link-hidden").value;
                    const fullPath = '/captcha/decrypt-filecrypt';

                    fetch(fullPath, {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                        },
                        body: JSON.stringify({ 
                            token: token,
                            ''' + f'''package_id: '{package_id}',
                            title: '{js_single_quoted_string_safe(title)}',
                            link: link,
                            password: '{password}',
                            mirror: '{desired_mirror}',
                        ''' + '''})
                    })
                    .then(response => response.json())
                    .then(data => {
                        if (data.success) {
                            document.getElementById("captcha-key").insertAdjacentHTML('afterend', 
                                '<p>✅ Successful!</p>');
                        } else {
                            document.getElementById("captcha-key").insertAdjacentHTML('afterend', 
                                '<p>Failed. Check console for details!</p>');
                        }

                        // Show appropriate button based on whether more CAPTCHAs exist
                        var reloadSection = document.getElementById("reload-button");
                        if (data.has_more_captchas) {
                            reloadSection.innerHTML = solveAnotherHtml;
                        } else {
                            reloadSection.innerHTML = noMoreHtml;
                        }
                        reloadSection.style.display = "block";
                    });
                }
                ''' + captcha_js() + f'''</script>
                <div>
                    <h1><img src="{images.logo}" type="image/png" alt="Quasarr logo" class="logo"/>Quasarr</h1>
                    <p id="package-title" style="max-width: 370px; word-wrap: break-word; overflow-wrap: break-word;"><b>Package:</b> {title}</p>
                    <div id="captcha-key"></div>
                    {link_select}<br><br>
                    <input type="hidden" id="link-hidden" value="{prioritized_links[0][0]}" />
                    <div class="captcha-container">
                        <div id="puzzle-captcha" aria-style="mobile">
                            <strong>Your adblocker prevents the captcha from loading. Disable it!</strong>
                        </div>
                    </div>
                    <div id="reload-button" style="display: none;">
                    </div>
            <br>
            <div id="delete-package-section">
            <p>
                {render_button("Delete Package", "secondary", {"onclick": f"location.href='/captcha/delete/{package_id}'"})}
            </p>
            </div>
            <div id="back-button-section">
            <p>
                {render_button("Back", "secondary", {"onclick": "location.href='/'"})}
            </p>
            </div>
            <div id="bypass-section">
                {bypass_section}
            </div>
                </div>
                </html>''')

        return content

    @app.post('/captcha/<captcha_id>.html')
    def proxy_html(captcha_id):
        target_url = f"{captcha_values()["url"]}/captcha/{captcha_id}.html"

        headers = {key: value for key, value in request.headers.items() if key != 'Host'}
        data = request.body.read()
        resp = requests.post(target_url, headers=headers, data=data, verify=False)

        response.content_type = resp.headers.get('Content-Type')

        content = resp.text
        content = re.sub(
            r'''<script\s+src="/(jquery(?:-ui|\.ui\.touch-punch\.min)?\.js)(?:\?[^"]*)?"></script>''',
            r'''<script src="/captcha/js/\1"></script>''',
            content
        )

        response.content_type = 'text/html'
        return content

    @app.post('/captcha/<captcha_id>.json')
    def proxy_json(captcha_id):
        target_url = f"{captcha_values()["url"]}/captcha/{captcha_id}.json"

        headers = {key: value for key, value in request.headers.items() if key != 'Host'}
        data = request.body.read()
        resp = requests.post(target_url, headers=headers, data=data, verify=False)

        response.content_type = resp.headers.get('Content-Type')
        return resp.content

    @app.get('/captcha/js/<filename>')
    def serve_local_js(filename):
        upstream = f"{captcha_values()['url']}/{filename}"
        try:
            upstream_resp = requests.get(upstream, verify=False, stream=True)
            upstream_resp.raise_for_status()
        except requests.RequestException as e:
            response.status = 502
            return f"/* Error proxying {filename}: {e} */"

        response.content_type = 'application/javascript'
        return upstream_resp.iter_content(chunk_size=8192)

    @app.get('/captcha/<captcha_id>/<uuid>/<filename>')
    def proxy_pngs(captcha_id, uuid, filename):
        new_url = f"{captcha_values()["url"]}/captcha/{captcha_id}/{uuid}/{filename}"

        try:
            external_response = requests.get(new_url, stream=True, verify=False)
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
        resp = requests.post(new_url, headers=headers, data=data, verify=False)

        response.status = resp.status_code
        for header in resp.headers:
            if header.lower() not in ['content-encoding', 'transfer-encoding', 'content-length', 'connection']:
                response.set_header(header, resp.headers[header])
        return resp.content

    @app.post('/captcha/bypass-submit')
    def handle_bypass_submit():
        """Handle bypass submission with either links or DLC file"""
        try:
            package_id = request.forms.get('package_id')
            title = request.forms.get('title')
            password = request.forms.get('password', '')
            links_input = request.forms.get('links', '').strip()
            dlc_upload = request.files.get('dlc_file')

            if not package_id or not title:
                return render_centered_html(f'''<h1><img src="{images.logo}" type="image/png" alt="Quasarr logo" class="logo"/>Quasarr</h1>
                <p><b>Error:</b> Missing package information.</p>
                <p>
                    {render_button("Back", "secondary", {"onclick": "location.href='/captcha'"})}
                </p>''')

            package_exists = shared_state.get_db("protected").retrieve(package_id)
            if not package_exists:
                return render_centered_html(f'''<h1><img src="{images.logo}" type="image/png" alt="Quasarr logo" class="logo"/>Quasarr</h1>
                <p><b>Error:</b> Package not found or already solved.</p>
                <p>
                    {render_button("Back", "secondary", {"onclick": "location.href='/captcha'"})}
                </p>''')

            # Process links input
            if links_input:
                info(f"Processing direct links bypass for {title}")
                raw_links = [link.strip() for link in links_input.split('\n') if link.strip()]
                links = [l for l in raw_links if l.lower().startswith(("http://", "https://"))]

                info(f"Received {len(links)} valid direct download links "
                     f"(from {len(raw_links)} provided)")

            # Process DLC file
            elif dlc_upload:
                info(f"Processing DLC file bypass for {title}")
                dlc_content = dlc_upload.file.read()
                try:
                    decrypted_links = DLC(shared_state, dlc_content).decrypt()
                    if decrypted_links:
                        links = decrypted_links
                        info(f"Decrypted {len(links)} links from DLC file")
                    else:
                        raise ValueError("DLC decryption returned no links")
                except Exception as e:
                    info(f"DLC decryption failed: {e}")
                    return render_centered_html(f'''<h1><img src="{images.logo}" type="image/png" alt="Quasarr logo" class="logo"/>Quasarr</h1>
                    <p><b>Error:</b> Failed to decrypt DLC file: {str(e)}</p>
                    <p>
                        {render_button("Back", "secondary", {"onclick": "location.href='/captcha'"})}
                    </p>''')
            else:
                return render_centered_html(f'''<h1><img src="{images.logo}" type="image/png" alt="Quasarr logo" class="logo"/>Quasarr</h1>
                <p><b>Error:</b> Please provide either links or a DLC file.</p>
                <p>
                    {render_button("Back", "secondary", {"onclick": "location.href='/captcha'"})}
                </p>''')

            # Download the package
            if links:
                downloaded = shared_state.download_package(links, title, password, package_id)
                if downloaded:
                    StatsHelper(shared_state).increment_package_with_links(links)
                    StatsHelper(shared_state).increment_captcha_decryptions_manual()
                    shared_state.get_db("protected").delete(package_id)

                    # Check if there are more CAPTCHAs to solve
                    remaining_protected = shared_state.get_db("protected").retrieve_all_titles()
                    has_more_captchas = bool(remaining_protected)

                    if has_more_captchas:
                        solve_button = render_button("Solve another CAPTCHA", "primary", {
                            "onclick": "location.href='/captcha'",
                        })
                    else:
                        solve_button = "<b>No more CAPTCHAs</b>"

                    return render_centered_html(f'''<h1><img src="{images.logo}" type="image/png" alt="Quasarr logo" class="logo"/>Quasarr</h1>
                    <p><b>Success!</b> Package "{title}" bypassed and submitted to JDownloader.</p>
                    <p>{len(links)} link(s) processed.</p>
                    <p>
                        {solve_button}
                    </p>
                    <p>
                        {render_button("Back", "secondary", {"onclick": "location.href='/'"})}
                    </p>''')
                else:
                    StatsHelper(shared_state).increment_failed_decryptions_manual()
                    return render_centered_html(f'''<h1><img src="{images.logo}" type="image/png" alt="Quasarr logo" class="logo"/>Quasarr</h1>
                    <p><b>Error:</b> Failed to submit package to JDownloader.</p>
                    <p>
                        {render_button("Try Again", "secondary", {"onclick": "location.href='/captcha'"})}
                    </p>''')
            else:
                return render_centered_html(f'''<h1><img src="{images.logo}" type="image/png" alt="Quasarr logo" class="logo"/>Quasarr</h1>
                <p><b>Error:</b> No valid links found.</p>
                <p>
                    {render_button("Back", "secondary", {"onclick": "location.href='/captcha'"})}
                </p>''')

        except Exception as e:
            info(f"Bypass submission error: {e}")
            return render_centered_html(f'''<h1><img src="{images.logo}" type="image/png" alt="Quasarr logo" class="logo"/>Quasarr</h1>
            <p><b>Error:</b> {str(e)}</p>
            <p>
                {render_button("Back", "secondary", {"onclick": "location.href='/captcha'"})}
            </p>''')

    @app.post('/captcha/decrypt-filecrypt')
    def submit_token():
        protected = shared_state.get_db("protected").retrieve_all_titles()
        if not protected:
            return {"success": False, "title": "No protected packages found! CAPTCHA not needed."}

        links = []
        title = "Unknown Package"
        try:
            data = request.json
            token = data.get('token')
            package_id = data.get('package_id')
            title = data.get('title')
            link = data.get('link')
            password = data.get('password')
            mirror = None if (mirror := data.get('mirror')) == "None" else mirror

            if token:
                info(f"Received token: {token}")
                info(f"Decrypting links for {title}")
                decrypted = get_filecrypt_links(shared_state, token, title, link, password=password, mirror=mirror)
                if decrypted:
                    if decrypted.get("status", "") == "replaced":
                        replace_url = decrypted.get("replace_url")
                        session = decrypted.get("session")
                        mirror = decrypted.get("mirror", "filecrypt")

                        links = [replace_url]

                        blob = json.dumps(
                            {
                                "title": title,
                                "links": [replace_url, mirror],
                                "size_mb": 0,
                                "password": password,
                                "mirror": mirror,
                                "session": session,
                                "original_url": link
                            })
                        shared_state.get_db("protected").update_store(package_id, blob)
                        info(f"Another CAPTCHA solution is required for {mirror} link: {replace_url}")

                    else:
                        links = decrypted.get("links", [])
                        info(f"Decrypted {len(links)} download links for {title}")
                        if not links:
                            raise ValueError("No download links found after decryption")
                        downloaded = shared_state.download_package(links, title, password, package_id)
                        if downloaded:
                            StatsHelper(shared_state).increment_package_with_links(links)
                            shared_state.get_db("protected").delete(package_id)
                        else:
                            links = []
                            raise RuntimeError("Submitting Download to JDownloader failed")
                else:
                    raise ValueError("No download links found")

        except Exception as e:
            info(f"Error decrypting: {e}")

        success = bool(links)
        if success:
            StatsHelper(shared_state).increment_captcha_decryptions_manual()
        else:
            StatsHelper(shared_state).increment_failed_decryptions_manual()

        # Check if there are more CAPTCHAs to solve
        remaining_protected = shared_state.get_db("protected").retrieve_all_titles()
        has_more_captchas = bool(remaining_protected)

        return {"success": success, "title": title, "has_more_captchas": has_more_captchas}

    # The following routes are for circle CAPTCHA
    @app.get('/captcha/circle')
    def serve_circle():
        payload = decode_payload()

        if "error" in payload:
            return render_centered_html(f'''<h1><img src="{images.logo}" type="image/png" alt="Quasarr logo" class="logo"/>Quasarr</h1>
            <p>{payload["error"]}</p>
            <p>
                {render_button("Back", "secondary", {"onclick": "location.href='/'"})}
            </p>''')

        package_id = payload.get("package_id")
        session_id = payload.get("session")
        title = payload.get("title", "Unknown Package")
        password = payload.get("password", "")
        original_url = payload.get("original_url", "")
        url = payload.get("links")[0] if payload.get("links") else None

        if not url or not session_id or not package_id:
            response.status = 400
            return "Missing required parameters"

        # Add bypass section
        bypass_section = render_filecrypt_bypass_section(original_url, package_id, title, password)

        return render_centered_html(f"""
        <!DOCTYPE html>
        <html>
          <body>
            <h1><img src="{images.logo}" type="image/png" alt="Quasarr logo" class="logo"/>Quasarr</h1>
            <p><b>Package:</b> {title}</p>
            <form action="/captcha/decrypt-filecrypt-circle?url={url}&session_id={session_id}&package_id={package_id}" method="post">
              <input type="image" src="/captcha/circle.php?url={url}&session_id={session_id}" name="button" alt="Circle CAPTCHA">
            </form>
            <p>
                {render_button("Delete Package", "secondary", {"onclick": f"location.href='/captcha/delete/{package_id}'"})}
            </p>
            <p>
                {render_button("Back", "secondary", {"onclick": "location.href='/'"})}
            </p>
            {bypass_section}
          </body>
        </html>""")

    @app.get('/captcha/circle.php')
    def proxy_circle_php():
        target_url = "https://filecrypt.cc/captcha/circle.php"

        url = request.query.get('url')
        session_id = request.query.get('session_id')
        if not url or not session_id:
            response.status = 400
            return "Missing required parameters"

        headers = {'User-Agent': shared_state.values["user_agent"]}
        cookies = {'PHPSESSID': session_id}
        resp = requests.get(target_url, headers=headers, cookies=cookies, verify=False)

        response.content_type = resp.headers.get('Content-Type', 'application/octet-stream')
        return resp.content

    @app.post('/captcha/decrypt-filecrypt-circle')
    def proxy_form_submit():
        url = request.query.get('url')
        session_id = request.query.get('session_id')
        package_id = request.query.get('package_id')
        success = False

        if not url or not session_id or not package_id:
            response.status = 400
            return "Missing required parameters"

        cookies = {'PHPSESSID': session_id}

        headers = {
            'User-Agent': shared_state.values["user_agent"],
            "Content-Type": "application/x-www-form-urlencoded"
        }

        raw_body = request.body.read()

        resp = requests.post(url, cookies=cookies, headers=headers, data=raw_body, verify=False)
        response.content_type = resp.headers.get('Content-Type', 'text/html')

        if "<h2>Security Check</h2>" in resp.text or "click inside the open circle" in resp.text:
            status = "CAPTCHA verification failed. Please try again."
            info(status)

        match = re.search(
            r"top\.location\.href\s*=\s*['\"]([^'\"]*?/go\b[^'\"]*)['\"]",
            resp.text,
            re.IGNORECASE
        )
        if match:
            redirect = match.group(1)
            resolved_url = urljoin(url, redirect)
            info(f"Redirect URL: {resolved_url}")
            try:
                redirect_resp = requests.post(resolved_url, cookies=cookies, headers=headers, allow_redirects=True,
                                              timeout=10, verify=False)

                if "expired" in redirect_resp.text.lower():
                    status = f"The CAPTCHA session has expired. Deleting package: {package_id}"
                    info(status)
                    shared_state.get_db("protected").delete(package_id)
                else:
                    download_link = redirect_resp.url
                    if redirect_resp.ok:
                        status = f"Successfully resolved download link!"
                        info(status)

                        raw_data = shared_state.get_db("protected").retrieve(package_id)
                        data = json.loads(raw_data)
                        title = data.get("title")
                        password = data.get("password", "")
                        links = [download_link]
                        downloaded = shared_state.download_package(links, title, password, package_id)
                        if downloaded:
                            StatsHelper(shared_state).increment_package_with_links(links)
                            success = True
                            shared_state.get_db("protected").delete(package_id)
                        else:
                            raise RuntimeError("Submitting Download to JDownloader failed")
                    else:
                        info(
                            f"Failed to reach redirect target. Status: {redirect_resp.status_code}, Solution: {status}")
            except Exception as e:
                info(f"Error while resolving download link: {e}")
        else:
            if resp.url.endswith("404.html"):
                info("Your IP has been blocked by Filecrypt. Please try again later.")
            else:
                info("You did not solve the CAPTCHA correctly. Please try again.")

        if success:
            StatsHelper(shared_state).increment_captcha_decryptions_manual()
        else:
            StatsHelper(shared_state).increment_failed_decryptions_manual()

        # Check if there are more CAPTCHAs to solve
        remaining_protected = shared_state.get_db("protected").retrieve_all_titles()
        has_more_captchas = bool(remaining_protected)

        if has_more_captchas:
            solve_button = render_button("Solve another CAPTCHA", "primary", {
                "onclick": "location.href='/captcha'",
            })
        else:
            solve_button = "<b>No more CAPTCHAs</b>"

        return render_centered_html(f"""
        <!DOCTYPE html>
        <html>
          <body>
            <h1><img src="{images.logo}" type="image/png" alt="Quasarr logo" class="logo"/>Quasarr</h1>
            <p>{status}</p>
            <p>
                {solve_button}
            </p>
            <p>
                {render_button("Back", "secondary", {"onclick": "location.href='/'"})}
            </p>
          </body>
        </html>""")
