# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import base64
import json
import re
import xml.dom.minidom
from urllib.parse import urljoin, urlparse

import dukpy
import requests
from bs4 import BeautifulSoup
from Cryptodome.Cipher import AES

from quasarr.constants import DOWNLOAD_REQUEST_TIMEOUT_SECONDS
from quasarr.providers.cloudflare import (
    _DOCUMENT_START_JS_RESULT,
    _FILECRYPT_DOCUMENT_START_JS,
    ensure_session_cf_bypassed,
    is_cloudflare_challenge,
)
from quasarr.providers.log import debug, info

_FILECRYPT_TLDS = ("cc", "to", "co")
_FLARESOLVERR_NEXT_URL = "https://github.com/rix1337/flaresolverr-next"
_FILECRYPT_CIRCLE_CAPTCHA_URL = "https://filecrypt.cc/captcha/circle.php"
# Includes the 12-second initial page settle plus flaresolverr-next's 100-second
# trusted-click await budget for an in-page proof-of-work worker.
_FILECRYPT_POW_REQUEST_TIMEOUT_SECONDS = 120


def has_filecrypt_cutcaptcha(html):
    page = (html or "").lower()
    return "cutcaptcha" in page or "cap_token" in page


def has_filecrypt_circlecaptcha(html):
    page = html or ""
    lower_page = page.lower()
    soup = BeautifulSoup(page, "html.parser")

    circle_container = soup.find(
        class_=lambda value: (
            value and "circle" in str(value).lower() and "captcha" in str(value).lower()
        )
    )
    if circle_container:
        return True

    page_text = soup.get_text(" ", strip=True).lower()
    return (
        "captcha/circle.php" in lower_page
        or "click inside the open circle" in page_text
        or ("security check" in page_text and "open circle" in page_text)
    )


def _detected_filecrypt_captcha_type(captcha_type, reason):
    debug(f"Detected Filecrypt CAPTCHA type: {captcha_type} ({reason})")
    return captcha_type


def detect_filecrypt_captcha_type(html):
    soup = BeautifulSoup(html or "", "html.parser")
    if soup.find("form", {"class": "cnlform"}):
        return _detected_filecrypt_captcha_type("none", "cnlform present")
    if soup.select_one("button.download"):
        return _detected_filecrypt_captcha_type("none", "download button present")
    if _get_pow_captcha(soup):
        return _detected_filecrypt_captcha_type("pow", "pow-captcha present")
    if has_filecrypt_circlecaptcha(html):
        return _detected_filecrypt_captcha_type(
            "circle", "circle captcha marker present"
        )
    if has_filecrypt_cutcaptcha(html):
        return _detected_filecrypt_captcha_type(
            "cutcaptcha", "cutcaptcha marker present"
        )
    password_input = soup.find("input", {"id": "p4assw0rt"}) or soup.find(
        "input",
        placeholder=lambda value: value and "password" in value.lower(),
    )
    if password_input:
        return _detected_filecrypt_captcha_type("password", "password input present")
    return _detected_filecrypt_captcha_type("unknown", "no known marker present")


def _get_pow_captcha(soup):
    return soup.find("div", {"id": "pow-captcha", "class": "pow-captcha"})


def _filecrypt_url_candidates(url):
    parsed = urlparse(url)
    host = parsed.hostname or ""
    parts = host.split(".")
    if len(parts) < 2 or parts[-2] != "filecrypt":
        return [url]

    original_tld = parts[-1]
    tlds = [original_tld] + [tld for tld in _FILECRYPT_TLDS if tld != original_tld]

    urls = []
    for tld in tlds:
        candidate_host = ".".join([*parts[:-1], tld])
        netloc = candidate_host
        if parsed.port:
            netloc = f"{candidate_host}:{parsed.port}"
        urls.append(parsed._replace(netloc=netloc).geturl())
    return urls


def _cookies_for_target(session, target_url):
    domain = urlparse(target_url).hostname or ""
    cookies = []

    for cookie in session.cookies:
        cookie_domain = cookie.domain or domain
        normalized = cookie_domain.lstrip(".")
        if normalized != domain and not domain.endswith("." + normalized):
            continue

        cookies.append(
            {
                "name": cookie.name,
                "value": cookie.value,
                "domain": cookie_domain,
                "path": cookie.path or "/",
            }
        )

    return cookies


def _cookie_dict(cookies):
    return {cookie.get("name"): cookie.get("value") for cookie in cookies or []}


def _flaresolverr_execute_js_get(shared_state, session, url, execute_js, wait=12):
    flaresolverr_url = shared_state.values["config"]("FlareSolverr").get("url")
    if not flaresolverr_url:
        raise RuntimeError("flaresolverr-next is required for Filecrypt proof-of-work.")

    last_error = None

    for candidate_url in _filecrypt_url_candidates(url):
        payload = {
            "cmd": "request.get",
            "url": candidate_url,
            "maxTimeout": _FILECRYPT_POW_REQUEST_TIMEOUT_SECONDS * 1000,
            "waitInSeconds": wait,
            "cookies": _cookies_for_target(session, candidate_url),
            "executeJs": execute_js,
            "documentStartJs": _FILECRYPT_DOCUMENT_START_JS,
            "trustedClick": True,
        }

        response = requests.post(
            flaresolverr_url,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=_FILECRYPT_POW_REQUEST_TIMEOUT_SECONDS + 10,
        )
        response.raise_for_status()
        result = response.json()

        if result.get("status") != "ok" or "solution" not in result:
            message = result.get("message", "<no message>")
            last_error = message
            if "dns rebinding detected" in message.lower():
                continue
            raise RuntimeError(f"flaresolverr-next failed: {message}")

        solution = result["solution"]
        if solution.get("documentStartJsResult") != _DOCUMENT_START_JS_RESULT:
            raise RuntimeError(
                "Filecrypt proof-of-work requires flaresolverr-next documentStartJs "
                f"support. Update flaresolverr-next: {_FLARESOLVERR_NEXT_URL}"
            )

        for cookie in solution.get("cookies", []):
            session.cookies.set(
                cookie.get("name"),
                cookie.get("value"),
                domain=cookie.get("domain"),
                path=cookie.get("path", "/"),
            )

        user_agent = solution.get("userAgent")
        if user_agent and user_agent != shared_state.values.get("user_agent"):
            shared_state.update("user_agent", user_agent)

        return {
            "url": solution.get("url", candidate_url),
            "html": solution.get("response", ""),
            "execute_js_result": solution.get("executeJsResult"),
        }

    raise RuntimeError(f"flaresolverr-next failed: {last_error}")


def _solve_filecrypt_pow_if_present(shared_state, session, output, headers):
    soup = BeautifulSoup(output.text, "html.parser")
    if not _get_pow_captcha(soup):
        return output

    info(
        "Filecrypt proof-of-work detected. Solving with flaresolverr-next executeJs..."
    )

    click_js = """
    const box = document.querySelector('#pow-captcha .pow-captcha__box');
    if (!box) {
        return 'missing';
    }
    const rectangle = box.getBoundingClientRect();
    window.__FRS_AWAIT = new Promise(resolve => {
        const observer = new MutationObserver(() => {
            if (!document.querySelector('#pow-captcha')) {
                observer.disconnect();
                resolve('solved');
            }
        });
        observer.observe(document.documentElement, {childList: true, subtree: true});
        window.setTimeout(() => {
            observer.disconnect();
            resolve('clicked');
        }, 90000);
    });
    return JSON.stringify({trustedClick: {
        x: rectangle.left + rectangle.width / 2,
        y: rectangle.top + rectangle.height / 2,
    }});
    """

    for _ in range(3):
        result = _flaresolverr_execute_js_get(
            shared_state,
            session,
            output.url,
            click_js,
            wait=12,
        )

        execute_result = result.get("execute_js_result")
        if execute_result in (None, "", "null"):
            raise RuntimeError(
                "Filecrypt proof-of-work requires flaresolverr-next executeJs support. "
                f"Make sure you are using flaresolverr-next: {_FLARESOLVERR_NEXT_URL}"
            )

        execute_result = str(execute_result)
        if execute_result.startswith("ERROR:"):
            raise RuntimeError(
                "Filecrypt proof-of-work browser click failed: " + execute_result
            )

        if execute_result not in ("clicked", "solved"):
            info(f"Filecrypt proof-of-work click was not possible: {execute_result}")
            continue

        refreshed = session.get(
            result.get("url") or output.url,
            headers=headers,
            timeout=DOWNLOAD_REQUEST_TIMEOUT_SECONDS,
        )
        refreshed_soup = BeautifulSoup(refreshed.text, "html.parser")
        if not _get_pow_captcha(refreshed_soup):
            return refreshed

    info("Filecrypt proof-of-work solve did not finish.")
    return output


def _find_password_field(soup):
    input_elem = soup.find("input", attrs={"type": "password"})
    if not input_elem:
        input_elem = soup.find(
            "input", placeholder=lambda value: value and "password" in value.lower()
        )
    if not input_elem:
        input_elem = soup.find(
            "input",
            attrs={
                "name": lambda value: (
                    value and ("pass" in value.lower() or "password" in value.lower())
                )
            },
        )
    if input_elem and input_elem.has_attr("name"):
        return input_elem["name"]
    return None


def inspect_filecrypt_captcha(shared_state, url, password=None):
    session = requests.Session()
    headers = {"User-Agent": shared_state.values["user_agent"]}

    session, headers, output = ensure_session_cf_bypassed(
        info,
        shared_state,
        session,
        url,
        headers,
        timeout=DOWNLOAD_REQUEST_TIMEOUT_SECONDS,
    )
    if not session or not output:
        return {"captcha_type": "unknown", "url": url}

    soup = BeautifulSoup(output.text, "html.parser")
    password_field = _find_password_field(soup)

    if password and password_field:
        post_headers = {
            "User-Agent": shared_state.values["user_agent"],
            "Content-Type": "application/x-www-form-urlencoded",
        }
        output = session.post(
            output.url,
            data={password_field: password},
            headers=post_headers,
            timeout=DOWNLOAD_REQUEST_TIMEOUT_SECONDS,
        )

        if output.status_code == 403 or is_cloudflare_challenge(output.text):
            session, headers, output = ensure_session_cf_bypassed(
                info,
                shared_state,
                session,
                output.url,
                headers,
                timeout=DOWNLOAD_REQUEST_TIMEOUT_SECONDS,
            )
            if not session or not output:
                return {"captcha_type": "unknown", "url": url}

    captcha_type = detect_filecrypt_captcha_type(output.text)
    debug(f"Filecrypt challenge inspection result for {output.url}: {captcha_type}")
    return {
        "captcha_type": captcha_type,
        "url": output.url,
    }


def prepare_filecrypt_circle_captcha(shared_state, url, password=None, cookies=None):
    session = requests.Session()
    _apply_cookie_list(session, cookies)
    headers = {"User-Agent": shared_state.values["user_agent"]}

    session, headers, output = ensure_session_cf_bypassed(
        info,
        shared_state,
        session,
        url,
        headers,
        timeout=DOWNLOAD_REQUEST_TIMEOUT_SECONDS,
    )
    if not session or not output:
        raise RuntimeError("Could not load Filecrypt Circle-Captcha page.")

    soup = BeautifulSoup(output.text, "html.parser")
    password_field = _find_password_field(soup)
    if password and password_field:
        output = session.post(
            output.url,
            data={password_field: password},
            headers={
                "User-Agent": shared_state.values["user_agent"],
                "Content-Type": "application/x-www-form-urlencoded",
            },
            timeout=DOWNLOAD_REQUEST_TIMEOUT_SECONDS,
        )

    if detect_filecrypt_captcha_type(output.text) != "circle":
        raise RuntimeError("Filecrypt Circle-Captcha is no longer present.")

    parsed_url = urlparse(output.url)
    if parsed_url.hostname:
        session.cookies.set("a", "1", domain=parsed_url.hostname, path="/")

    cookies = _cookies_for_target(session, output.url)
    captcha = requests.get(
        _FILECRYPT_CIRCLE_CAPTCHA_URL,
        headers={
            **headers,
            "Accept": "image/avif,image/webp,image/png,image/svg+xml,image/*;q=0.8,*/*;q=0.5",
            "Referer": output.url,
        },
        cookies=_cookie_dict(cookies),
        timeout=DOWNLOAD_REQUEST_TIMEOUT_SECONDS,
    )
    captcha.raise_for_status()

    return {
        "url": output.url,
        "cookies": cookies,
        "image": captcha.content,
        "content_type": captcha.headers.get("Content-Type", "image/png"),
    }


class CNL:
    def __init__(self, crypted_data):
        debug("Initializing CNL with crypted_data.")
        self.crypted_data = crypted_data

    def jk_eval(self, f_def):
        debug("Evaluating JavaScript key function.")
        js_code = f"""
        {f_def}
        f();
        """

        result = dukpy.evaljs(js_code).strip()
        debug("JavaScript evaluation complete.")
        return result

    def aes_decrypt(self, data, key):
        debug("Starting AES decrypt.")
        try:
            encrypted_data = base64.b64decode(data)
            debug("Base64 decode for AES decrypt successful.")
        except Exception as e:
            debug("Base64 decode for AES decrypt failed.")
            raise ValueError("Failed to decode base64 data") from e

        try:
            key_bytes = bytes.fromhex(key)
            debug("Key successfully converted from hex.")
        except Exception as e:
            debug("Failed converting key from hex.")
            raise ValueError("Failed to convert key to bytes") from e

        iv = key_bytes
        cipher = AES.new(key_bytes, AES.MODE_CBC, iv)

        try:
            decrypted_data = cipher.decrypt(encrypted_data)
            debug("AES decrypt operation successful.")
        except ValueError as e:
            debug("AES decrypt operation failed.")
            raise ValueError("Decryption failed") from e

        try:
            decoded = (
                decrypted_data.decode("utf-8").replace("\x00", "").replace("\x08", "")
            )
            debug("Decoded AES output successfully.")
            return decoded
        except UnicodeDecodeError as e:
            debug("Failed decoding decrypted AES output.")
            raise ValueError("Failed to decode decrypted data") from e

    def decrypt(self):
        debug("Starting Click'N'Load decrypt sequence.")
        crypted = self.crypted_data[2]
        jk = "function f(){ return '" + self.crypted_data[1] + "';}"
        key = self.jk_eval(jk)
        uncrypted = self.aes_decrypt(crypted, key)
        urls = [result for result in uncrypted.split("\r\n") if len(result) > 0]
        debug(f"Extracted {len(urls)} URLs from CNL decrypt.")
        return urls


class DLC:
    def __init__(self, shared_state, dlc_file):
        debug("Initializing DLC decrypt handler.")
        self.shared_state = shared_state
        self.data = dlc_file
        self.KEY = b"cb99b5cbc24db398"
        self.IV = b"9bc24cb995cb8db3"
        self.API_URL = "http://service.jdownloader.org/dlcrypt/service.php?srcType=dlc&destType=pylo&data="

    def parse_packages(self, start_node):
        debug("Parsing DLC packages from XML.")
        return [
            (
                base64.b64decode(node.getAttribute("name")).decode("utf-8"),
                self.parse_links(node),
            )
            for node in start_node.getElementsByTagName("package")
        ]

    def parse_links(self, start_node):
        debug("Parsing DLC links in package.")
        return [
            base64.b64decode(
                node.getElementsByTagName("url")[0].firstChild.data
            ).decode("utf-8")
            for node in start_node.getElementsByTagName("file")
        ]

    def decrypt(self):
        debug("Starting DLC decrypt flow.")
        if not isinstance(self.data, bytes):
            debug("DLC data type invalid.")
            raise TypeError("data must be bytes.")

        all_urls = []

        try:
            debug("Preparing DLC data buffer.")
            data = self.data.strip()
            data += b"=" * (-len(data) % 4)

            dlc_key = data[-88:].decode("utf-8")
            dlc_data = base64.b64decode(data[:-88])
            debug("DLC base64 decode successful.")

            headers = {"User-Agent": self.shared_state.values["user_agent"]}

            debug("Requesting DLC decryption service.")
            dlc_content = requests.get(
                self.API_URL + dlc_key,
                headers=headers,
                timeout=DOWNLOAD_REQUEST_TIMEOUT_SECONDS,
            ).content.decode("utf-8")

            rc = base64.b64decode(
                re.search(r"<rc>(.+)</rc>", dlc_content, re.S).group(1)
            )[:16]
            debug("Received DLC RC block.")

            cipher = AES.new(self.KEY, AES.MODE_CBC, self.IV)
            key = iv = cipher.decrypt(rc)
            debug("Decrypted DLC key material.")

            cipher = AES.new(key, AES.MODE_CBC, iv)
            xml_data = base64.b64decode(cipher.decrypt(dlc_data)).decode("utf-8")
            debug("Final DLC decrypt successful.")

            root = xml.dom.minidom.parseString(xml_data).documentElement
            content_node = root.getElementsByTagName("content")[0]
            debug("Parsed DLC XML content.")

            packages = self.parse_packages(content_node)
            debug(f"Found {len(packages)} DLC packages.")

            for package in packages:
                urls = package[1]
                all_urls.extend(urls)

        except Exception as e:
            info("DLC Error: " + str(e))
            return None

        debug(f"DLC decrypt yielded {len(all_urls)} URLs.")
        return all_urls


def _apply_cookie_list(session, cookies):
    for cookie in cookies or []:
        session.cookies.set(
            cookie.get("name"),
            cookie.get("value"),
            domain=cookie.get("domain"),
            path=cookie.get("path", "/"),
        )


def _extract_filecrypt_single_link_urls(soup, base_url):
    urls = []
    for button in soup.select("button.download"):
        link_id = None
        for name, value in button.attrs.items():
            if name.startswith("data-") and isinstance(value, str) and value:
                link_id = value
                break
        if not link_id:
            continue
        link_url = urljoin(base_url, f"/Link/{link_id}.html")
        if link_url not in urls:
            urls.append(link_url)
    return urls


def _extract_filecrypt_go_urls(html, base_url):
    urls = []
    for go_url in re.findall(
        r"""(?:top\.)?location\.href\s*=\s*['"]([^'"]+/Go/[^'"]+\.html)['"]""",
        html or "",
    ):
        absolute = urljoin(base_url, go_url)
        if absolute not in urls:
            urls.append(absolute)
    return urls


def _is_filecrypt_hostname(hostname):
    parts = (hostname or "").lower().split(".")
    return len(parts) >= 2 and parts[-2] == "filecrypt"


def _resolve_filecrypt_go_urls(session, headers, go_urls):
    links = []
    for go_url in go_urls:
        debug(f"Resolving Filecrypt Go URL: {go_url}")
        go_response = session.get(
            go_url,
            headers=headers,
            allow_redirects=False,
            timeout=DOWNLOAD_REQUEST_TIMEOUT_SECONDS,
        )
        redirect_url = go_response.headers.get("Location")
        if redirect_url:
            links.append(urljoin(go_url, redirect_url))
            continue
        if go_response.url and not _is_filecrypt_hostname(
            urlparse(go_response.url).hostname
        ):
            links.append(go_response.url)
    return links


def _decrypt_filecrypt_single_links(session, headers, soup, page_url):
    links = []
    for link_url in _extract_filecrypt_single_link_urls(soup, page_url):
        info(f"Filecrypt single-link button detected: {link_url}")
        link_response = session.get(
            link_url,
            headers={
                **headers,
                "Referer": page_url,
            },
            timeout=DOWNLOAD_REQUEST_TIMEOUT_SECONDS,
        )

        captcha_type = detect_filecrypt_captcha_type(link_response.text)
        if captcha_type == "circle":
            info("Filecrypt single-link Circle-Captcha required.")
            return {
                "status": "single_link_circle_required",
                "url": link_response.url,
                "cookies": _cookies_for_target(session, link_response.url),
            }
        if captcha_type == "cutcaptcha":
            info("Filecrypt single-link CutCaptcha required.")
            return {
                "status": "captcha_required",
                "url": link_response.url,
                "cookies": _cookies_for_target(session, link_response.url),
            }

        go_urls = _extract_filecrypt_go_urls(link_response.text, link_response.url)
        links.extend(_resolve_filecrypt_go_urls(session, headers, go_urls))

    return {"status": "success", "links": links} if links else False


def get_filecrypt_links(
    shared_state,
    token,
    title,
    url,
    password=None,
    mirrors=None,
    cookies=None,
    circle_solution=None,
):
    info("Attempting to decrypt Filecrypt link: " + url)
    debug("Initializing Filecrypt session & headers.")
    session = requests.Session()
    _apply_cookie_list(session, cookies)
    headers = {"User-Agent": shared_state.values["user_agent"]}

    debug("Ensuring Cloudflare bypass is ready.")
    session, headers, output = ensure_session_cf_bypassed(
        info,
        shared_state,
        session,
        url,
        headers,
        timeout=DOWNLOAD_REQUEST_TIMEOUT_SECONDS,
    )
    if not session or not output:
        debug("Cloudflare bypass failed.")
        return False

    soup = BeautifulSoup(output.text, "html.parser")
    debug("Parsed initial Filecrypt HTML.")

    password_field = None
    try:
        debug("Attempting password field auto-detection.")
        password_field = _find_password_field(soup)
        if password_field:
            info("Password field name identified: " + password_field)
            debug(f"Password field detected: {password_field}")
    except Exception as e:
        info(f"Password-field detection error: {e}")
        debug("Password-field detection error raised.")

    if password and password_field:
        info("Using Password: " + password)
        debug("Submitting password via POST.")
        post_headers = {
            "User-Agent": shared_state.values["user_agent"],
            "Content-Type": "application/x-www-form-urlencoded",
        }
        data = {password_field: password}
        try:
            output = session.post(
                output.url,
                data=data,
                headers=post_headers,
                timeout=DOWNLOAD_REQUEST_TIMEOUT_SECONDS,
            )
            debug("Password POST request successful.")
        except requests.RequestException as e:
            info(f"POSTing password failed: {e}")
            debug("Password POST request failed.")
            return False

        if output.status_code == 403 or is_cloudflare_challenge(output.text):
            debug(
                "Encountered Cloudflare after password POST. Re-running FlareSolverr..."
            )
            session, headers, output = ensure_session_cf_bypassed(
                info,
                shared_state,
                session,
                output.url,
                headers,
                timeout=DOWNLOAD_REQUEST_TIMEOUT_SECONDS,
            )
            if not session or not output:
                debug("Cloudflare bypass failed after password POST.")
                return False

    url = output.url
    soup = BeautifulSoup(output.text, "html.parser")
    debug("Re-parsed HTML after password submit or initial load.")

    if bool(soup.find_all("input", {"id": "p4assw0rt"})):
        info(f"Password was wrong or missing. Could not get links for {title}")
        debug("Incorrect password detected via p4assw0rt.")
        return False

    output = _solve_filecrypt_pow_if_present(shared_state, session, output, headers)
    url = output.url
    soup = BeautifulSoup(output.text, "html.parser")

    if _get_pow_captcha(soup):
        info("Filecrypt proof-of-work still present after browser solve.")
        return False

    if detect_filecrypt_captcha_type(output.text) == "circle":
        if not circle_solution:
            info("Filecrypt Circle-Captcha required.")
            return {
                "status": "circle_required",
                "url": output.url,
                "cookies": _cookies_for_target(session, output.url),
            }

        x, y = circle_solution
        info(f"Submitting Filecrypt Circle-Captcha click at x={x}, y={y}.")
        parsed_url = urlparse(output.url)
        output = session.post(
            output.url,
            data={"button.x": x, "button.y": y},
            headers={
                "User-Agent": shared_state.values["user_agent"],
                "Content-Type": "application/x-www-form-urlencoded",
                "Origin": f"{parsed_url.scheme}://{parsed_url.netloc}",
                "Referer": output.url,
            },
            timeout=DOWNLOAD_REQUEST_TIMEOUT_SECONDS,
        )
        url = output.url
        soup = BeautifulSoup(output.text, "html.parser")

        if detect_filecrypt_captcha_type(output.text) == "circle":
            info("Filecrypt Circle-Captcha was rejected.")
            return False

        go_urls = _extract_filecrypt_go_urls(output.text, output.url)
        go_links = _resolve_filecrypt_go_urls(session, headers, go_urls)
        if go_links:
            return {"status": "success", "links": go_links}

    if not token and detect_filecrypt_captcha_type(output.text) == "cutcaptcha":
        info("Filecrypt CutCaptcha required after proof-of-work.")
        return {
            "status": "captcha_required",
            "url": output.url,
            "cookies": _cookies_for_target(session, output.url),
        }

    no_captcha_present = bool(
        soup.find("form", {"class": "cnlform"})
        or _extract_filecrypt_single_link_urls(soup, url)
    )
    if no_captcha_present:
        info("No CAPTCHA present. Skipping token!")
        debug("Detected no CAPTCHA (CNL form or download button).")
    else:
        circle_captcha = has_filecrypt_circlecaptcha(output.text)
        debug(f"Circle captcha present: {circle_captcha}")
        if circle_captcha:
            return {
                "status": "circle_required",
                "url": output.url,
                "cookies": _cookies_for_target(session, output.url),
            }

        debug("Submitting final CAPTCHA token.")
        output = session.post(
            url,
            data="cap_token=" + token,
            headers={
                "User-Agent": shared_state.values["user_agent"],
                "Content-Type": "application/x-www-form-urlencoded",
            },
            timeout=DOWNLOAD_REQUEST_TIMEOUT_SECONDS,
        )
    url = output.url

    if "/404.html" in url:
        info(
            "Filecrypt returned 404 - current IP is likely banned or the link is offline."
        )
        debug("Detected Filecrypt 404 page.")

    soup = BeautifulSoup(output.text, "html.parser")
    debug("Parsed post-captcha response HTML.")

    if detect_filecrypt_captcha_type(output.text) == "circle":
        info("Filecrypt Circle-Captcha required after CutCaptcha.")
        return {
            "status": "circle_required",
            "url": output.url,
            "cookies": _cookies_for_target(session, output.url),
        }

    solved = bool(soup.find_all("div", {"class": "container"}))
    if not solved:
        info("Token rejected by Filecrypt! Try another CAPTCHA to proceed...")
        debug("Token rejected; no 'container' div found.")
        return False
    else:
        debug("CAPTCHA token accepted by Filecrypt.")

        season_number = ""
        episode_number = ""
        episode_in_title = re.findall(
            r".*\.s(\d{1,3})e(\d{1,3})\..*", title, re.IGNORECASE
        )
        season_in_title = re.findall(r".*\.s(\d{1,3})\..*", title, re.IGNORECASE)
        debug("Attempting episode/season number parsing from title.")

        if episode_in_title:
            try:
                season_number = str(int(episode_in_title[0][0]))
                episode_number = str(int(episode_in_title[0][1]))
                debug(f"Detected S{season_number}E{episode_number} from title.")
            except:
                debug("Failed parsing S/E numbers from title.")
                pass
        elif season_in_title:
            try:
                season_number = str(int(season_in_title[0]))
                debug(f"Detected season {season_number} from title.")
            except:
                debug("Failed parsing season number from title.")
                pass

        season = ""
        episode = ""
        tv_show_selector = soup.find("div", {"class": "dlpart"})
        debug(f"TV show selector found: {bool(tv_show_selector)}")

        if tv_show_selector:
            season = "season="
            episode = "episode="

            season_selection = soup.find("div", {"id": "selbox_season"})
            try:
                if season_selection:
                    season += str(season_number)
                    debug(f"Assigned season parameter: {season}")
            except:
                debug("Failed assigning season parameter.")
                pass

            episode_selection = soup.find("div", {"id": "selbox_episode"})
            try:
                if episode_selection:
                    episode += str(episode_number)
                    debug(f"Assigned episode parameter: {episode}")
            except:
                debug("Failed assigning episode parameter.")
                pass

        if episode_number and not episode:
            info(
                f"Missing select for episode number {episode_number}! Expect undesired links in the output."
            )
            debug("Episode number present but no episode selector container found.")

        links = []

        mirrors_list = []
        mirrors_available = soup.select("a[href*=mirror]")
        debug(f"Mirrors available: {len(mirrors_available)}")

        if not mirrors and mirrors_available:
            for mirror in mirrors_available:
                try:
                    mirror_query = mirror.get("href").split("?")[1]
                    base_url = url.split("?")[0] if "mirror" in url else url
                    mirrors_list.append(f"{base_url}?{mirror_query}")
                    debug(f"Discovered mirror: {mirrors_list[-1]}")
                except IndexError:
                    debug("Mirror parsing failed due to missing '?'.")
                    continue
        else:
            mirrors_list = [url]
            debug("Using direct URL as only mirror.")

        for mirror in mirrors_list:
            if not len(mirrors_list) == 1:
                debug(f"Loading mirror: {mirror}")
                output = session.get(
                    mirror,
                    headers=headers,
                    timeout=DOWNLOAD_REQUEST_TIMEOUT_SECONDS,
                )
                url = output.url
                soup = BeautifulSoup(output.text, "html.parser")

            try:
                debug("Attempting Click'n'Load decrypt.")
                crypted_payload = soup.find("form", {"class": "cnlform"}).get(
                    "onsubmit"
                )
                crypted_data = re.findall(r"'(.*?)'", crypted_payload)
                if not title:
                    title = crypted_data[3]
                crypted_data = [
                    crypted_data[0],
                    crypted_data[1],
                    crypted_data[2],
                    title,
                ]

                if episode and season:
                    debug("Applying episode/season filtering to CNL.")
                    domain = urlparse(url).netloc
                    filtered_cnl_secret = soup.find(
                        "input", {"name": "hidden_cnl_id"}
                    ).attrs["value"]
                    filtered_cnl_link = f"https://{domain}/_CNL/{filtered_cnl_secret}.html?{season}&{episode}"
                    filtered_cnl_result = session.post(
                        filtered_cnl_link,
                        headers=headers,
                        timeout=DOWNLOAD_REQUEST_TIMEOUT_SECONDS,
                    )
                    if filtered_cnl_result.status_code == 200:
                        filtered_cnl_data = json.loads(filtered_cnl_result.text)
                        if filtered_cnl_data["success"]:
                            debug("Season/Episode filter applied successfully.")
                            crypted_data = [
                                crypted_data[0],
                                filtered_cnl_data["data"][0],
                                filtered_cnl_data["data"][1],
                                title,
                            ]
                links.extend(CNL(crypted_data).decrypt())
            except:
                debug("CNL decrypt failed; trying DLC fallback.")
                if (
                    "The owner of this folder has deactivated all hosts in this container in their settings."
                    in soup.text
                ):
                    info(f"Mirror deactivated by the owner: {mirror}")
                    debug("Mirror deactivated detected in page text.")
                    continue

                info("Click'n'Load not found! Falling back to DLC...")
                try:
                    debug("Attempting DLC fallback.")
                    crypted_payload = soup.find("button", {"class": "dlcdownload"}).get(
                        "onclick"
                    )
                    crypted_data = re.findall(r"'(.*?)'", crypted_payload)
                    dlc_secret = crypted_data[0]
                    domain = urlparse(url).netloc
                    if episode and season:
                        dlc_link = (
                            f"https://{domain}/DLC/{dlc_secret}.dlc?{episode}&{season}"
                        )
                    else:
                        dlc_link = f"https://{domain}/DLC/{dlc_secret}.dlc"
                    dlc_file = session.get(
                        dlc_link,
                        headers=headers,
                        timeout=DOWNLOAD_REQUEST_TIMEOUT_SECONDS,
                    ).content
                    links.extend(DLC(shared_state, dlc_file).decrypt())
                except:
                    debug("DLC fallback failed, trying button fallback.")
                    single_link_result = _decrypt_filecrypt_single_links(
                        session,
                        headers,
                        soup,
                        url,
                    )
                    if (
                        isinstance(single_link_result, dict)
                        and single_link_result.get("status") != "success"
                    ):
                        return single_link_result
                    if single_link_result:
                        links.extend(single_link_result.get("links", []))
                        continue
                    info(
                        "Click'n'Load, DLC, and single-link fallback not found. Please use the fallback userscript instead!"
                    )
                    return False

    if not links:
        info("No links found in Filecrypt response!")
        debug("Extraction completed but yielded no links.")
        return False

    debug(f"Returning success with {len(links)} extracted links.")
    return {"status": "success", "links": links}
