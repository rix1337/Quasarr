# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337
#
# MX: download twin.
# Original contribution by Riourik (https://github.com/riourik), PR #360.

import json
import re
from urllib.parse import parse_qs, urlparse

import requests

from quasarr.constants import (
    DOWNLOAD_REQUEST_TIMEOUT_SECONDS,
    SESSION_REQUEST_TIMEOUT_SECONDS,
)
from quasarr.downloads.mirror_filters import normalize_mirror_token
from quasarr.downloads.sources.helpers.abstract_source import AbstractDownloadSource
from quasarr.providers.cloudflare import (
    flaresolverr_create_session,
    flaresolverr_destroy_session,
    flaresolverr_get,
)
from quasarr.providers.hostname_issues import clear_hostname_issue, mark_hostname_issue
from quasarr.providers.log import debug, info
from quasarr.providers.utils import is_flaresolverr_available

_DECODE_PATH_RE = re.compile(r"/api/darkiworld/decode/(?P<link_id>[^/?#]+)")
_DEFAULT_TURNSTILE_SITEKEY = "0x4AAAAAACiKag0T7qr6BMz3"

# Render MX's Turnstile widget at document start with a challenge title so
# FlareSolverr's native Turnstile clicker solves the interactive checkbox before
# executeJs reads the resulting token.
_TURNSTILE_DOCUMENT_START_JS = """
window.__mx_turnstile_token = null;
window.__mx_turnstile_error = null;
window.__mx_turnstile_rendered = false;
const __mx_sitekey = SITEKEY;
const __mx_observer = new MutationObserver(() => {
    if (!window.__mx_turnstile_token && !window.__mx_turnstile_error) {
        if (document.title !== "Just a moment...") {
            document.title = "Just a moment...";
        }
    }
    if (document.body && !document.getElementById("cf-turnstile-mx")) {
        const box = document.createElement("div");
        box.id = "cf-turnstile-mx";
        box.className = "cf-turnstile";
        box.setAttribute("data-sitekey", __mx_sitekey);
        box.setAttribute("data-theme", "dark");
        box.style.cssText = (
            "position:fixed;top:20px;left:20px;width:300px;height:65px;z-index:2147483647;"
        );
        document.body.prepend(box);
    }
    if (
        window.turnstile &&
        document.getElementById("cf-turnstile-mx") &&
        !window.__mx_turnstile_rendered
    ) {
        window.__mx_turnstile_rendered = true;
        try {
            window.turnstile.render("#cf-turnstile-mx", {
                sitekey: __mx_sitekey,
                theme: "dark",
                callback: (token) => {
                    window.__mx_turnstile_token = token;
                    __mx_observer.disconnect();
                    document.title = "Solved";
                },
                "error-callback": (err) => {
                    window.__mx_turnstile_error = String(err);
                    __mx_observer.disconnect();
                    document.title = "Error";
                },
            });
        } catch (err) {
            window.__mx_turnstile_error = String(err);
            __mx_observer.disconnect();
            document.title = "Error";
        }
    }
});
__mx_observer.observe(document, { childList: true, subtree: true });
"""

_TURNSTILE_EXECUTE_JS = """return (async () => {
    for (let attempt = 0; attempt < 40; attempt++) {
        if (window.__mx_turnstile_token || window.__mx_turnstile_error) {
            break;
        }
        const input = document.querySelector("input[name=cf-turnstile-response]");
        if (input && input.value) {
            window.__mx_turnstile_token = input.value;
            break;
        }
        await new Promise((resolve) => setTimeout(resolve, 250));
    }
    return JSON.stringify({
        token: window.__mx_turnstile_token || null,
        error: window.__mx_turnstile_error || null,
    });
})();"""


def _extract_decoded_url(data):
    if not isinstance(data, dict):
        return None
    embed_url = data.get("embed_url")
    if isinstance(embed_url, dict):
        return embed_url.get("lien") or embed_url.get("url") or embed_url.get("link")
    if isinstance(embed_url, str) and embed_url:
        return embed_url
    return data.get("url") or data.get("link")


def _parse_decode_target(url, configured_host):
    parsed = urlparse(url)
    match = _DECODE_PATH_RE.search(parsed.path or "")
    if not match:
        return None

    netloc = (parsed.hostname or "").strip(".")
    site_host = configured_host
    if not site_host and netloc:
        site_host = netloc[4:] if netloc.startswith("api.") else netloc
    if not site_host:
        return None

    api_origin = (
        f"{parsed.scheme or 'https'}://{netloc}"
        if netloc
        else f"https://api.{site_host}"
    )
    query = parse_qs(parsed.query)
    title_id = (query.get("title_id") or [None])[0]
    host_hint = (query.get("host") or [None])[0]
    return {
        "api_url": f"{api_origin}/api/darkiworld/decode/{match.group('link_id')}",
        "site_host": site_host,
        "title_id": title_id,
        "host_hint": host_hint,
    }


def _solve_turnstile_token(shared_state, site_host, sitekey=_DEFAULT_TURNSTILE_SITEKEY):
    if not is_flaresolverr_available(shared_state):
        info("[mx] FlareSolverr is required to solve MX link verification")
        mark_hostname_issue("mx", "download", "FlareSolverr required")
        return None

    session_id = flaresolverr_create_session(shared_state)
    if not session_id:
        mark_hostname_issue("mx", "download", "Could not create FlareSolverr session")
        return None

    doc_start_js = _TURNSTILE_DOCUMENT_START_JS.replace("SITEKEY", json.dumps(sitekey))
    try:
        response = flaresolverr_get(
            shared_state,
            f"https://{site_host}/",
            timeout=max(
                DOWNLOAD_REQUEST_TIMEOUT_SECONDS, SESSION_REQUEST_TIMEOUT_SECONDS
            ),
            session_id=session_id,
            document_start_js=doc_start_js,
            execute_js=_TURNSTILE_EXECUTE_JS,
        )
        payload = json.loads(getattr(response, "execute_js_result", None) or "{}")
        token = payload.get("token") if isinstance(payload, dict) else None
        if not token:
            err = payload.get("error") if isinstance(payload, dict) else None
            debug(f"[mx] Turnstile token unavailable ({err or 'timeout'})")
            return None
        return token
    except Exception as e:
        debug(f"[mx] Turnstile browser solve failed: {e}")
        mark_hostname_issue("mx", "download", str(e))
        return None
    finally:
        flaresolverr_destroy_session(shared_state, session_id)


def _decode_mx_link(shared_state, target):
    site_host = target["site_host"]
    params = {"title_id": target["title_id"]} if target["title_id"] is not None else {}
    token = _solve_turnstile_token(shared_state, site_host)
    if not token:
        return None

    headers = {
        "User-Agent": shared_state.values.get("user_agent", "Mozilla/5.0"),
        "Referer": f"https://{site_host}/",
        "Origin": f"https://{site_host}",
    }
    r = requests.post(
        target["api_url"],
        params=params,
        json={"turnstileToken": token},
        headers=headers,
        timeout=DOWNLOAD_REQUEST_TIMEOUT_SECONDS,
    )
    if r.status_code >= 400:
        debug(f"[mx] decode POST failed ({r.status_code}): {r.text[:200]}")
        mark_hostname_issue("mx", "download", f"Decode HTTP {r.status_code}")
        return None
    return _extract_decoded_url(r.json())


class Source(AbstractDownloadSource):
    initials = "mx"

    def get_download_links(self, shared_state, url, mirrors, title, password):
        if not url:
            return {"links": []}

        allowed = (
            {normalize_mirror_token(m) for m in mirrors if m} if mirrors else set()
        )
        allowed.discard("")

        configured_host = None
        cfg = shared_state.values.get("config")
        if callable(cfg):
            configured_host = cfg("Hostnames").get(self.initials)

        decode_target = _parse_decode_target(url, configured_host)
        if decode_target is not None:
            hint_token = normalize_mirror_token(decode_target.get("host_hint"))
            if allowed and hint_token and hint_token not in allowed:
                debug(f"[mx] {hint_token} not in requested mirrors for {title}")
                return {"links": []}

            resolved_url = _decode_mx_link(shared_state, decode_target)
            if not resolved_url:
                return {"links": []}
            url = resolved_url

        # Match the mirror whitelist on the canonical hoster token (the same
        # normalization the final filter uses), so aliased hoster domains are
        # not dropped before they reach it.
        token = normalize_mirror_token(url)
        if allowed and token not in allowed:
            debug(f"[mx] {token or 'unknown'} not in requested mirrors for {title}")
            return {"links": []}

        debug(f"[mx] download link: {url}")
        clear_hostname_issue(self.initials)
        return {"links": [[url, token or "unknown"]]}
