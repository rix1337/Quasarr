# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import json
import re
from base64 import b64encode, urlsafe_b64decode, urlsafe_b64encode
from io import BytesIO
from urllib.parse import quote, unquote

import requests
from bottle import HTTPResponse, redirect, request, response
from PIL import Image

import quasarr.providers.html_images as images
from quasarr.api.jdownloader import get_jdownloader_disconnected_page
from quasarr.downloads import submit_final_download_urls
from quasarr.downloads.linkcrypters.filecrypt import (
    DLC,
    get_filecrypt_links,
    inspect_filecrypt_captcha,
    prepare_filecrypt_circle_captcha,
)
from quasarr.downloads.packages import delete_package
from quasarr.providers import obfuscated, shared_state
from quasarr.providers.auth import public_endpoint
from quasarr.providers.html_templates import render_button, render_centered_html
from quasarr.providers.log import debug, error, info, trace
from quasarr.providers.statistics import StatsHelper
from quasarr.storage.categories import (
    get_download_category_from_package_id,
    get_download_category_mirrors,
)
from quasarr.storage.config import Config


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
                    {render_button("Back", "secondary", {"onclick": "location.href='/'"})}
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
            return get_jdownloader_disconnected_page(shared_state)

        protected = shared_state.get_db("protected").retrieve_all_titles()
        if not protected:
            return render_centered_html(f'''<h1><img src="{images.logo}" type="image/webp" alt="Quasarr logo" class="logo"/>Quasarr</h1>
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
            has_filecrypt_links = any(
                (
                    "filecrypt." in link[0]
                    if isinstance(link, (list, tuple))
                    else "filecrypt." in link
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
            elif has_filecrypt_links:
                debug("Redirecting to FileCrypt challenge page")
                redirect(f"/captcha/filecrypt?data={quote(encoded_payload)}")
            else:
                debug("Redirecting to cutcaptcha")
                redirect(f"/captcha/cutcaptcha?data={quote(encoded_payload)}")

            return render_centered_html(f'''<h1><img src="{images.logo}" type="image/webp" alt="Quasarr logo" class="logo"/>Quasarr</h1>
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

    def encode_payload(payload):
        return urlsafe_b64encode(json.dumps(payload).encode()).decode()

    def render_captcha_success_page(title, link_count, package_id):
        remaining_protected = shared_state.get_db("protected").retrieve_all_titles()
        if remaining_protected:
            solve_button = render_button(
                "Solve another CAPTCHA",
                "primary",
                {"onclick": "location.href='/captcha'"},
            )
        else:
            solve_button = "<b>No more CAPTCHAs</b>"

        return render_centered_html(f'''<h1><img src="{images.logo}" type="image/webp" alt="Quasarr logo" class="logo"/>Quasarr</h1>
        <p><b>✅ CAPTCHA solved and submitted to JDownloader.</b></p>
        <p style="word-break: break-all;"><b>Package:</b> {title}</p>
        <p>{link_count} link(s) processed.</p>
        <p>{solve_button}</p>
        <p>{render_button("Back", "secondary", {"onclick": "location.href='/'"})}</p>
        <script>localStorage.removeItem('captcha_attempts_{package_id}');</script>''')

    def render_filecrypt_loading_redirect(target_url, title, status_text):
        return render_centered_html(f"""
            <style>
                .filecrypt-skeleton {{
                    max-width: 370px;
                    margin: 34px auto 0 auto;
                }}
                .filecrypt-skeleton-line {{
                    height: 18px;
                    border-radius: 6px;
                    margin: 10px auto;
                    background: linear-gradient(90deg, rgba(128,128,128,0.18), rgba(128,128,128,0.32), rgba(128,128,128,0.18));
                    background-size: 200% 100%;
                    animation: filecryptSkeleton 1.1s ease-in-out infinite;
                }}
                .filecrypt-skeleton-line.short {{ width: 55%; }}
                .filecrypt-skeleton-line.long {{ width: 82%; }}
                @keyframes filecryptSkeleton {{
                    0% {{ background-position: 200% 0; }}
                    100% {{ background-position: -200% 0; }}
                }}
            </style>
            <h1><img src="{images.logo}" type="image/webp" alt="Quasarr logo" class="logo"/>Quasarr</h1>
            <p style="word-break: break-all;"><b>Package:</b> {title}</p>
            <p>{status_text}</p>
            <div class="filecrypt-skeleton" aria-label="{status_text}">
                <div class="filecrypt-skeleton-line long"></div>
                <div class="filecrypt-skeleton-line short"></div>
            </div>
            <script>
                window.location.replace('{js_single_quoted_string_safe(target_url)}');
            </script>
        """)

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

        extra_params = ""
        if provider_type == "junkies":
            junkies_user = Config("JUNKIES").get("user")
            junkies_pass = Config("JUNKIES").get("password")
            if junkies_user and junkies_pass:
                extra_params = (
                    f"&jk_user={quote(junkies_user)}&jk_pass={quote(junkies_pass)}"
                )

        url_with_quick_transfer_params = (
            f"{url}?"
            f"transfer_url={quote(transfer_url)}&"
            f"pkg_id={quote(package_id)}&"
            f"pkg_title={quote(title)}&"
            f"pkg_pass={quote(password)}"
            f"{extra_params}"
        )

        js_url = url_with_quick_transfer_params.replace("'", "\\'")
        js_userscript_url = userscript_url.replace("'", "\\'")
        js_provider_name = provider_name.replace("'", "\\'")

        return f'''
            <div>
                <!-- Primary action - the quick transfer link -->
                <p>
                    {render_button(f"Open {provider_name} & Get Download Links", "primary", {"onclick": f"handleProviderClick('{js_url}', '{storage_key}', '{js_provider_name}', '{js_userscript_url}')"})}
                </p>

                <!-- Reset tutorial button -->
                <p id="reset-tutorial-btn" style="display: none;">
                    <button type="button" class="btn-subtle" onclick="localStorage.removeItem('{storage_key}'); showModal('Tutorial Reset', '<p>Tutorial reset! Click the Open button to see it again.</p>', '<button class=\\'btn-primary\\' onclick=\\'location.reload()\\'>Reload</button>');">
                        ℹ️ Reset Setup Guide
                    </button>
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

              // Show reset button if tutorial was already seen
              if (localStorage.getItem('{storage_key}') === 'true') {{
                  document.getElementById('reset-tutorial-btn').style.display = 'block';
              }}

              // Global handler for provider clicks
              if (!window.handleProviderClick) {{
                  window.handleProviderClick = function(url, storageKey, providerName, userscriptUrl) {{
                    if (localStorage.getItem(storageKey) === 'true') {{
                        if(typeof incrementCaptchaAttempts==='function') incrementCaptchaAttempts();
                        window.location.href = url;
                        return;
                    }}

                    const content = `
                        <p style="margin-bottom: 8px;">
                            <a href="https://www.tampermonkey.net/" target="_blank" rel="noopener noreferrer">1. On mobile Safari/Firefox or any Desktop Browser install Tampermonkey</a>
                        </p>
                        <p style="margin-top: 0; margin-bottom: 8px;">
                            <a href="${{userscriptUrl}}" target="_blank">2. Install the ${{providerName}} userscript</a>
                        </p>
                        <p style="margin-top: 0; margin-bottom: 12px;">
                            3. Open link, solve CAPTCHAs, and links are automatically sent back to Quasarr!
                        </p>
                    `;

                    const btnId = 'modal-proceed-btn-' + Math.floor(Math.random() * 10000);
                    const buttons = `
                        <button id="${{btnId}}" class="btn-primary" disabled>Wait 5s...</button>
                        <button class="btn-secondary" onclick="closeModal()">Cancel</button>
                    `;

                    showModal('📦 First Time Setup', content, buttons);

                    let count = 5;
                    const btn = document.getElementById(btnId);
                    const interval = setInterval(() => {{
                        count--;
                        if (count <= 0) {{
                            clearInterval(interval);
                            btn.innerText = 'I have installed Tampermonkey and the userscript';
                            btn.disabled = false;
                            btn.onclick = function() {{
                                localStorage.setItem(storageKey, 'true');
                                closeModal();
                                if(typeof incrementCaptchaAttempts==='function') incrementCaptchaAttempts();
                                window.location.href = url;
                            }};
                        }} else {{
                            btn.innerText = 'Wait ' + count + 's...';
                        }}
                    }}, 1000);
                  }};
              }}
            </script>
        '''

    @app.get("/captcha/hide")
    def serve_hide_captcha():
        payload = decode_payload()

        if "error" in payload:
            return render_centered_html(f'''<h1><img src="{images.logo}" type="image/webp" alt="Quasarr logo" class="logo"/>Quasarr</h1>
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
        failed_warning = render_failed_attempts_warning(package_id, title=title)

        source_button = ""
        if original_url:
            source_button = f"<p>{render_button('Source', 'secondary', {'onclick': f"window.open('{js_single_quoted_string_safe(original_url)}', '_blank')"})}</p>"

        return render_centered_html(f"""
        <!DOCTYPE html>
        <html>
          <body>
            <h1><img src="{images.logo}" type="image/webp" alt="Quasarr logo" class="logo"/>Quasarr</h1>
            {package_selector}
            {failed_warning}
                {render_userscript_section(url, package_id, title, password, "hide")}
            {source_button}
            <p>
                {render_button("Delete Package", "secondary", {"onclick": f"location.href='/captcha/delete/{package_id}?title={quote(title)}'"})}
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
            return render_centered_html(f'''<h1><img src="{images.logo}" type="image/webp" alt="Quasarr logo" class="logo"/>Quasarr</h1>
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
        failed_warning = render_failed_attempts_warning(package_id, title=title)

        source_button = ""
        if original_url:
            source_button = f"<p>{render_button('Source', 'secondary', {'onclick': f"window.open('{js_single_quoted_string_safe(original_url)}', '_blank')"})}</p>"

        return render_centered_html(f"""
        <!DOCTYPE html>
        <html>
          <body>
            <h1><img src="{images.logo}" type="image/webp" alt="Quasarr logo" class="logo"/>Quasarr</h1>
            {package_selector}
            {failed_warning}
                {render_userscript_section(url, package_id, title, password, "junkies")}
            {source_button}
            <p>
                {render_button("Delete Package", "secondary", {"onclick": f"location.href='/captcha/delete/{package_id}?title={quote(title)}'"})}
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
            return render_centered_html(f'''<h1><img src="{images.logo}" type="image/webp" alt="Quasarr logo" class="logo"/>Quasarr</h1>
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
        failed_warning = render_failed_attempts_warning(package_id, title=title)

        source_button = ""
        if original_url:
            source_button = f"<p>{render_button('Source', 'secondary', {'onclick': f"window.open('{js_single_quoted_string_safe(original_url)}', '_blank')"})}</p>"

        return render_centered_html(f"""
        <!DOCTYPE html>
        <html>
          <body>
            <h1><img src="{images.logo}" type="image/webp" alt="Quasarr logo" class="logo"/>Quasarr</h1>
            {package_selector}
            {failed_warning}
                {render_userscript_section(url, package_id, title, password, "keeplinks")}
            {source_button}
            <p>
                {render_button("Delete Package", "secondary", {"onclick": f"location.href='/captcha/delete/{package_id}?title={quote(title)}'"})}
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
            return render_centered_html(f'''<h1><img src="{images.logo}" type="image/webp" alt="Quasarr logo" class="logo"/>Quasarr</h1>
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
        failed_warning = render_failed_attempts_warning(package_id, title=title)

        source_button = ""
        if original_url:
            source_button = f"<p>{render_button('Source', 'secondary', {'onclick': f"window.open('{js_single_quoted_string_safe(original_url)}', '_blank')"})}</p>"

        return render_centered_html(f"""
        <!DOCTYPE html>
        <html>
          <body>
            <h1><img src="{images.logo}" type="image/webp" alt="Quasarr logo" class="logo"/>Quasarr</h1>
            {package_selector}
            {failed_warning}
                {render_userscript_section(url, package_id, title, password, "tolink")}
            {source_button}
            <p>
                {render_button("Delete Package", "secondary", {"onclick": f"location.href='/captcha/delete/{package_id}?title={quote(title)}'"})}
            </p>
            <p>
                {render_button("Back", "secondary", {"onclick": "location.href='/'"})}
            </p>

          </body>
        </html>""")

    @app.get("/captcha/filecrypt.user.js")
    @public_endpoint
    def serve_filecrypt_user_js():
        content = obfuscated.filecrypt_user_js()
        response.content_type = "application/javascript"
        return content

    @app.get("/captcha/hide.user.js")
    @public_endpoint
    def serve_hide_user_js():
        content = obfuscated.hide_user_js()
        response.content_type = "application/javascript"
        return content

    @app.get("/captcha/junkies.user.js")
    @public_endpoint
    def serve_junkies_user_js():
        sj = shared_state.values["config"]("Hostnames").get("sj")
        dj = shared_state.values["config"]("Hostnames").get("dj")

        content = obfuscated.junkies_user_js(sj, dj)
        response.content_type = "application/javascript"
        return content

    @app.get("/captcha/keeplinks.user.js")
    @public_endpoint
    def serve_keeplinks_user_js():
        content = obfuscated.keeplinks_user_js()
        response.content_type = "application/javascript"
        return content

    @app.get("/captcha/tolink.user.js")
    @public_endpoint
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

        js_url = url_with_quick_transfer_params.replace("'", "\\'")
        storage_key = "hideFileCryptSetupInstructions"
        provider_name = "FileCrypt"
        userscript_url = "/captcha/filecrypt.user.js"

        return f'''
            <div class="section-divider" style="max-width: 370px; margin-left: auto; margin-right: auto;">
                <details id="bypassDetails">
                <summary id="bypassSummary">Show CAPTCHA Bypass</summary><br>

                    <!-- Primary action button -->
                    <p>
                        {render_button("Open FileCrypt & Get Download Links", "primary", {"onclick": f"handleProviderClick('{js_url}', '{storage_key}', '{provider_name}', '{userscript_url}')"})}
                    </p>

                    <!-- Reset tutorial button -->
                    <p id="reset-tutorial-btn" style="display: none;">
                        <button type="button" class="btn-subtle" onclick="localStorage.removeItem('{storage_key}'); showModal('Tutorial Reset', '<p>Tutorial reset! Click the Open button to see it again.</p>', '<button class=\\'btn-primary\\' onclick=\\'location.reload()\\'>Reload</button>');">
                            ℹ️ Reset Setup Guide
                        </button>
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

              // Show reset button if tutorial was already seen
              if (localStorage.getItem('{storage_key}') === 'true') {{
                  document.getElementById('reset-tutorial-btn').style.display = 'block';
              }}

              // Global handler for provider clicks (if not already defined)
              if (!window.handleProviderClick) {{
                  window.handleProviderClick = function(url, storageKey, providerName, userscriptUrl) {{
                    if (localStorage.getItem(storageKey) === 'true') {{
                        if(typeof incrementCaptchaAttempts==='function') incrementCaptchaAttempts();
                        window.location.href = url;
                        return;
                    }}

                    const content = `
                        <p style="margin-bottom: 8px;">
                            <a href="https://www.tampermonkey.net/" target="_blank" rel="noopener noreferrer">1. On mobile Safari/Firefox or any Desktop Browser install Tampermonkey</a>
                        </p>
                        <p style="margin-top: 0; margin-bottom: 8px;">
                            <a href="${{userscriptUrl}}" target="_blank">2. Install the ${{providerName}} userscript</a>
                        </p>
                        <p style="margin-top: 0; margin-bottom: 12px;">
                            3. Open link, solve CAPTCHAs, and links are automatically sent back to Quasarr!
                        </p>
                    `;

                    const btnId = 'modal-proceed-btn-' + Math.floor(Math.random() * 10000);
                    const buttons = `
                        <button id="${{btnId}}" class="btn-primary" disabled>Wait 5s...</button>
                        <button class="btn-secondary" onclick="closeModal()">Cancel</button>
                    `;

                    showModal('📦 First Time Setup', content, buttons);

                    let count = 5;
                    const btn = document.getElementById(btnId);
                    const interval = setInterval(() => {{
                        count--;
                        if (count <= 0) {{
                            clearInterval(interval);
                            btn.innerText = 'I have installed Tampermonkey and the userscript';
                            btn.disabled = false;
                            btn.onclick = function() {{
                                localStorage.setItem(storageKey, 'true');
                                closeModal();
                                if(typeof incrementCaptchaAttempts==='function') incrementCaptchaAttempts();
                                window.location.href = url;
                            }};
                        }} else {{
                            btn.innerText = 'Wait ' + count + 's...';
                        }}
                    }}, 1000);
                  }};
              }}
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
            has_filecrypt = any(
                ("filecrypt." in (l[0] if isinstance(l, (list, tuple)) else l))
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
            elif has_filecrypt:
                return "filecrypt"
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
            display_title = title
            options.append(
                f'<option value="{captcha_type}|{quote(encoded)}" {selected}>{display_title}</option>'
            )

        options_html = "\n".join(options)

        return f"""
            <div class="package-selector" style="margin-bottom: 20px; padding: 12px; background: rgba(128, 128, 128, 0.1); border: 1px solid rgba(128, 128, 128, 0.3); border-radius: 8px;">
                <label for="package-select" style="display: block; margin-bottom: 8px; font-weight: bold;">📦 Select Package:</label>
                <select id="package-select" style="width: 100%; padding: 8px; border-radius: 4px; background: inherit; color: inherit; border: 1px solid rgba(128, 128, 128, 0.5); cursor: pointer; text-overflow: ellipsis; white-space: nowrap; overflow: hidden;">
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
        package_id, title=None, include_delete_button=True, fallback_url=None
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
            delete_url = f"/captcha/delete/{package_id}"
            if title:
                delete_url += f"?title={quote(title)}"

            delete_button = render_button(
                "Delete Package",
                "primary",
                {"onclick": f"location.href='{delete_url}'"},
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

    @app.get("/captcha/filecrypt/manual")
    def serve_filecrypt_fallback():
        """Dedicated FileCrypt fallback page - similar to hide/junkies/keeplinks/tolink"""
        payload = decode_payload()

        if "error" in payload:
            return render_centered_html(f'''<h1><img src="{images.logo}" type="image/webp" alt="Quasarr logo" class="logo"/>Quasarr</h1>
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
        failed_warning = render_failed_attempts_warning(package_id, title=title)
        unknown_warning = """
            <div id="filecrypt-unknown-warning" style="max-width: 370px; margin: 0 auto 20px auto; padding: 14px; background: rgba(220, 53, 69, 0.14); border: 2px solid #dc3545; border-radius: 8px; color: #b02a37;">
                <p style="margin: 0;"><b>FileCrypt challenge not recognized.</b></p>
                <p style="margin: 8px 0 0 0;">Quasarr could not match this page to CutCaptcha, Circle-Captcha, proof-of-work, or a no-CAPTCHA link page. Use the FileCrypt userscript flow below.</p>
            </div>
        """

        source_button = ""
        if original_url:
            source_button = f"<p>{render_button('Source', 'secondary', {'onclick': f"window.open('{js_single_quoted_string_safe(original_url)}', '_blank')"})}</p>"

        js_url = url_with_quick_transfer_params.replace("'", "\\'")
        storage_key = "hideFileCryptFallbackSetupInstructions"
        provider_name = "FileCrypt"
        userscript_url = "/captcha/filecrypt.user.js"

        return render_centered_html(f"""
        <!DOCTYPE html>
        <html>
          <body>
            <h1><img src="{images.logo}" type="image/webp" alt="Quasarr logo" class="logo"/>Quasarr</h1>
            {package_selector}
            {failed_warning}
            {unknown_warning}

            <div>
                <!-- Primary action button -->
                <p>
                    {render_button("Open FileCrypt & Get Download Links", "primary", {"onclick": f"handleProviderClick('{js_url}', '{storage_key}', '{provider_name}', '{userscript_url}')"})}
                </p>

                <!-- Reset tutorial button -->
                <p id="reset-tutorial-btn" style="display: none;">
                    <button type="button" class="btn-subtle" onclick="localStorage.removeItem('{storage_key}'); showModal('Tutorial Reset', '<p>Tutorial reset! Click the Open button to see it again.</p>', '<button class=\\'btn-primary\\' onclick=\\'location.reload()\\'>Reload</button>');">
                        ℹ️ Reset Setup Guide
                    </button>
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
                {render_button("Delete Package", "secondary", {"onclick": f"location.href='/captcha/delete/{package_id}?title={quote(title)}'"})}
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

              // Show reset button if tutorial was already seen
              if (localStorage.getItem('{storage_key}') === 'true') {{
                  document.getElementById('reset-tutorial-btn').style.display = 'block';
              }}

              // Global handler for provider clicks
              window.handleProviderClick = function(url, storageKey, providerName, userscriptUrl) {{
                if (localStorage.getItem(storageKey) === 'true') {{
                    if(typeof incrementCaptchaAttempts==='function') incrementCaptchaAttempts();
                    window.location.href = url;
                    return;
                }}

                const content = `
                    <p style="margin-bottom: 8px;">
                        <a href="https://www.tampermonkey.net/" target="_blank" rel="noopener noreferrer">1. On mobile Safari/Firefox or any Desktop Browser install Tampermonkey</a>
                    </p>
                    <p style="margin-top: 0; margin-bottom: 8px;">
                        <a href="${{userscriptUrl}}" target="_blank">2. Install the ${{providerName}} userscript</a>
                    </p>
                    <p style="margin-top: 0; margin-bottom: 12px;">
                        3. Open link, solve CAPTCHAs, and links are automatically sent back to Quasarr!
                    </p>
                `;

                const btnId = 'modal-proceed-btn-' + Math.floor(Math.random() * 10000);
                const buttons = `
                    <button id="${{btnId}}" class="btn-primary" disabled>Wait 5s...</button>
                    <button class="btn-secondary" onclick="closeModal()">Cancel</button>
                `;

                showModal('📦 First Time Setup', content, buttons);

                let count = 5;
                const btn = document.getElementById(btnId);
                const interval = setInterval(() => {{
                    count--;
                    if (count <= 0) {{
                        clearInterval(interval);
                        btn.innerText = 'I have installed Tampermonkey and the userscript';
                        btn.disabled = false;
                        btn.onclick = function() {{
                            localStorage.setItem(storageKey, 'true');
                            closeModal();
                            if(typeof incrementCaptchaAttempts==='function') incrementCaptchaAttempts();
                            window.location.href = url;
                        }};
                    }} else {{
                        btn.innerText = 'Wait ' + count + 's...';
                    }}
                }}, 1000);
              }};
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
                return render_centered_html(f'''<h1><img src="{images.logo}" type="image/webp" alt="Quasarr logo" class="logo"/>Quasarr</h1>
                <p><b>Error:</b> Missing parameters</p>
                <p>
                    {render_button("Back", "secondary", {"onclick": "location.href='/'"})}
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
                return render_centered_html(f'''<h1><img src="{images.logo}" type="image/webp" alt="Quasarr logo" class="logo"/>Quasarr</h1>
                <p><b>Error:</b> Failed to decode data: {str(e)}</p>
                <p>
                    {render_button("Back", "secondary", {"onclick": "location.href='/'"})}
                </p>''')

            # Decompress using zlib - use raw deflate format (no header)
            try:
                decompressed = zlib.decompress(
                    decoded, -15
                )  # -15 = raw deflate, no zlib header
            except Exception as e:
                trace(f"Decompression error: {e}, trying with header...")
                try:
                    # Fallback: try with zlib header
                    decompressed = zlib.decompress(decoded)
                except Exception as e2:
                    info(f"Decompression failed without and with header: {e2}")
                    return render_centered_html(f'''<h1><img src="{images.logo}" type="image/webp" alt="Quasarr logo" class="logo"/>Quasarr</h1>
                    <p><b>Error:</b> Failed to decompress data: {str(e)}</p>
                    <p>
                        {render_button("Back", "secondary", {"onclick": "location.href='/'"})}
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

            debug(
                f"Quick transfer received <green>{len(links)}</green> links for package <y>{package_id}</y>"
            )

            # Get package info
            raw_data = shared_state.get_db("protected").retrieve(package_id)
            if not raw_data:
                return render_centered_html(f'''<h1><img src="{images.logo}" type="image/webp" alt="Quasarr logo" class="logo"/>Quasarr</h1>
                <p><b>Error:</b> Package not found</p>
                <p>
                    {render_button("Back", "secondary", {"onclick": "location.href='/'"})}
                </p>''')

            data = json.loads(raw_data)
            title = data.get("title", "Unknown")
            password = data.get("password", "")

            # Download the package
            submit_result = submit_final_download_urls(
                shared_state,
                links,
                title,
                password,
                package_id,
                remove_protected=True,
                notification_details={"method": "manual"},
            )

            if submit_result["success"]:
                final_links = submit_result["links"]
                StatsHelper(shared_state).increment_package_with_links(final_links)
                StatsHelper(shared_state).increment_captcha_decryptions_manual()

                info(
                    f"Quick transfer successful: <g>{len(final_links)}</g> links processed"
                )

                return render_captcha_success_page(title, len(final_links), package_id)
            else:
                StatsHelper(shared_state).increment_failed_decryptions_manual()
                if submit_result.get("persisted_failure"):
                    return render_centered_html(f'''<h1><img src="{images.logo}" type="image/webp" alt="Quasarr logo" class="logo"/>Quasarr</h1>
                    <p><b>Package marked as failed.</b></p>
                    <p>{submit_result["reason"]}</p>
                    <p>
                        {render_button("Back", "secondary", {"onclick": "location.href='/'"})}
                    </p>''')
                return render_centered_html(f'''<h1><img src="{images.logo}" type="image/webp" alt="Quasarr logo" class="logo"/>Quasarr</h1>
                <p><b>Error:</b> Failed to submit package to JDownloader</p>
                <p>
                    {render_button("Try Again", "secondary", {"onclick": "location.href='/captcha'"})}
                </p>''')

        except Exception as e:
            error(f"Quick transfer error: {e}")
            return render_centered_html(f'''<h1><img src="{images.logo}" type="image/webp" alt="Quasarr logo" class="logo"/>Quasarr</h1>
            <p><b>Error:</b> {str(e)}</p>
            <p>
                {render_button("Back", "secondary", {"onclick": "location.href='/'"})}
            </p>''')

    @app.get("/captcha/delete/<package_id>")
    def delete_captcha_package(package_id):
        title = request.query.get("title")
        success = delete_package(shared_state, package_id, title)

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
            return render_centered_html(f'''<h1><img src="{images.logo}" type="image/webp" alt="Quasarr logo" class="logo"/>Quasarr</h1>
            <p>Package successfully deleted!</p>
            <p>
                {solve_button}
            </p>
            <p>
                {render_button("Back", "secondary", {"onclick": "location.href='/'"})}
            </p>
            <script>localStorage.removeItem('captcha_attempts_{package_id}');</script>''')
        else:
            return render_centered_html(f'''<h1><img src="{images.logo}" type="image/webp" alt="Quasarr logo" class="logo"/>Quasarr</h1>
            <p>Failed to delete package!</p>
            <p>
                {solve_button}
            </p>
            <p>
                {render_button("Back", "secondary", {"onclick": "location.href='/'"})}
            </p>''')

    # The following routes are for FileCrypt challenge handling
    @app.get("/captcha/cutcaptcha-loader.js")
    def serve_cutcaptcha_loader_js():
        response.content_type = "application/javascript"
        return obfuscated.cutcaptcha_custom_js()

    @app.post("/captcha/filecrypt-status")
    def check_filecrypt_status():
        data = request.json or {}
        link = data.get("link")
        password = data.get("password")

        if not link:
            response.status = 400
            return {"captcha_type": "unknown", "error": "Missing link"}

        try:
            status = inspect_filecrypt_captcha(shared_state, link, password=password)
            return status
        except Exception as e:
            info(f"Error checking Filecrypt challenge: {e}")
            response.status = 500
            return {"captcha_type": "unknown", "error": str(e)}

    @app.get("/captcha/circle")
    def serve_circle_captcha():
        circle_payload = {}
        if request.query.get("data"):
            circle_payload = decode_payload()
            if "error" in circle_payload:
                circle_payload = {}

        package_id = circle_payload.get("package_id") or request.query.get("package_id")
        url = circle_payload.get("url") or request.query.get("url")
        incoming_cookies = circle_payload.get("cookies") or []

        if not package_id or not url:
            response.status = 400
            return render_centered_html(f'''<h1><img src="{images.logo}" type="image/webp" alt="Quasarr logo" class="logo"/>Quasarr</h1>
            <p><b>Error:</b> Missing Circle-Captcha parameters.</p>
            <p>{render_button("Back", "secondary", {"onclick": "location.href='/'"})}</p>''')

        check_package_exists(package_id)
        package_data = json.loads(shared_state.get_db("protected").retrieve(package_id))
        title = package_data.get("title", "Unknown Package")
        password = package_data.get("password", "")
        links = package_data.get("links", [])
        desired_mirror = package_data.get("mirror")
        original_url = package_data.get("original_url")

        try:
            circle = prepare_filecrypt_circle_captcha(
                shared_state,
                url,
                password=password,
                cookies=incoming_cookies,
            )
        except Exception as e:
            info(f"Error preparing Filecrypt Circle-Captcha: {e}")
            return render_centered_html(f'''<h1><img src="{images.logo}" type="image/webp" alt="Quasarr logo" class="logo"/>Quasarr</h1>
            <p><b>Error:</b> Could not load Filecrypt Circle-Captcha.</p>
            <p>{render_button("Try Again", "secondary", {"onclick": "location.href='/captcha'"})}</p>''')

        image_data = b64encode(circle["image"]).decode("ascii")
        with Image.open(BytesIO(circle["image"])) as captcha_image:
            image_width, image_height = captcha_image.size

        cookies_payload = urlsafe_b64encode(
            json.dumps(circle["cookies"]).encode()
        ).decode()
        package_selector = render_package_selector(package_id, title)
        failed_warning = render_failed_attempts_warning(
            package_id,
            title=title,
            include_delete_button=False,
        )

        link_options = ""
        filecrypt_links = [
            link
            for link in links
            if "filecrypt." in (link[0] if isinstance(link, (list, tuple)) else link)
        ]
        if len(filecrypt_links) > 1:
            for link in filecrypt_links:
                link_url = link[0] if isinstance(link, (list, tuple)) else link
                link_label = (
                    link[1] if isinstance(link, (list, tuple)) and len(link) > 1 else ""
                )
                prioritized = [link] + [other for other in links if other != link]
                mirror_payload = {
                    "package_id": package_id,
                    "title": title,
                    "password": password,
                    "mirror": desired_mirror,
                    "links": prioritized,
                    "original_url": original_url,
                }
                encoded = urlsafe_b64encode(
                    json.dumps(mirror_payload).encode()
                ).decode()
                selected = "selected" if link_url == url else ""
                link_options += (
                    f'<option value="{quote(encoded)}" {selected}>{link_label}</option>'
                )

            link_select = f"""<div id="mirrors-select">
                    <label for="link-select">Mirror:</label>
                    <select id="link-select">
                        {link_options}
                    </select>
                </div>
                <script>
                    document.getElementById("link-select").addEventListener("change", function() {{
                        window.location.href = '/captcha/filecrypt?data=' + this.value;
                    }});
                </script>
            """
        elif filecrypt_links:
            first_link = filecrypt_links[0]
            link_label = (
                first_link[1]
                if isinstance(first_link, (list, tuple)) and len(first_link) > 1
                else "filecrypt"
            )
            link_select = f'<div id="mirrors-select">Mirror: <b>{link_label}</b></div>'
        else:
            link_select = ""

        source_button = ""
        if original_url:
            source_button = f"<p>{render_button('Source', 'secondary', {'onclick': f"window.open('{js_single_quoted_string_safe(original_url)}', '_blank')"})}</p>"
        bypass_section = render_filecrypt_bypass_section(
            circle["url"],
            package_id,
            title,
            password,
        )

        return render_centered_html(f"""
            <style>
                .circle-captcha-scroll {{
                    overflow-x: auto;
                    max-width: 100%;
                    margin: 16px auto;
                    text-align: center;
                }}
                .circle-captcha-image {{
                    display: block;
                    width: {image_width}px !important;
                    height: {image_height}px !important;
                    max-width: none !important;
                    margin: 0 auto !important;
                    padding: 0 !important;
                    border: 0 !important;
                    border-radius: 0 !important;
                    background: transparent !important;
                    cursor: crosshair;
                }}
                .filecrypt-skeleton {{
                    max-width: 370px;
                    margin: 24px auto;
                    display: none;
                }}
                .filecrypt-skeleton-line {{
                    height: 18px;
                    border-radius: 6px;
                    margin: 10px auto;
                    background: linear-gradient(90deg, rgba(128,128,128,0.18), rgba(128,128,128,0.32), rgba(128,128,128,0.18));
                    background-size: 200% 100%;
                    animation: filecryptSkeleton 1.1s ease-in-out infinite;
                }}
                .filecrypt-skeleton-line.short {{ width: 55%; }}
                .filecrypt-skeleton-line.long {{ width: 82%; }}
                @keyframes filecryptSkeleton {{
                    0% {{ background-position: 200% 0; }}
                    100% {{ background-position: -200% 0; }}
                }}
            </style>
            <h1><img src="{images.logo}" type="image/webp" alt="Quasarr logo" class="logo"/>Quasarr</h1>
            {package_selector}
            {failed_warning}
            {link_select}<br><br>
            <form id="circle-captcha-form" action="/captcha/decrypt-filecrypt-circle" method="post" onsubmit="if(typeof incrementCaptchaAttempts==='function')incrementCaptchaAttempts();">
              <input type="hidden" name="package_id" value="{package_id}" />
              <input type="hidden" name="url" value="{circle["url"]}" />
              <input type="hidden" name="cookies" value="{cookies_payload}" />
              <input type="hidden" id="circle-x" name="button.x" value="" />
              <input type="hidden" id="circle-y" name="button.y" value="" />
              <div class="circle-captcha-scroll">
                <img
                    id="circle-captcha-image"
                    class="circle-captcha-image"
                    src="data:{circle["content_type"]};base64,{image_data}"
                    alt="Circle CAPTCHA"
                    width="{image_width}"
                    height="{image_height}"
                    data-width="{image_width}"
                    data-height="{image_height}"
                />
              </div>
            </form>
            <div id="circle-submit-loader" class="filecrypt-skeleton" aria-label="Submitting Circle-Captcha">
                <div class="filecrypt-skeleton-line long"></div>
                <div class="filecrypt-skeleton-line short"></div>
            </div>
            {source_button}
            <p>
                {render_button("Delete Package", "secondary", {"onclick": f"location.href='/captcha/delete/{package_id}?title={quote(title)}'"})}
            </p>
            <p>
                {render_button("Back", "secondary", {"onclick": "location.href='/'"})}
            </p>
            <div id="bypass-section">
                {bypass_section}
            </div>
            <script>
                document.getElementById('circle-captcha-image').addEventListener('click', function(event) {{
                    const rect = this.getBoundingClientRect();
                    const naturalWidth = Number(this.dataset.width);
                    const naturalHeight = Number(this.dataset.height);
                    const x = Math.round((event.clientX - rect.left) * naturalWidth / rect.width);
                    const y = Math.round((event.clientY - rect.top) * naturalHeight / rect.height);
                    document.getElementById('circle-x').value = String(x);
                    document.getElementById('circle-y').value = String(y);
                    document.getElementById('circle-captcha-form').style.display = 'none';
                    document.getElementById('circle-submit-loader').style.display = 'block';
                    document.getElementById('circle-captcha-form').submit();
                }});
            </script>
        """)

    @app.post("/captcha/decrypt-filecrypt-circle")
    def submit_circle_captcha():
        package_id = request.forms.get("package_id")
        url = request.forms.get("url")
        cookies_payload = request.forms.get("cookies")
        x = request.forms.get("buttonx.x") or request.forms.get("button.x")
        y = request.forms.get("buttonx.y") or request.forms.get("button.y")

        if not package_id or not url or not cookies_payload or not x or not y:
            response.status = 400
            return render_centered_html(f'''<h1><img src="{images.logo}" type="image/webp" alt="Quasarr logo" class="logo"/>Quasarr</h1>
            <p><b>Error:</b> Missing Circle-Captcha solution data.</p>
            <p>{render_button("Back", "secondary", {"onclick": "location.href='/'"})}</p>''')

        check_package_exists(package_id)
        package_data = json.loads(shared_state.get_db("protected").retrieve(package_id))
        title = package_data.get("title", "Unknown Package")
        password = package_data.get("password", "")
        package_links = package_data.get("links", [])
        desired_mirror = package_data.get("mirror")
        original_url = package_data.get("original_url")
        category = get_download_category_from_package_id(package_id)
        mirrors = get_download_category_mirrors(category, lowercase=True)

        try:
            cookies = json.loads(urlsafe_b64decode(unquote(cookies_payload)).decode())
            decrypted = get_filecrypt_links(
                shared_state,
                "",
                title,
                url,
                password=password,
                mirrors=mirrors,
                cookies=cookies,
                circle_solution=(x, y),
            )
            if isinstance(decrypted, dict) and decrypted.get("status") in (
                "captcha_required",
                "circle_required",
                "single_link_circle_required",
            ):
                next_payload = {
                    "package_id": package_id,
                    "title": title,
                    "password": password,
                    "mirror": desired_mirror,
                    "links": [
                        [decrypted.get("url") or url, "filecrypt"],
                        *[
                            link
                            for link in package_links
                            if (link[0] if isinstance(link, (list, tuple)) else link)
                            != url
                        ],
                    ],
                    "original_url": original_url,
                    "cookies": decrypted.get("cookies") or cookies,
                }
                if decrypted.get("status") == "captcha_required":
                    next_payload["captcha_type"] = "cutcaptcha"
                    next_url = f"/captcha/cutcaptcha?data={quote(encode_payload(next_payload))}"
                    return render_filecrypt_loading_redirect(
                        next_url,
                        title,
                        "Circle-Captcha accepted. Loading CutCaptcha...",
                    )

                next_payload["mode"] = "single_link"
                next_url = f"/captcha/circle?data={quote(encode_payload(next_payload))}"
                return render_filecrypt_loading_redirect(
                    next_url,
                    title,
                    "Circle-Captcha accepted. Loading next FileCrypt challenge...",
                )

            links = decrypted.get("links", []) if decrypted else []
            if not links:
                raise ValueError("No download links found after Circle-Captcha")

            submit_result = submit_final_download_urls(
                shared_state,
                links,
                title,
                password,
                package_id,
                remove_protected=True,
                notification_details={"method": "manual"},
            )
            if not submit_result["success"]:
                raise RuntimeError(
                    submit_result.get("reason") or "Submitting Download failed"
                )

            final_links = submit_result["links"]
            StatsHelper(shared_state).increment_package_with_links(final_links)
            StatsHelper(shared_state).increment_captcha_decryptions_manual()

            return render_captcha_success_page(title, len(final_links), package_id)
        except Exception as e:
            info(f"Error decrypting Filecrypt Circle-Captcha: {e}")
            StatsHelper(shared_state).increment_failed_decryptions_manual()
            return render_centered_html(f'''<h1><img src="{images.logo}" type="image/webp" alt="Quasarr logo" class="logo"/>Quasarr</h1>
            <p><b>Error:</b> Circle-Captcha failed. Please try again.</p>
            <p>{render_button("Try Again", "secondary", {"onclick": "location.href='/captcha'"})}</p>''')

    @app.get("/captcha/filecrypt")
    @app.get("/captcha/cutcaptcha")
    def serve_filecrypt_challenge_page():
        payload = decode_payload()

        if "error" in payload:
            return render_centered_html(f'''<h1><img src="{images.logo}" type="image/webp" alt="Quasarr logo" class="logo"/>Quasarr</h1>
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
        handoff_cookies = payload.get("cookies") or []
        forced_captcha_type = payload.get("captcha_type")

        check_package_exists(package_id)

        if not prioritized_links:
            # No links found, show an error message
            return render_centered_html(f'''
                <h1><img src="{images.logo}" type="image/webp" alt="Quasarr logo" class="logo"/>Quasarr</h1>
                <p style="max-width: 370px; word-wrap: break-word; overflow-wrap: break-word;"><b>Package:</b> {title}</p>
                <p><b>Error:</b> No download links available for this package.</p>
                <p>
                    {render_button("Delete Package", "secondary", {"onclick": f"location.href='/captcha/delete/{package_id}?title={quote(title)}'"})}
                </p>
                <p>
                    {render_button("Back", "secondary", {"onclick": "location.href='/'"})}
                </p>
            ''')

        has_filecrypt_links = any(
            (
                "filecrypt." in link[0]
                if isinstance(link, (list, tuple))
                else "filecrypt." in link
            )
            for link in prioritized_links
        )

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
                        var status = document.getElementById("filecrypt-status");
                        if (status && window.checkFilecryptChallenge) {{
                            status.style.display = "block";
                            status.innerHTML = '<div class="filecrypt-skeleton" aria-label="Checking FileCrypt challenge"><div class="filecrypt-skeleton-line long"></div><div class="filecrypt-skeleton-line short"></div></div>';
                            window.checkFilecryptChallenge();
                        }}
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

        url = payload.get("link") or prioritized_links[0][0]

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
        filecrypt_fallback_url = (
            f"/captcha/filecrypt/manual?data={quote(fallback_encoded)}"
        )

        failed_warning = render_failed_attempts_warning(
            package_id,
            title=title,
            include_delete_button=False,
            fallback_url=filecrypt_fallback_url,
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

        pow_button_html = render_button(
            "Bypass Proof-of-Work",
            "primary",
            {"onclick": "decryptFilecryptWithoutToken('Bypassing proof-of-work...')"},
        )
        decrypt_button_html = render_button(
            "Decrypt FileCrypt",
            "primary",
            {"onclick": "decryptFilecryptWithoutToken('Decrypting links...')"},
        )
        initial_loader = (
            "loadCutCaptcha"
            if forced_captcha_type == "cutcaptcha"
            else (
                "checkFilecryptChallenge" if has_filecrypt_links else "loadCutCaptcha"
            )
        )

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
                .filecrypt-skeleton {
                    max-width: 370px;
                    margin: 0 auto 28px auto;
                }
                .filecrypt-skeleton-line {
                    height: 18px;
                    border-radius: 6px;
                    margin: 10px auto;
                    background: linear-gradient(90deg, rgba(128,128,128,0.18), rgba(128,128,128,0.32), rgba(128,128,128,0.18));
                    background-size: 200% 100%;
                    animation: filecryptSkeleton 1.1s ease-in-out infinite;
                }
                .filecrypt-skeleton-line.short {
                    width: 55%;
                }
                .filecrypt-skeleton-line.long {
                    width: 82%;
                }
                @keyframes filecryptSkeleton {
                    0% { background-position: 200% 0; }
                    100% { background-position: -200% 0; }
                }
            </style>
            <script type="text/javascript">
                // Package title for result display
                var packageTitleText = "'''
            + escaped_title_js
            + r"""";

                // Keep warning visible after repeated failures, but still detect
                // FileCrypt's current challenge type before falling back manually.
                (function() {
                    const storageKey = 'captcha_attempts_"""
            + package_id
            + r"""';
                    const attempts = parseInt(localStorage.getItem(storageKey) || '0', 10);
                    const autoFallbackRedirect = false;
                    if (autoFallbackRedirect && attempts >= 2) {
                        window.location.href = '"""
            + js_single_quoted_string_safe(filecrypt_fallback_url)
            + r'''';
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
                var filecryptCookies = """
            + json.dumps(handoff_cookies)
            + r""";

                function hideFilecryptControls() {
                    var puzzleCaptcha = document.getElementById("puzzle-captcha");
                    if (puzzleCaptcha) puzzleCaptcha.style.display = "none";
                    var mirrorsSelect = document.getElementById("mirrors-select");
                    if (mirrorsSelect) mirrorsSelect.style.display = "none";
                    var deletePackageSection = document.getElementById("delete-package-section");
                    if (deletePackageSection) deletePackageSection.style.display = "none";
                    var backButtonSection = document.getElementById("back-button-section");
                    if (backButtonSection) backButtonSection.style.display = "none";
                    var bypassSection = document.getElementById("bypass-section");
                    if (bypassSection) bypassSection.style.display = "none";
                    var statusSection = document.getElementById("filecrypt-status");
                    if (statusSection) statusSection.style.display = "none";
                    var captchaContainer = document.getElementById("captcha-container");
                    if (captchaContainer) captchaContainer.style.display = "none";
                    var pkgSelector = document.getElementById("package-selector-section");
                    if (pkgSelector) pkgSelector.style.display = "none";
                    var warnBox = document.getElementById("failed-attempts-warning");
                    if (warnBox) warnBox.style.display = "none";
                }

                function renderFilecryptLoading(statusText) {
                    return '<p style="word-break: break-all;"><b>Package:</b> ' + packageTitleText + '</p>' +
                        '<p style="word-break: break-all;">' + statusText + '</p>' +
                        '<div class="filecrypt-skeleton" aria-label="' + statusText.replace(/"/g, '&quot;') + '">' +
                        '<div class="filecrypt-skeleton-line long"></div>' +
                        '<div class="filecrypt-skeleton-line short"></div>' +
                        '</div>';
                }

                function submitFilecryptToken(token, statusText) {
                    hideFilecryptControls();
                    document.getElementById("captcha-key").innerHTML = renderFilecryptLoading(statusText);
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
                            password: '{js_single_quoted_string_safe(password or "")}',
                            mirror: '{js_single_quoted_string_safe(desired_mirror or "")}',
                            cookies: filecryptCookies,
                        """
            + """})
                    })
                    .then(response => response.json())
                    .then(data => {
                        if (data.action === 'captcha_required') {
                            filecryptCookies = data.cookies || filecryptCookies || [];
                            if (data.url) {
                                document.getElementById("link-hidden").value = data.url;
                            }
                            document.getElementById("captcha-key").innerHTML = '<p style="word-break: break-all;"><b>Package:</b> ' + packageTitleText + '</p><p style="word-break: break-all;">Proof-of-work cleared. Solve CutCaptcha to decrypt links.</p>';
                            var puzzleCaptcha = document.getElementById("puzzle-captcha");
                            if (puzzleCaptcha) puzzleCaptcha.style.display = "block";
                            loadCutCaptcha();
                            return;
                        }
                        if (data.action === 'circle_required' || data.action === 'single_link_circle_required') {
                            redirectToCircleCaptcha(data);
                            return;
                        }
                        if (data.success) {
                            const linkCount = Number.isInteger(data.link_count) ? data.link_count : 0;
                            document.getElementById("captcha-key").innerHTML =
                                '<p><b>✅ CAPTCHA solved and submitted to JDownloader.</b></p>' +
                                '<p style="word-break: break-all;"><b>Package:</b> ' + packageTitleText + '</p>' +
                                '<p>' + linkCount + ' link(s) processed.</p>';
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

                function handleToken(token) {
                    submitFilecryptToken(token, 'Using result "' + token + '" to decrypt links...');
                }

                function decryptFilecryptWithoutToken(statusText) {
                    submitFilecryptToken('', statusText);
                }

                function loadCutCaptcha() {
                    document.getElementById("filecrypt-status").style.display = "none";
                    document.getElementById("captcha-container").style.display = "inline-block";
                    var script = document.createElement('script');
                    script.src = '/captcha/cutcaptcha-loader.js';
                    document.body.appendChild(script);
                }

                function showFilecryptAction(html, text) {
                    const status = document.getElementById("filecrypt-status");
                    status.innerHTML = '<p style="word-break: break-all;">' + text + '</p><p>' + html + '</p>';
                }

                function redirectToFilecryptUserscript() {
                    window.location.href = '"""
            + filecrypt_fallback_url
            + r"""';
                }

                function redirectToCircleCaptcha(data) {
                    const circleUrl = data.url || document.getElementById("link-hidden").value;
                    const payload = {
                        package_id: '"""
            + js_single_quoted_string_safe(package_id)
            + r"""',
                        url: circleUrl,
                        cookies: data.cookies || filecryptCookies || [],
                        mode: data.action === 'single_link_circle_required' ? 'single_link' : 'container'
                    };
                    const encoded = btoa(unescape(encodeURIComponent(JSON.stringify(payload))));
                    window.location.href = '/captcha/circle?data=' + encodeURIComponent(encoded);
                }

                function checkFilecryptChallenge() {
                    const controller = new AbortController();
                    const timeoutId = setTimeout(() => controller.abort(), 20000);
                    fetch('/captcha/filecrypt-status', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        signal: controller.signal,
                        body: JSON.stringify({
                            link: document.getElementById("link-hidden").value,
                            password: '"""
            + js_single_quoted_string_safe(password or "")
            + r"""'
                        })
                    })
                    .finally(() => clearTimeout(timeoutId))
                    .then(response => response.json())
                    .then(data => {
                        const captchaType = data.captcha_type || 'unknown';
                        if (captchaType === 'cutcaptcha') {
                            loadCutCaptcha();
                        } else if (captchaType === 'pow') {
                            showFilecryptAction(`"""
            + pow_button_html
            + r"""`, 'FileCrypt proof-of-work is present.');
                        } else if (captchaType === 'none') {
                            showFilecryptAction(`"""
            + decrypt_button_html
            + r"""`, 'FileCrypt links are available without CAPTCHA.');
                        } else if (captchaType === 'circle') {
                            redirectToCircleCaptcha(data);
                        } else {
                            redirectToFilecryptUserscript();
                        }
                    })
                    .catch(() => redirectToFilecryptUserscript());
                }

                if (document.readyState === 'loading') {
                    document.addEventListener('DOMContentLoaded', """
            + initial_loader
            + r""");
                } else {
                    """
            + initial_loader
            + r"""();
                }
                """
            + f'''</script>
                <div>
                    <h1><img src="{images.logo}" type="image/webp" alt="Quasarr logo" class="logo"/>Quasarr</h1>
                    <div id="package-selector-section">
                        {package_selector}
                    </div>
                    {failed_warning}
                    <div id="captcha-key"></div>
                    {link_select}<br><br>
                    <input type="hidden" id="link-hidden" value="{prioritized_links[0][0]}" />
                    <div id="filecrypt-status">
                        <div class="filecrypt-skeleton" aria-label="Checking FileCrypt challenge">
                            <div class="filecrypt-skeleton-line long"></div>
                            <div class="filecrypt-skeleton-line short"></div>
                        </div>
                    </div>
                    <div class="captcha-container" id="captcha-container" style="display: none;">
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
                {render_button("Delete Package", "secondary", {"onclick": f"location.href='/captcha/delete/{package_id}?title={quote(title)}'"})}
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
            response.content_type = "image/webp"
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
                return render_centered_html(f'''<h1><img src="{images.logo}" type="image/webp" alt="Quasarr logo" class="logo"/>Quasarr</h1>
                <p><b>Error:</b> Missing package information.</p>
                <p>
                    {render_button("Back", "secondary", {"onclick": "location.href='/'"})}
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
                    f"Received <green>{len(links)}</green> valid direct download links "
                    f"(from <y>{len(raw_links)}</y> provided)"
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
                    return render_centered_html(f'''<h1><img src="{images.logo}" type="image/webp" alt="Quasarr logo" class="logo"/>Quasarr</h1>
                    <p><b>Error:</b> Failed to decrypt DLC file: {str(e)}</p>
                    <p>
                        {render_button("Back", "secondary", {"onclick": "location.href='/'"})}
                    </p>''')
            else:
                return render_centered_html(f'''<h1><img src="{images.logo}" type="image/webp" alt="Quasarr logo" class="logo"/>Quasarr</h1>
                <p><b>Error:</b> Please provide either links or a DLC file.</p>
                <p>
                    {render_button("Back", "secondary", {"onclick": "location.href='/'"})}
                </p>''')

            # Download the package
            if links:
                submit_result = submit_final_download_urls(
                    shared_state,
                    links,
                    title,
                    password,
                    package_id,
                    remove_protected=True,
                    notification_details={"method": "manual"},
                )
                if submit_result["success"]:
                    final_links = submit_result["links"]
                    StatsHelper(shared_state).increment_package_with_links(final_links)
                    StatsHelper(shared_state).increment_captcha_decryptions_manual()

                    return render_captcha_success_page(
                        title, len(final_links), package_id
                    )
                else:
                    StatsHelper(shared_state).increment_failed_decryptions_manual()
                    if submit_result.get("persisted_failure"):
                        return render_centered_html(f'''<h1><img src="{images.logo}" type="image/webp" alt="Quasarr logo" class="logo"/>Quasarr</h1>
                        <p><b>Package marked as failed.</b></p>
                        <p>{submit_result["reason"]}</p>
                        <p>
                            {render_button("Back", "secondary", {"onclick": "location.href='/'"})}
                        </p>''')
                    return render_centered_html(f'''<h1><img src="{images.logo}" type="image/webp" alt="Quasarr logo" class="logo"/>Quasarr</h1>
                    <p><b>Error:</b> Failed to submit package to JDownloader.</p>
                    <p>
                        {render_button("Try Again", "secondary", {"onclick": "location.href='/captcha'"})}
                    </p>''')
            else:
                return render_centered_html(f'''<h1><img src="{images.logo}" type="image/webp" alt="Quasarr logo" class="logo"/>Quasarr</h1>
                <p><b>Error:</b> No valid links found.</p>
                <p>
                    {render_button("Back", "secondary", {"onclick": "location.href='/'"})}
                </p>''')

        except Exception as e:
            info(f"Bypass submission error: {e}")
            return render_centered_html(f'''<h1><img src="{images.logo}" type="image/webp" alt="Quasarr logo" class="logo"/>Quasarr</h1>
            <p><b>Error:</b> {str(e)}</p>
            <p>
                {render_button("Back", "secondary", {"onclick": "location.href='/'"})}
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
        failure_reason = ""
        try:
            data = request.json
            token = data.get("token")
            package_id = data.get("package_id")
            title = data.get("title")
            link = data.get("link")
            password = data.get("password")
            cookies = data.get("cookies") or []
            category = get_download_category_from_package_id(package_id)
            mirrors = get_download_category_mirrors(category, lowercase=True)

            if token is not None:
                info(
                    f"Received token: <green>{token}</green> to decrypt links for <y>{title}</y>"
                )
                decrypted = get_filecrypt_links(
                    shared_state,
                    token,
                    title,
                    link,
                    password=password,
                    mirrors=mirrors,
                    cookies=cookies,
                )
                if (
                    isinstance(decrypted, dict)
                    and decrypted.get("status") == "captcha_required"
                ):
                    return {
                        "success": False,
                        "action": "captcha_required",
                        "url": decrypted.get("url") or link,
                        "cookies": decrypted.get("cookies") or cookies,
                        "title": title,
                        "has_more_captchas": True,
                    }
                if (
                    isinstance(decrypted, dict)
                    and decrypted.get("status") == "circle_required"
                ):
                    return {
                        "success": False,
                        "action": "circle_required",
                        "url": decrypted.get("url") or link,
                        "cookies": decrypted.get("cookies") or cookies,
                        "title": title,
                        "has_more_captchas": True,
                    }
                if (
                    isinstance(decrypted, dict)
                    and decrypted.get("status") == "single_link_circle_required"
                ):
                    return {
                        "success": False,
                        "action": "single_link_circle_required",
                        "url": decrypted.get("url") or link,
                        "cookies": decrypted.get("cookies") or cookies,
                        "title": title,
                        "has_more_captchas": True,
                    }
                if decrypted:
                    links = decrypted.get("links", [])
                    info(f"Decrypted <g>{len(links)}</g> download links for {title}")
                    if not links:
                        raise ValueError("No download links found after decryption")
                    submit_result = submit_final_download_urls(
                        shared_state,
                        links,
                        title,
                        password,
                        package_id,
                        remove_protected=True,
                        notification_details={"method": "manual"},
                    )
                    if submit_result["success"]:
                        final_links = submit_result["links"]
                        StatsHelper(shared_state).increment_package_with_links(
                            final_links
                        )
                        links = final_links
                    else:
                        links = []
                        failure_reason = submit_result.get("reason", "")
                        if submit_result.get("persisted_failure"):
                            info(
                                f'Package "{title}" marked as failed after final mirror-whitelist check'
                            )
                        else:
                            raise RuntimeError(
                                "Submitting Download to JDownloader failed"
                            )
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
            "reason": failure_reason,
            "title": title,
            "link_count": len(links),
            "has_more_captchas": has_more_captchas,
        }
