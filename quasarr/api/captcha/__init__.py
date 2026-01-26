# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import json
import re
from base64 import urlsafe_b64decode, urlsafe_b64encode
from urllib.parse import quote, unquote

import requests
from bottle import HTTPResponse, redirect, request, response

import quasarr.providers.html_images as images
from quasarr.downloads.linkcrypters.filecrypt import DLC, get_filecrypt_links
from quasarr.downloads.packages import delete_package
from quasarr.providers import obfuscated, shared_state
from quasarr.providers.html_templates import render_button, render_centered_html
from quasarr.providers.log import debug, info
from quasarr.providers.statistics import StatsHelper


def js_single_quoted_string_safe(text):
    return text.replace("\\", "\\\\").replace("'", "\\'")


def check_package_exists(package_id):
    if not shared_state.get_db("protected").retrieve(package_id):
        raise HTTPResponse(
            status=404,
            body=render_centered_html(f'''
                <h1><img src="{images.logo}" class="logo"/>Quasarr</h1>
                <p><b>Error:</b> Package not found or already solved.</p>
                <p>
                    {render_button("Back", "secondary", {"onclick": "location.href='/captcha'"})}
                </p>
            '''),
            content_type="text/html",
        )


def setup_captcha_routes(app):
    @app.get("/captcha")
    def check_captcha():
        try:
            device = shared_state.values["device"]
        except KeyError:
            device = None
        if not device:
            return render_centered_html(f'''<h1><img src="{images.logo}" type="image/png" alt="Quasarr logo" class="logo"/>Quasarr</h1>
            <div class="status-bar">
                <span class="status-pill error">
                    ❌ JDownloader disconnected
                </span>
            </div>
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
            # Check if a specific package_id was requested
            requested_package_id = request.query.get("package_id")
            package = None

            if requested_package_id:
                # Find the specific package
                for p in protected:
                    if p[0] == requested_package_id:
                        package = p
                        break

            # Fall back to first package if not found or not specified
            if package is None:
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

            original_url = data.get("original_url")

            # This is required for cutcaptcha
            rapid = [ln for ln in links if "rapidgator" in ln[1].lower()]
            others = [ln for ln in links if "rapidgator" not in ln[1].lower()]
            prioritized_links = rapid + others

            payload = {
                "package_id": package_id,
                "title": title,
                "password": password,
                "mirror": desired_mirror,
                "links": prioritized_links,
                "original_url": original_url,
            }

            encoded_payload = urlsafe_b64encode(json.dumps(payload).encode()).decode()

            sj = shared_state.values["config"]("Hostnames").get("sj")
            dj = shared_state.values["config"]("Hostnames").get("dj")

            def is_junkies_link(link):
                """Check if link is a junkies link (handles [[url, mirror]] format)."""
                url = link[0] if isinstance(link, (list, tuple)) else link
                mirror = (
                    link[1] if isinstance(link, (list, tuple)) and len(link) > 1 else ""
                )
                if mirror == "junkies":
                    return True
                return (sj and sj in url) or (dj and dj in url)

            has_junkies_links = any(is_junkies_link(link) for link in prioritized_links)

            # Hide uses nested arrays like FileCrypt: [["url", "mirror"]]
            has_hide_links = any(
                (
                    "hide." in link[0]
                    if isinstance(link, (list, tuple))
                    else "hide." in link
                )
                for link in prioritized_links
            )

            # KeepLinks uses nested arrays like FileCrypt: [["url", "mirror"]]
            has_keeplinks_links = any(
                (
                    "keeplinks." in link[0]
                    if isinstance(link, (list, tuple))
                    else "keeplinks." in link
                )
                for link in prioritized_links
            )

            # ToLink uses nested arrays like FileCrypt: [["url", "mirror"]]
            has_tolink_links = any(
                (
                    "tolink." in link[0]
                    if isinstance(link, (list, tuple))
                    else "tolink." in link
                )
                for link in prioritized_links
            )

            if has_hide_links:
                debug("Redirecting to Hide page")
                redirect(f"/captcha/hide?data={quote(encoded_payload)}")
            elif has_junkies_links:
                debug("Redirecting to Junkies CAPTCHA")
                redirect(f"/captcha/junkies?data={quote(encoded_payload)}")
            elif has_keeplinks_links:
                debug("Redirecting to KeepLinks CAPTCHA")
                redirect(f"/captcha/keeplinks?data={quote(encoded_payload)}")
            elif has_tolink_links:
                debug("Redirecting to ToLink CAPTCHA")
                redirect(f"/captcha/tolink?data={quote(encoded_payload)}")
            else:
                debug(f"Redirecting to cutcaptcha")
                redirect(f"/captcha/cutcaptcha?data={quote(encoded_payload)}")

            return render_centered_html(f'''<h1><img src="{images.logo}" type="image/png" alt="Quasarr logo" class="logo"/>Quasarr</h1>
            <p>Unexpected Error!</p>
            <p>
                {render_button("Back", "secondary", {"onclick": "location.href='/'"})}
            </p>''')

    def decode_payload():
        encoded = request.query.get("data")
        try:
            decoded = urlsafe_b64decode(unquote(encoded)).decode()
            return json.loads(decoded)
        except Exception as e:
            return {"error": f"Failed to decode payload: {str(e)}"}

    def render_userscript_section(
        url, package_id, title, password, provider_type="junkies"
    ):
        """Render the userscript UI section for Junkies, KeepLinks, ToLink, or Hide pages

        This is the MAIN solution for these providers (not a bypass/fallback).

        Args:
            url: The URL to open with transfer params
            package_id: Package identifier
            title: Package title
            password: Package password
            provider_type: Either "hide", "junkies", "keeplinks", or "tolink"
        """

        provider_names = {
            "hide": "Hide",
            "junkies": "Junkies",
            "keeplinks": "KeepLinks",
            "tolink": "ToLink",
        }
        provider_name = provider_names.get(provider_type, "Provider")
        userscript_url = f"/captcha/{provider_type}.user.js"
        storage_key = f"hide{provider_name}SetupInstructions"

        # Generate userscript URL with transfer params
        base_url = request.urlparts.scheme + "://" + request.urlparts.netloc
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
                <div id="setup-instructions" class="setup-box">
                    <h3>📦 First Time Setup:</h3>
                    <p style="margin-bottom: 8px;">
                        <a href="https://www.tampermonkey.net/" target="_blank" rel="noopener noreferrer">1. On mobile Safari/Firefox or any Desktop Browser install Tampermonkey</a>
                    </p>
                    <p style="margin-top: 0; margin-bottom: 8px;">
                        <a href="{userscript_url}" target="_blank">2. Install the {provider_name} userscript</a>
                    </p>
                    <p style="margin-top: 0; margin-bottom: 12px;">
                        3. Open link, solve CAPTCHAs, and links are automatically sent back to Quasarr!
                    </p>
                    <p style="margin-top: 0;">
                        <button id="hide-setup-btn" type="button" class="btn-subtle">
                            ✅ Don't show this again
                        </button>
                    </p>
                </div>

                <!-- Hidden "show instructions" button -->
                <div id="show-instructions-link" style="display: none; margin-bottom: 16px;">
                    <button id="show-setup-btn" type="button" class="btn-subtle">
                        ℹ️ Show setup instructions
                    </button>
                </div>

                <!-- Primary action - the quick transfer link -->
                <p>
                    {render_button(f"Open {provider_name} & Get Download Links", "primary", {"onclick": f"if(typeof incrementCaptchaAttempts==='function')incrementCaptchaAttempts();location.href='{url_with_quick_transfer_params}'"})}
                </p>

                <!-- Manual submission - collapsible -->
                <div class="section-divider">
                    <details id="manualSubmitDetails">
                        <summary id="manualSubmitSummary" style="cursor: pointer;">Show Manual Submission</summary>
                        <div style="margin-top: 16px;">
                            <p style="font-size: 0.9em;">
                                If the userscript doesn't work, you can manually paste the links below:
                            </p>
                            <form id="bypass-form" action="/captcha/bypass-submit" method="post" enctype="multipart/form-data" onsubmit="if(typeof incrementCaptchaAttempts==='function')incrementCaptchaAttempts();">
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
                    </details>
                </div>
            </div>
            <script>
              // Handle manual submission toggle text
              const manualDetails = document.getElementById('manualSubmitDetails');
              const manualSummary = document.getElementById('manualSubmitSummary');

              if (manualDetails && manualSummary) {{
                manualDetails.addEventListener('toggle', () => {{
                  if (manualDetails.open) {{
                    manualSummary.textContent = 'Hide Manual Submission';
                  }} else {{
                    manualSummary.textContent = 'Show Manual Submission';
                  }}
                }});
              }}

              // Handle setup instructions hide/show
              const hideSetup = localStorage.getItem('{storage_key}');
              const setupBox = document.getElementById('setup-instructions');
              const showLink = document.getElementById('show-instructions-link');

              if (hideSetup === 'true') {{
                setupBox.style.display = 'none';
                showLink.style.display = 'block';
              }}

              // Hide setup instructions
              document.getElementById('hide-setup-btn').addEventListener('click', function() {{
                localStorage.setItem('{storage_key}', 'true');
                setupBox.style.display = 'none';
                showLink.style.display = 'block';
              }});

              // Show setup instructions again
              document.getElementById('show-setup-btn').addEventListener('click', function() {{
                localStorage.setItem('{storage_key}', 'false');
                setupBox.style.display = 'block';
                showLink.style.display = 'none';
              }});
            </script>
        '''

    @app.get("/captcha/hide")
    def serve_hide_captcha():
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
        original_url = payload.get("original_url")
        url = urls[0][0] if isinstance(urls[0], (list, tuple)) else urls[0]

        check_package_exists(package_id)

        package_selector = render_package_selector(package_id, title)
        failed_warning = render_failed_attempts_warning(package_id)

        source_button = ""
        if original_url:
            source_button = f"<p>{render_button('Source', 'secondary', {'onclick': f"window.open('{js_single_quoted_string_safe(original_url)}', '_blank')"})}</p>"

        return render_centered_html(f"""
        <!DOCTYPE html>
        <html>
          <body>
            <h1><img src="{images.logo}" type="image/png" alt="Quasarr logo" class="logo"/>Quasarr</h1>
            {package_selector}
            {failed_warning}
                {render_userscript_section(url, package_id, title, password, "hide")}
            {source_button}
            <p>
                {render_button("Delete Package", "secondary", {"onclick": f"location.href='/captcha/delete/{package_id}'"})}
            </p>
            <p>
                {render_button("Back", "secondary", {"onclick": "location.href='/'"})}
            </p>

          </body>
        </html>""")

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
        original_url = payload.get("original_url")
        url = urls[0][0] if isinstance(urls[0], (list, tuple)) else urls[0]

        check_package_exists(package_id)

        package_selector = render_package_selector(package_id, title)
        failed_warning = render_failed_attempts_warning(package_id)

        source_button = ""
        if original_url:
            source_button = f"<p>{render_button('Source', 'secondary', {'onclick': f"window.open('{js_single_quoted_string_safe(original_url)}', '_blank')"})}</p>"

        return render_centered_html(f"""
        <!DOCTYPE html>
        <html>
          <body>
            <h1><img src="{images.logo}" type="image/png" alt="Quasarr logo" class="logo"/>Quasarr</h1>
            {package_selector}
            {failed_warning}
                {render_userscript_section(url, package_id, title, password, "junkies")}
            {source_button}
            <p>
                {render_button("Delete Package", "secondary", {"onclick": f"location.href='/captcha/delete/{package_id}'"})}
            </p>
            <p>
                {render_button("Back", "secondary", {"onclick": "location.href='/'"})}
            </p>

          </body>
        </html>""")

    @app.get("/captcha/keeplinks")
    def serve_keeplinks_captcha():
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
        original_url = payload.get("original_url")

        check_package_exists(package_id)

        url = urls[0][0] if isinstance(urls[0], (list, tuple)) else urls[0]

        package_selector = render_package_selector(package_id, title)
        failed_warning = render_failed_attempts_warning(package_id)

        source_button = ""
        if original_url:
            source_button = f"<p>{render_button('Source', 'secondary', {'onclick': f"window.open('{js_single_quoted_string_safe(original_url)}', '_blank')"})}</p>"

        return render_centered_html(f"""
        <!DOCTYPE html>
        <html>
          <body>
            <h1><img src="{images.logo}" type="image/png" alt="Quasarr logo" class="logo"/>Quasarr</h1>
            {package_selector}
            {failed_warning}
                {render_userscript_section(url, package_id, title, password, "keeplinks")}
            {source_button}
            <p>
                {render_button("Delete Package", "secondary", {"onclick": f"location.href='/captcha/delete/{package_id}'"})}
            </p>
            <p>
                {render_button("Back", "secondary", {"onclick": "location.href='/'"})}
            </p>

          </body>
        </html>""")

    @app.get("/captcha/tolink")
    def serve_tolink_captcha():
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
        original_url = payload.get("original_url")

        check_package_exists(package_id)

        url = urls[0][0] if isinstance(urls[0], (list, tuple)) else urls[0]

        package_selector = render_package_selector(package_id, title)
        failed_warning = render_failed_attempts_warning(package_id)

        source_button = ""
        if original_url:
            source_button = f"<p>{render_button('Source', 'secondary', {'onclick': f"window.open('{js_single_quoted_string_safe(original_url)}', '_blank')"})}</p>"

        return render_centered_html(f"""
        <!DOCTYPE html>
        <html>
          <body>
            <h1><img src="{images.logo}" type="image/png" alt="Quasarr logo" class="logo"/>Quasarr</h1>
            {package_selector}
            {failed_warning}
                {render_userscript_section(url, package_id, title, password, "tolink")}
            {source_button}
            <p>
                {render_button("Delete Package", "secondary", {"onclick": f"location.href='/captcha/delete/{package_id}'"})}
            </p>
            <p>
                {render_button("Back", "secondary", {"onclick": "location.href='/'"})}
            </p>

          </body>
        </html>""")

    @app.get("/captcha/filecrypt.user.js")
    def serve_filecrypt_user_js():
        content = obfuscated.filecrypt_user_js()
        response.content_type = "application/javascript"
        return content

    @app.get("/captcha/hide.user.js")
    def serve_hide_user_js():
        content = obfuscated.hide_user_js()
        response.content_type = "application/javascript"
        return content

    @app.get("/captcha/junkies.user.js")
    def serve_junkies_user_js():
        sj = shared_state.values["config"]("Hostnames").get("sj")
        dj = shared_state.values["config"]("Hostnames").get("dj")

        content = obfuscated.junkies_user_js(sj, dj)
        response.content_type = "application/javascript"
        return content

    @app.get("/captcha/keeplinks.user.js")
    def serve_keeplinks_user_js():
        content = obfuscated.keeplinks_user_js()
        response.content_type = "application/javascript"
        return content

    @app.get("/captcha/tolink.user.js")
    def serve_tolink_user_js():
        content = obfuscated.tolink_user_js()
        response.content_type = "application/javascript"
        return content

    def render_filecrypt_bypass_section(url, package_id, title, password):
        """Render the bypass UI section for cutcaptcha captcha page"""

        # Generate userscript URL with transfer params
        # Get base URL of current request
        base_url = request.urlparts.scheme + "://" + request.urlparts.netloc
        transfer_url = f"{base_url}/captcha/quick-transfer"

        url_with_quick_transfer_params = (
            f"{url}?"
            f"transfer_url={quote(transfer_url)}&"
            f"pkg_id={quote(package_id)}&"
            f"pkg_title={quote(title)}&"
            f"pkg_pass={quote(password)}"
        )

        return f'''
            <div class="section-divider" style="max-width: 370px; margin-left: auto; margin-right: auto;">
                <details id="bypassDetails">
                <summary id="bypassSummary">Show CAPTCHA Bypass</summary><br>

                    <!-- One-time setup section - visually separated -->
                    <div id="setup-instructions" class="setup-box">
                        <h3>📦 First Time Setup:</h3>
                        <p style="margin-bottom: 8px;">
                            <a href="https://www.tampermonkey.net/" target="_blank" rel="noopener noreferrer">1. On mobile Safari/Firefox or any Desktop Browser install Tampermonkey</a>
                        </p>
                        <p style="margin-top: 0; margin-bottom: 8px;">
                            <a href="/captcha/filecrypt.user.js" target="_blank">2. Install the FileCrypt userscript</a>
                        </p>
                        <p style="margin-top: 0; margin-bottom: 12px;">
                            3. Open link, solve CAPTCHAs, and links are automatically sent back to Quasarr!
                        </p>
                        <p style="margin-top: 0;">
                            <button id="hide-setup-btn" type="button" class="btn-subtle">
                                ✅ Don't show this again
                            </button>
                        </p>
                    </div>

                    <!-- Hidden "show instructions" button -->
                    <div id="show-instructions-link" style="display: none; margin-bottom: 16px;">
                        <button id="show-setup-btn" type="button" class="btn-subtle">
                            ℹ️ Show setup instructions
                        </button>
                    </div>

                    <!-- Primary action button -->
                    <p>
                        {render_button("Open FileCrypt & Get Download Links", "primary", {"onclick": f"if(typeof incrementCaptchaAttempts==='function')incrementCaptchaAttempts();location.href='{url_with_quick_transfer_params}'"})}
                    </p>

                    <!-- Manual submission section -->
                    <div class="section-divider">
                        <p style="font-size: 0.9em; margin-bottom: 16px;">
                            If the userscript doesn't work, you can manually paste the links or upload a DLC file:
                        </p>
                        <form id="bypass-form" action="/captcha/bypass-submit" method="post" enctype="multipart/form-data" onsubmit="if(typeof incrementCaptchaAttempts==='function')incrementCaptchaAttempts();">
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
                    </div>
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
              document.getElementById('show-setup-btn').addEventListener('click', function() {{
                localStorage.setItem('hideFileCryptSetupInstructions', 'false');
                setupBox.style.display = 'block';
                showLink.style.display = 'none';
              }});
            </script>
        '''

    def render_package_selector(current_package_id, current_title=None):
        """Render package title, with dropdown selector if multiple packages available"""
        protected = shared_state.get_db("protected").retrieve_all_titles()

        if not protected:
            return ""

        # Single package - just show the title without dropdown
        if len(protected) <= 1:
            if current_title:
                return f"""
                    <div class="package-selector" style="margin-bottom: 20px; padding: 12px; background: rgba(128, 128, 128, 0.1); border: 1px solid rgba(128, 128, 128, 0.3); border-radius: 8px;">
                        <p style="margin: 0; word-break: break-all;"><b>📦 Package:</b> {current_title}</p>
                    </div>
                """
            return ""

        sj = shared_state.values["config"]("Hostnames").get("sj")
        dj = shared_state.values["config"]("Hostnames").get("dj")

        def is_junkies_link(link):
            url = link[0] if isinstance(link, (list, tuple)) else link
            mirror = (
                link[1] if isinstance(link, (list, tuple)) and len(link) > 1 else ""
            )
            if mirror == "junkies":
                return True
            return (sj and sj in url) or (dj and dj in url)

        def get_captcha_type_for_links(links):
            """Determine which captcha type to use based on links"""
            has_hide = any(
                ("hide." in (l[0] if isinstance(l, (list, tuple)) else l))
                for l in links
            )
            has_junkies = any(is_junkies_link(l) for l in links)
            has_keeplinks = any(
                ("keeplinks." in (l[0] if isinstance(l, (list, tuple)) else l))
                for l in links
            )
            has_tolink = any(
                ("tolink." in (l[0] if isinstance(l, (list, tuple)) else l))
                for l in links
            )

            if has_hide:
                return "hide"
            elif has_junkies:
                return "junkies"
            elif has_keeplinks:
                return "keeplinks"
            elif has_tolink:
                return "tolink"
            else:
                return "cutcaptcha"

        options = []
        for package in protected:
            pkg_id = package[0]
            data = json.loads(package[1])
            title = data.get("title", "Unknown")
            links = data.get("links", [])
            password = data.get("password", "")
            mirror = data.get("mirror")
            original_url = data.get("original_url")

            # Prioritize rapidgator links for cutcaptcha
            rapid = [ln for ln in links if "rapidgator" in ln[1].lower()]
            others = [ln for ln in links if "rapidgator" not in ln[1].lower()]
            prioritized = rapid + others

            payload = {
                "package_id": pkg_id,
                "title": title,
                "password": password,
                "mirror": mirror,
                "links": prioritized,
                "original_url": original_url,
            }
            encoded = urlsafe_b64encode(json.dumps(payload).encode()).decode()
            captcha_type = get_captcha_type_for_links(prioritized)

            selected = "selected" if pkg_id == current_package_id else ""
            # Truncate long titles for display
            display_title = (title[:50] + "...") if len(title) > 53 else title
            options.append(
                f'<option value="{captcha_type}|{quote(encoded)}" {selected}>{display_title}</option>'
            )

        options_html = "\n".join(options)

        return f"""
            <div class="package-selector" style="margin-bottom: 20px; padding: 12px; background: rgba(128, 128, 128, 0.1); border: 1px solid rgba(128, 128, 128, 0.3); border-radius: 8px;">
                <label for="package-select" style="display: block; margin-bottom: 8px; font-weight: bold;">📦 Select Package:</label>
                <select id="package-select" style="width: 100%; padding: 8px; border-radius: 4px; background: inherit; color: inherit; border: 1px solid rgba(128, 128, 128, 0.5); cursor: pointer;">
                    {options_html}
                </select>
            </div>
            <script>
                document.getElementById('package-select').addEventListener('change', function() {{
                    const [captchaType, encodedData] = this.value.split('|');
                    window.location.href = '/captcha/' + captchaType + '?data=' + encodedData;
                }});
            </script>
        """

    def render_failed_attempts_warning(
        package_id, include_delete_button=True, fallback_url=None
    ):
        """Render a warning block that shows after 2+ failed attempts per package_id.
        Uses localStorage to track attempts by package_id to ensure reliable tracking
        even when package titles are duplicated.

        Attempts are NOT incremented on page load - they must be incremented by
        calling window.incrementCaptchaAttempts() when user takes an action (e.g.,
        clicking submit, opening bypass link).

        Args:
            package_id: The unique package identifier
            include_delete_button: Whether to show delete button in warning
            fallback_url: Optional URL to a fallback page (e.g., FileCrypt manual fallback)
        """

        delete_button = ""
        if include_delete_button:
            delete_button = render_button(
                "Delete Package",
                "primary",
                {"onclick": f"location.href='/captcha/delete/{package_id}'"},
            )

        fallback_link = ""
        if fallback_url:
            fallback_link = f'''
                <p style="margin-top: 12px; margin-bottom: 8px;">
                    <a href="{fallback_url}" style="color: #cc0000;">Try the manual FileCrypt fallback page →</a>
                </p>
            '''

        return f"""
            <div id="failed-attempts-warning" class="warning-box" style="display: none; background: #fee2e2; border: 2px solid #dc2626; border-radius: 8px; padding: 16px; margin-bottom: 20px; text-align: center; color: #991b1b;">
                <h3 style="color: #dc2626; margin-top: 0;">⚠️ Multiple Failed Attempts Detected</h3>
                <p style="margin-bottom: 12px; color: #7f1d1d;">This CAPTCHA has failed multiple times. The link may be <b>offline</b> or require a different solution method.</p>
                <p style="margin-bottom: 8px; color: #7f1d1d;">Please verify the link is still valid, or delete this package if it's no longer available.</p>
                {fallback_link}
                <div id="warning-delete-button" style="margin-top: 12px;">
                    {delete_button}
                </div>
            </div>
            <script>
                (function() {{
                    const packageId = '{package_id}';
                    const storageKey = 'captcha_attempts_' + packageId;

                    // Get current attempt count (do NOT increment on page load)
                    let attempts = parseInt(localStorage.getItem(storageKey) || '0', 10);

                    // Show warning if 2+ failed attempts
                    if (attempts >= 2) {{
                        const warningBox = document.getElementById('failed-attempts-warning');
                        if (warningBox) {{
                            warningBox.style.display = 'block';
                        }}
                    }}

                    // Function to increment attempts (call this on submit/action)
                    window.incrementCaptchaAttempts = function() {{
                        let current = parseInt(localStorage.getItem(storageKey) || '0', 10);
                        current++;
                        localStorage.setItem(storageKey, current.toString());
                        // Show warning immediately if we hit 2+ attempts
                        if (current >= 2) {{
                            const warningBox = document.getElementById('failed-attempts-warning');
                            if (warningBox) {{
                                warningBox.style.display = 'block';
                            }}
                        }}
                        return current;
                    }};

                    // Function to get current attempt count
                    window.getCaptchaAttempts = function() {{
                        return parseInt(localStorage.getItem(storageKey) || '0', 10);
                    }};

                    // Function to clear attempts (call on success)
                    window.clearCaptchaAttempts = function() {{
                        localStorage.removeItem(storageKey);
                    }};
                }})();
            </script>
        """

    @app.get("/captcha/filecrypt")
    def serve_filecrypt_fallback():
        """Dedicated FileCrypt fallback page - similar to hide/junkies/keeplinks/tolink"""
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
        original_url = payload.get("original_url")

        check_package_exists(package_id)

        url = urls[0][0] if isinstance(urls[0], (list, tuple)) else urls[0]

        # Generate userscript URL with transfer params
        base_url = request.urlparts.scheme + "://" + request.urlparts.netloc
        transfer_url = f"{base_url}/captcha/quick-transfer"

        url_with_quick_transfer_params = (
            f"{url}?"
            f"transfer_url={quote(transfer_url)}&"
            f"pkg_id={quote(package_id)}&"
            f"pkg_title={quote(title)}&"
            f"pkg_pass={quote(password)}"
        )

        package_selector = render_package_selector(package_id, title)
        failed_warning = render_failed_attempts_warning(package_id)

        source_button = ""
        if original_url:
            source_button = f"<p>{render_button('Source', 'secondary', {'onclick': f"window.open('{js_single_quoted_string_safe(original_url)}', '_blank')"})}</p>"

        return render_centered_html(f"""
        <!DOCTYPE html>
        <html>
          <body>
            <h1><img src="{images.logo}" type="image/png" alt="Quasarr logo" class="logo"/>Quasarr</h1>
            {package_selector}
            {failed_warning}

            <div>
                <!-- One-time setup section - visually separated -->
                <div id="setup-instructions" class="setup-box">
                    <h3>📦 First Time Setup:</h3>
                    <p style="margin-bottom: 8px;">
                        <a href="https://www.tampermonkey.net/" target="_blank" rel="noopener noreferrer">1. On mobile Safari/Firefox or any Desktop Browser install Tampermonkey</a>
                    </p>
                    <p style="margin-top: 0; margin-bottom: 8px;">
                        <a href="/captcha/filecrypt.user.js" target="_blank">2. Install the FileCrypt userscript</a>
                    </p>
                    <p style="margin-top: 0; margin-bottom: 12px;">
                        3. Open link, solve CAPTCHAs, and links are automatically sent back to Quasarr!
                    </p>
                    <p style="margin-top: 0;">
                        <button id="hide-setup-btn" type="button" class="btn-subtle">
                            ✅ Don't show this again
                        </button>
                    </p>
                </div>

                <!-- Hidden "show instructions" button -->
                <div id="show-instructions-link" style="display: none; margin-bottom: 16px;">
                    <button id="show-setup-btn" type="button" class="btn-subtle">
                        ℹ️ Show setup instructions
                    </button>
                </div>

                <!-- Primary action button -->
                <p>
                    {render_button("Open FileCrypt & Get Download Links", "primary", {"onclick": f"if(typeof incrementCaptchaAttempts==='function')incrementCaptchaAttempts();location.href='{url_with_quick_transfer_params}'"})}
                </p>

                <!-- Manual submission section -->
                <div class="section-divider">
                    <details id="manualSubmitDetails">
                        <summary id="manualSubmitSummary" style="cursor: pointer;">Show Manual Submission</summary>
                        <div style="margin-top: 16px;">
                            <p style="font-size: 0.9em; margin-bottom: 16px;">
                                If the userscript doesn't work, you can manually paste the links or upload a DLC file:
                            </p>
                            <form id="bypass-form" action="/captcha/bypass-submit" method="post" enctype="multipart/form-data" onsubmit="if(typeof incrementCaptchaAttempts==='function')incrementCaptchaAttempts();">
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
                        </div>
                    </details>
                </div>
            </div>

            {source_button}
            <p>
                {render_button("Delete Package", "secondary", {"onclick": f"location.href='/captcha/delete/{package_id}'"})}
            </p>
            <p>
                {render_button("Back", "secondary", {"onclick": "location.href='/'"})}
            </p>

            <script>
              // Handle manual submission toggle text
              const manualDetails = document.getElementById('manualSubmitDetails');
              const manualSummary = document.getElementById('manualSubmitSummary');

              if (manualDetails && manualSummary) {{
                manualDetails.addEventListener('toggle', () => {{
                  if (manualDetails.open) {{
                    manualSummary.textContent = 'Hide Manual Submission';
                  }} else {{
                    manualSummary.textContent = 'Show Manual Submission';
                  }}
                }});
              }}

              // Handle setup instructions hide/show
              const hideSetup = localStorage.getItem('hideFileCryptFallbackSetupInstructions');
              const setupBox = document.getElementById('setup-instructions');
              const showLink = document.getElementById('show-instructions-link');

              if (hideSetup === 'true') {{
                setupBox.style.display = 'none';
                showLink.style.display = 'block';
              }}

              // Hide setup instructions
              document.getElementById('hide-setup-btn').addEventListener('click', function() {{
                localStorage.setItem('hideFileCryptFallbackSetupInstructions', 'true');
                setupBox.style.display = 'none';
                showLink.style.display = 'block';
              }});

              // Show setup instructions again
              document.getElementById('show-setup-btn').addEventListener('click', function() {{
                localStorage.setItem('hideFileCryptFallbackSetupInstructions', 'false');
                setupBox.style.display = 'block';
                showLink.style.display = 'none';
              }});
            </script>

          </body>
        </html>""")

    @app.get("/captcha/quick-transfer")
    def handle_quick_transfer():
        """Handle quick transfer from userscript"""
        import zlib

        try:
            package_id = request.query.get("pkg_id")
            compressed_links = request.query.get("links", "")

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
                compressed_links += "=" * padding

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
                decompressed = zlib.decompress(
                    decoded, -15
                )  # -15 = raw deflate, no zlib header
            except Exception as e:
                debug(f"Decompression error: {e}, trying with header...")
                try:
                    # Fallback: try with zlib header
                    decompressed = zlib.decompress(decoded)
                except Exception as e2:
                    info(f"Decompression failed without and with header: {e2}")
                    return render_centered_html(f'''<h1><img src="{images.logo}" type="image/png" alt="Quasarr logo" class="logo"/>Quasarr</h1>
                    <p><b>Error:</b> Failed to decompress data: {str(e)}</p>
                    <p>
                        {render_button("Back", "secondary", {"onclick": "location.href='/captcha'"})}
                    </p>''')

            links_text = decompressed.decode("utf-8")

            # Parse links and restore protocols
            raw_links = [
                link.strip() for link in links_text.split("\n") if link.strip()
            ]
            links = []
            for link in raw_links:
                if not link.startswith(("http://", "https://")):
                    link = "https://" + link
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
            downloaded = shared_state.download_package(
                links, title, password, package_id
            )

            if downloaded:
                StatsHelper(shared_state).increment_package_with_links(links)
                StatsHelper(shared_state).increment_captcha_decryptions_manual()
                shared_state.get_db("protected").delete(package_id)

                info(f"Quick transfer successful: {len(links)} links processed")

                # Check if more CAPTCHAs remain
                remaining_protected = shared_state.get_db(
                    "protected"
                ).retrieve_all_titles()
                has_more_captchas = bool(remaining_protected)

                if has_more_captchas:
                    solve_button = render_button(
                        "Solve another CAPTCHA",
                        "primary",
                        {"onclick": "location.href='/captcha'"},
                    )
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
                </p>
                <script>localStorage.removeItem('captcha_attempts_{package_id}');</script>''')
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

    @app.get("/captcha/delete/<package_id>")
    def delete_captcha_package(package_id):
        success = delete_package(shared_state, package_id)

        # Check if there are more CAPTCHAs to solve after deletion
        remaining_protected = shared_state.get_db("protected").retrieve_all_titles()
        has_more_captchas = bool(remaining_protected)

        if has_more_captchas:
            solve_button = render_button(
                "Solve another CAPTCHA",
                "primary",
                {
                    "onclick": "location.href='/captcha'",
                },
            )
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
            </p>
            <script>localStorage.removeItem('captcha_attempts_{package_id}');</script>''')
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
    @app.get("/captcha/cutcaptcha")
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
        original_url = payload.get("original_url")

        check_package_exists(package_id)

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
            link_select = f"""<div id="mirrors-select">
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
            """
        else:
            link_select = f'<div id="mirrors-select">Mirror: <b>{prioritized_links[0][1]}</b></div>'

        # Pre-render button HTML in Python
        solve_another_html = render_button(
            "Solve another CAPTCHA", "primary", {"onclick": "location.href='/captcha'"}
        )
        back_button_html = render_button(
            "Back", "secondary", {"onclick": "location.href='/'"}
        )

        url = prioritized_links[0][0]

        # Add bypass section
        bypass_section = render_filecrypt_bypass_section(
            url, package_id, title, password
        )

        # Add package selector and failed attempts warning
        package_selector = render_package_selector(package_id, title)

        # Create fallback URL for the manual FileCrypt page
        fallback_payload = {
            "package_id": package_id,
            "title": title,
            "password": password,
            "mirror": desired_mirror,
            "links": prioritized_links,
            "original_url": original_url,
        }
        fallback_encoded = urlsafe_b64encode(
            json.dumps(fallback_payload).encode()
        ).decode()
        filecrypt_fallback_url = f"/captcha/filecrypt?data={quote(fallback_encoded)}"

        failed_warning = render_failed_attempts_warning(
            package_id, include_delete_button=False, fallback_url=filecrypt_fallback_url
        )  # Delete button is already below

        # Escape title for safe use in JavaScript string
        escaped_title_js = (
            title.replace("\\", "\\\\")
            .replace('"', '\\"')
            .replace("\n", "\\n")
            .replace("\r", "\\r")
        )

        source_button_html = ""
        if original_url:
            source_button_html = f"<p>{render_button('Source', 'secondary', {'onclick': f"window.open('{js_single_quoted_string_safe(original_url)}', '_blank')"})}</p>"

        content = render_centered_html(
            r'''
            <style>
                /* Fix captcha container to shrink-wrap iframe on desktop */
                .captcha-container {
                    display: inline-block;
                    background-color: var(--secondary);
                }
                #puzzle-captcha {
                    display: block;
                }
                #puzzle-captcha iframe {
                    display: block;
                }
            </style>
            <script type="text/javascript">
                // Package title for result display
                var packageTitleText = "'''
            + escaped_title_js
            + r"""";

                // Check if we should redirect to fallback due to failed attempts
                (function() {
                    const storageKey = 'captcha_attempts_"""
            + package_id
            + r"""';
                    const attempts = parseInt(localStorage.getItem(storageKey) || '0', 10);
                    if (attempts >= 2) {
                        // Redirect to FileCrypt fallback page
                        window.location.href = """
            " + filecrypt_fallback_url + r"
            ''';
                        return;
                    }
                })();

                var api_key = "'''
            + obfuscated.captcha_values()["api_key"]
            + r"""";
                var endpoint = '/' + window.location.pathname.split('/')[1] + '/' + api_key + '.html';
                var solveAnotherHtml = `<p>"""
            + solve_another_html
            + r"""</p><p>"""
            + back_button_html
            + r"""</p>`;
                var noMoreHtml = `<p><b>No more CAPTCHAs</b></p><p>"""
            + back_button_html
            + r"""</p>`;

                function handleToken(token) {
                    document.getElementById("puzzle-captcha").remove();
                    document.getElementById("mirrors-select").remove();
                    document.getElementById("delete-package-section").style.display = "none";
                    document.getElementById("back-button-section").style.display = "none";
                    document.getElementById("bypass-section").style.display = "none";
                    // Hide package selector and warning on token submission
                    var pkgSelector = document.getElementById("package-selector-section");
                    if (pkgSelector) pkgSelector.style.display = "none";
                    var warnBox = document.getElementById("failed-attempts-warning");
                    if (warnBox) warnBox.style.display = "none";

                    // Add package title to result area
                    document.getElementById("captcha-key").innerHTML = '<p style="word-break: break-all;"><b>Package:</b> ' + packageTitleText + '</p><p style="word-break: break-all;">Using result "' + token + '" to decrypt links...</p>';
                    var link = document.getElementById("link-hidden").value;
                    const fullPath = '/captcha/decrypt-filecrypt';

                    fetch(fullPath, {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                        },
                        body: JSON.stringify({ 
                            token: token,
                            """
            + f"""package_id: '{package_id}',
                            title: '{js_single_quoted_string_safe(title)}',
                            link: link,
                            password: '{password}',
                            mirror: '{desired_mirror}',
                        """
            + """})
                    })
                    .then(response => response.json())
                    .then(data => {
                        if (data.success) {
                            document.getElementById("captcha-key").insertAdjacentHTML('afterend', 
                                '<p>✅ Successful!</p>');
                            // Clear failed attempts on success
                            if (typeof clearCaptchaAttempts === 'function') {
                                clearCaptchaAttempts();
                            }
                        } else {
                            document.getElementById("captcha-key").insertAdjacentHTML('afterend', 
                                '<p>Failed. Check console for details!</p>');
                            // Increment failed attempts on failure
                            if (typeof incrementCaptchaAttempts === 'function') {
                                incrementCaptchaAttempts();
                            }
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
                """
            + obfuscated.cutcaptcha_custom_js()
            + f'''</script>
                <div>
                    <h1><img src="{images.logo}" type="image/png" alt="Quasarr logo" class="logo"/>Quasarr</h1>
                    <div id="package-selector-section">
                        {package_selector}
                    </div>
                    {failed_warning}
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
            '''
            + source_button_html
            + f"""
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
                </html>"""
        )

        return content

    @app.post("/captcha/<captcha_id>.html")
    def proxy_html(captcha_id):
        target_url = f"{obfuscated.captcha_values()['url']}/captcha/{captcha_id}.html"

        headers = {
            key: value for key, value in request.headers.items() if key != "Host"
        }
        data = request.body.read()
        resp = requests.post(target_url, headers=headers, data=data, verify=False)

        response.content_type = resp.headers.get("Content-Type")

        content = resp.text
        content = re.sub(
            r"""<script\s+src="/(jquery(?:-ui|\.ui\.touch-punch\.min)?\.js)(?:\?[^"]*)?"></script>""",
            r"""<script src="/captcha/js/\1"></script>""",
            content,
        )

        response.content_type = "text/html"
        return content

    @app.post("/captcha/<captcha_id>.json")
    def proxy_json(captcha_id):
        target_url = f"{obfuscated.captcha_values()['url']}/captcha/{captcha_id}.json"

        headers = {
            key: value for key, value in request.headers.items() if key != "Host"
        }
        data = request.body.read()
        resp = requests.post(target_url, headers=headers, data=data, verify=False)

        response.content_type = resp.headers.get("Content-Type")
        return resp.content

    @app.get("/captcha/js/<filename>")
    def serve_local_js(filename):
        upstream = f"{obfuscated.captcha_values()['url']}/{filename}"
        try:
            upstream_resp = requests.get(upstream, verify=False, stream=True)
            upstream_resp.raise_for_status()
        except requests.RequestException as e:
            response.status = 502
            return f"/* Error proxying {filename}: {e} */"

        response.content_type = "application/javascript"
        return upstream_resp.iter_content(chunk_size=8192)

    @app.get("/captcha/<captcha_id>/<uuid>/<filename>")
    def proxy_pngs(captcha_id, uuid, filename):
        new_url = f"{obfuscated.captcha_values()['url']}/captcha/{captcha_id}/{uuid}/{filename}"

        try:
            external_response = requests.get(new_url, stream=True, verify=False)
            external_response.raise_for_status()
            response.content_type = "image/png"
            response.headers["Content-Disposition"] = f'inline; filename="{filename}"'
            return external_response.iter_content(chunk_size=8192)

        except requests.RequestException as e:
            response.status = 502
            return f"Error fetching resource: {e}"

    @app.post("/captcha/<captcha_id>/check")
    def proxy_check(captcha_id):
        new_url = f"{obfuscated.captcha_values()['url']}/captcha/{captcha_id}/check"
        headers = {key: value for key, value in request.headers.items()}

        data = request.body.read()
        resp = requests.post(new_url, headers=headers, data=data, verify=False)

        response.status = resp.status_code
        for header in resp.headers:
            if header.lower() not in [
                "content-encoding",
                "transfer-encoding",
                "content-length",
                "connection",
            ]:
                response.set_header(header, resp.headers[header])
        return resp.content

    @app.post("/captcha/bypass-submit")
    def handle_bypass_submit():
        """Handle bypass submission with either links or DLC file"""
        try:
            package_id = request.forms.get("package_id")
            title = request.forms.get("title")
            password = request.forms.get("password", "")
            links_input = request.forms.get("links", "").strip()
            dlc_upload = request.files.get("dlc_file")

            if not package_id or not title:
                return render_centered_html(f'''<h1><img src="{images.logo}" type="image/png" alt="Quasarr logo" class="logo"/>Quasarr</h1>
                <p><b>Error:</b> Missing package information.</p>
                <p>
                    {render_button("Back", "secondary", {"onclick": "location.href='/captcha'"})}
                </p>''')

            check_package_exists(package_id)

            # Process links input
            if links_input:
                info(f"Processing direct links bypass for {title}")
                raw_links = [
                    link.strip() for link in links_input.split("\n") if link.strip()
                ]
                links = [
                    l
                    for l in raw_links
                    if l.lower().startswith(("http://", "https://"))
                ]

                info(
                    f"Received {len(links)} valid direct download links "
                    f"(from {len(raw_links)} provided)"
                )

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
                downloaded = shared_state.download_package(
                    links, title, password, package_id
                )
                if downloaded:
                    StatsHelper(shared_state).increment_package_with_links(links)
                    StatsHelper(shared_state).increment_captcha_decryptions_manual()
                    shared_state.get_db("protected").delete(package_id)

                    # Check if there are more CAPTCHAs to solve
                    remaining_protected = shared_state.get_db(
                        "protected"
                    ).retrieve_all_titles()
                    has_more_captchas = bool(remaining_protected)

                    if has_more_captchas:
                        solve_button = render_button(
                            "Solve another CAPTCHA",
                            "primary",
                            {
                                "onclick": "location.href='/captcha'",
                            },
                        )
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
                    </p>
                    <script>localStorage.removeItem('captcha_attempts_{package_id}');</script>''')
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

    @app.post("/captcha/decrypt-filecrypt")
    def submit_token():
        protected = shared_state.get_db("protected").retrieve_all_titles()
        if not protected:
            return {
                "success": False,
                "title": "No protected packages found! CAPTCHA not needed.",
            }

        links = []
        title = "Unknown Package"
        try:
            data = request.json
            token = data.get("token")
            package_id = data.get("package_id")
            title = data.get("title")
            link = data.get("link")
            password = data.get("password")
            mirror = None if (mirror := data.get("mirror")) == "None" else mirror

            if token:
                info(f"Received token: {token}")
                info(f"Decrypting links for {title}")
                decrypted = get_filecrypt_links(
                    shared_state, token, title, link, password=password, mirror=mirror
                )
                if decrypted:
                    links = decrypted.get("links", [])
                    info(f"Decrypted {len(links)} download links for {title}")
                    if not links:
                        raise ValueError("No download links found after decryption")
                    downloaded = shared_state.download_package(
                        links, title, password, package_id
                    )
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

        return {
            "success": success,
            "title": title,
            "has_more_captchas": has_more_captchas,
        }
