# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import json
from base64 import urlsafe_b64decode, urlsafe_b64encode
from html import escape
from urllib.parse import quote, unquote

from bottle import HTTPResponse, redirect, request, response

import quasarr.providers.html_images as images
from quasarr.api.jdownloader import get_jdownloader_disconnected_page
from quasarr.downloads import fail, submit_final_download_urls
from quasarr.downloads.linkcrypters.hide import (
    HideEpisodeError,
    confirm_hide_episode_selection,
)
from quasarr.downloads.packages import delete_package
from quasarr.providers import obfuscated, shared_state
from quasarr.providers.auth import public_endpoint
from quasarr.providers.html_templates import render_button, render_centered_html
from quasarr.providers.log import debug, error, info, trace
from quasarr.providers.notifications import update_release_notification
from quasarr.providers.notifications.helpers.notification_types import NotificationType
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
    def mark_manual_package_failed(package_id, title, reason):
        protected_release = None
        try:
            raw_data = shared_state.get_db("protected").retrieve(package_id)
            protected_release = json.loads(raw_data) if raw_data else None
        except Exception as e:
            info(
                f'Error reading protected package "{package_id}" for manual failure: {e}'
            )
        if isinstance(protected_release, dict) and protected_release.get("title"):
            title = protected_release["title"]
        fail(title, package_id, shared_state, reason=reason)
        try:
            shared_state.get_db("protected").delete(package_id)
        except Exception as e:
            info(
                f'Error deleting protected package "{package_id}" after manual failure: {e}'
            )
        update_release_notification(
            shared_state,
            protected_release or {"title": title},
            NotificationType.FAILED,
            details={"reason": reason},
        )
        return render_centered_html(f'''<h1><img src="{images.logo}" class="logo"/>Quasarr</h1>
        <p><b>Package marked as failed.</b></p>
        <p>{escape(str(reason))}</p>
        <p>{render_button("Back", "secondary", {"onclick": "location.href='/captcha'"})}</p>''')

    def render_manual_failure(reason):
        return render_centered_html(f'''<h1><img src="{images.logo}" class="logo"/>Quasarr</h1>
        <p><b>Error:</b> {escape(str(reason))}</p>
        <p>{render_button("Back", "secondary", {"onclick": "location.href='/captcha'"})}</p>''')

    def get_hide_episode_confirmation():
        season_values = request.query.getall("season")
        episode_values = request.query.getall("episode")
        if len(season_values) != 1 or len(episode_values) != 1:
            return {"season": None, "episode": None}
        season = season_values[0]
        episode = episode_values[0]
        try:
            season = int(season)
            episode = int(episode)
        except (TypeError, ValueError):
            pass
        return {"season": season, "episode": episode}

    def is_he_link(link):
        url = link[0] if isinstance(link, (list, tuple)) else link
        mirror = link[1] if isinstance(link, (list, tuple)) and len(link) > 1 else ""
        if str(mirror).lower() == "he":
            return True

        he = shared_state.values["config"]("Hostnames").get("he")
        return bool(he and he.lower() in str(url).lower())

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

            # Order the links to open by the category's mirror-whitelist:
            # the whitelist order is the priority ranking. Without an explicit
            # whitelist, fall back to the legacy rapidgator-first default.
            mirror_priority = []
            try:
                category = get_download_category_from_package_id(package_id)
                mirror_priority = get_download_category_mirrors(
                    category, lowercase=True
                )
            except Exception:
                mirror_priority = []
            if mirror_priority:

                def mirror_rank(link):
                    if isinstance(link, (list, tuple)) and len(link) > 1 and link[1]:
                        haystack = str(link[1]).lower()
                    elif isinstance(link, (list, tuple)) and link:
                        haystack = str(link[0]).lower()
                    else:
                        haystack = str(link).lower()
                    for index, mirror in enumerate(mirror_priority):
                        if mirror and mirror in haystack:
                            return index
                    return len(mirror_priority)

                prioritized_links = sorted(links, key=mirror_rank)
            else:
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
            has_he_links = any(is_he_link(link) for link in prioritized_links)

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
            elif has_he_links:
                debug("Redirecting to HE CAPTCHA")
                redirect(f"/captcha/he?data={quote(encoded_payload)}")
            elif has_keeplinks_links:
                debug("Redirecting to KeepLinks CAPTCHA")
                redirect(f"/captcha/keeplinks?data={quote(encoded_payload)}")
            elif has_tolink_links:
                debug("Redirecting to ToLink CAPTCHA")
                redirect(f"/captcha/tolink?data={quote(encoded_payload)}")
            else:
                debug("Redirecting to FileCrypt CAPTCHA")
                redirect(f"/captcha/filecrypt?data={quote(encoded_payload)}")

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

    def render_userscript_section(
        url, package_id, title, password, provider_type="junkies"
    ):
        """Render the standard userscript UI section for a protected provider.

        This is the MAIN solution for these providers (not a bypass/fallback).

        Args:
            url: The URL to open with transfer params
            package_id: Package identifier
            title: Package title
            password: Package password
            provider_type: Protected-provider route name
        """

        provider_names = {
            "filecrypt": "FileCrypt",
            "hide": "Hide",
            "junkies": "Junkies",
            "he": "HE",
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

        separator = "&" if "?" in url else "?"
        url_with_quick_transfer_params = (
            f"{url}{separator}"
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

    @app.get("/captcha/he")
    def serve_he_captcha():
        payload = decode_payload()

        if "error" in payload:
            return render_centered_html(f'''<h1><img src="{images.logo}" type="image/webp" alt="Quasarr logo" class="logo"/>Quasarr</h1>
            <p>{payload["error"]}</p>
            <p>
                {render_button("Back", "secondary", {"onclick": "location.href='/'"})}
            </p>''')

        package_id = payload.get("package_id")
        title = payload.get("title")
        password = payload.get("password") or ""
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
                {render_userscript_section(url, package_id, title, password, "he")}
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

    @app.get("/captcha/filecrypt")
    def serve_filecrypt_captcha():
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
                {render_userscript_section(url, package_id, title, password, "filecrypt")}
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

    @app.get("/captcha/he.user.js")
    @public_endpoint
    def serve_he_user_js():
        he = shared_state.values["config"]("Hostnames").get("he")
        content = obfuscated.he_user_js(he)
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
            has_he = any(is_he_link(l) for l in links)
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
            elif has_he:
                return "he"
            elif has_keeplinks:
                return "keeplinks"
            elif has_tolink:
                return "tolink"
            else:
                return "filecrypt"

        options = []
        for package in protected:
            pkg_id = package[0]
            data = json.loads(package[1])
            title = data.get("title", "Unknown")
            links = data.get("links", [])
            password = data.get("password", "")
            mirror = data.get("mirror")
            original_url = data.get("original_url")

            # Prefer rapidgator mirrors when picking the link to open first
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
        package_id, title=None, include_delete_button=True
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

        return f"""
            <div id="failed-attempts-warning" class="warning-box" style="display: none; background: #fee2e2; border: 2px solid #dc2626; border-radius: 8px; padding: 16px; margin-bottom: 20px; text-align: center; color: #991b1b;">
                <h3 style="color: #dc2626; margin-top: 0;">⚠️ Multiple Failed Attempts Detected</h3>
                <p style="margin-bottom: 12px; color: #7f1d1d;">This CAPTCHA has failed multiple times. The link may be <b>offline</b> or require a different solution method.</p>
                <p style="margin-bottom: 8px; color: #7f1d1d;">Please verify the link is still valid, or delete this package if it's no longer available.</p>
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

    @app.get("/captcha/quick-transfer")
    def handle_quick_transfer():
        """Handle quick transfer from userscript"""
        import zlib

        try:
            package_id = request.query.get("pkg_id")
            failure_reason = request.query.get("error")
            if package_id and failure_reason:
                check_package_exists(package_id)
                protected_data = json.loads(
                    shared_state.get_db("protected").retrieve(package_id)
                )
                try:
                    expected_selection = confirm_hide_episode_selection(
                        protected_data.get("links", []), get_hide_episode_confirmation()
                    )
                except HideEpisodeError as e:
                    return render_manual_failure(str(e))
                if expected_selection is None:
                    return render_manual_failure(failure_reason)
                StatsHelper(shared_state).increment_failed_decryptions_manual()
                return mark_manual_package_failed(package_id, "Unknown", failure_reason)
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

            try:
                confirm_hide_episode_selection(
                    data.get("links", []), get_hide_episode_confirmation()
                )
            except HideEpisodeError as e:
                StatsHelper(shared_state).increment_failed_decryptions_manual()
                return mark_manual_package_failed(package_id, title, str(e))

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

        except HTTPResponse:
            raise
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

    @app.post("/captcha/bypass-submit")
    def handle_bypass_submit():
        """Handle manual submission of pasted download links"""
        try:
            package_id = request.forms.get("package_id")
            title = request.forms.get("title")
            password = request.forms.get("password", "")
            links_input = request.forms.get("links", "").strip()

            if not package_id or not title:
                return render_centered_html(f'''<h1><img src="{images.logo}" type="image/webp" alt="Quasarr logo" class="logo"/>Quasarr</h1>
                <p><b>Error:</b> Missing package information.</p>
                <p>
                    {render_button("Back", "secondary", {"onclick": "location.href='/'"})}
                </p>''')

            check_package_exists(package_id)

            protected_data = json.loads(
                shared_state.get_db("protected").retrieve(package_id)
            )
            try:
                confirm_hide_episode_selection(protected_data.get("links", []), None)
            except HideEpisodeError as e:
                StatsHelper(shared_state).increment_failed_decryptions_manual()
                return mark_manual_package_failed(package_id, title, str(e))

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
            else:
                return render_centered_html(f'''<h1><img src="{images.logo}" type="image/webp" alt="Quasarr logo" class="logo"/>Quasarr</h1>
                <p><b>Error:</b> Please provide the download links.</p>
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
