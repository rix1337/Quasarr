# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

from urllib.parse import urljoin, urlparse

import requests

from quasarr.constants import DOWNLOAD_REQUEST_TIMEOUT_SECONDS
from quasarr.providers.hostname_issues import mark_hostname_issue
from quasarr.providers.log import debug, warn
from quasarr.providers.utils import (
    NAVIGATION_CHAIN_READ_JS,
    NAVIGATION_CHAIN_RECORDER_JS,
    detect_crypter_type,
    first_crypter_in_chain,
    is_filecrypt_ban_page,
)


def _warn_404(label, url):
    if is_filecrypt_ban_page(url):
        warn(
            f"filecrypt banned the IP for now, so {label} link is not resolved: <d>{url}</d>"
        )
    else:
        warn(f"{label} link leads to a 404 page: <d>{url}</d>")


def resolve_crypter_redirect(
    url, user_agent, cf_session, source_initials, host=None, accept_offsite=False
):
    """Resolve a source's link-protection redirect to a crypter / hoster URL.

    Shared by the Cloudflare-session download sources (FF, SF). It follows the
    redirect chain manually with plain requests while the host is reachable, and
    lets the shared solver browser follow the rest for Cloudflare-gated hosts.

    In the browser case the tab can be pushed *past* the real crypter container onto
    a hostile ad (Quasarr#419: an aliexpress affiliate page). The browser reports
    only its final URL, so we also read the recorded navigation chain
    (``NAVIGATION_CHAIN_RECORDER_JS`` / ``first_crypter_in_chain``) and take the first
    crypter the browser walked, ignoring anything after it.

    ``accept_offsite`` returns a non-crypter URL that has left the source domain (a
    direct hoster link, as FF exposes); sources that only publish crypter containers
    (SF) leave it False. ``host`` is only needed when ``accept_offsite`` is True.

    Returns the resolved URL, or None on 404 / error / IP-ban / loop.
    """
    label = source_initials.upper()
    source_netloc = urlparse(f"https://{host}").netloc if host else None
    current_url = url
    visited = set()
    session = requests.Session()

    for _hop in range(8):
        if current_url in visited:
            debug(f"{label} redirect loop detected for {current_url}")
            return None
        visited.add(current_url)

        if detect_crypter_type(current_url) is not None:
            return current_url

        try:
            r = cf_session.get(
                current_url,
                {"User-Agent": user_agent},
                DOWNLOAD_REQUEST_TIMEOUT_SECONDS,
                request_get=lambda request_url, headers, timeout: session.get(
                    request_url,
                    allow_redirects=False,
                    timeout=timeout,
                    headers=headers,
                ),
                document_start_js=NAVIGATION_CHAIN_RECORDER_JS,
                execute_js=NAVIGATION_CHAIN_READ_JS,
            )
        except Exception as e:
            warn(f"Error fetching redirected URL for {url}: {e}")
            mark_hostname_issue(
                source_initials,
                "download",
                e,
            )
            return None

        # When the request went through the solver browser (Cloudflare-gated host),
        # it may have followed the chain past the real crypter into a hostile ad.
        # Take the first crypter the browser walked and stop; ignore anything after.
        crypter_url = first_crypter_in_chain(getattr(r, "execute_js_result", None))
        if crypter_url is not None:
            debug(
                f"{label} resolved to crypter via navigation chain: <d>{crypter_url}</d>"
            )
            return crypter_url

        location = (r.headers.get("Location") or "").strip()
        if location:
            next_url = urljoin(current_url, location)
            debug(f"Redirected from <d>{current_url}</d> to <d>{next_url}</d>")
            if "/404.html" in next_url:
                _warn_404(label, next_url)
                return None
            if detect_crypter_type(next_url) is not None:
                return next_url
            if (
                accept_offsite
                and source_netloc
                and urlparse(next_url).netloc != source_netloc
            ):
                return next_url
            current_url = next_url
            continue

        final_url = (r.url or current_url).strip()
        if "/404.html" in final_url:
            _warn_404(label, final_url)
            return None
        if r.status_code >= 400:
            warn(
                f"Error fetching redirected URL for {url}: HTTP {r.status_code} at {final_url}"
            )
            mark_hostname_issue(
                source_initials,
                "download",
                requests.HTTPError(
                    f"HTTP {r.status_code} while resolving redirect", response=r
                ),
            )
            return None
        if detect_crypter_type(final_url) is not None:
            return final_url
        if (
            accept_offsite
            and source_netloc
            and urlparse(final_url).netloc != source_netloc
        ):
            return final_url
        warn(
            f"Blocked attempt to resolve {url}. Your IP may be banned. Try again later."
        )
        return None

    debug(f"{label} redirect hop limit exceeded for {url}")
    return None
