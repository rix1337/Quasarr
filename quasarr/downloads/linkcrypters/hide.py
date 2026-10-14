# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

import requests

from quasarr.constants import DOWNLOAD_REQUEST_TIMEOUT_SECONDS
from quasarr.providers.cloudflare import (
    flaresolverr_create_session,
    flaresolverr_destroy_session,
    flaresolverr_get,
)
from quasarr.providers.log import debug, info
from quasarr.providers.statistics import StatsHelper
from quasarr.providers.utils import is_flaresolverr_available

EPISODE_NOT_PRESENT = "Episode not present in link container"


class HideEpisodeError(Exception):
    """An episode grab must never fall back to an unfiltered container."""


class HideEpisodeBrowserUnavailable(HideEpisodeError):
    """The explicit selection can still be handled by the browser/helper flow."""


def _terminal_episode_error(shared_state, reason):
    StatsHelper(shared_state).increment_failed_decryptions_automatic()
    return {
        "status": "error",
        "results": [],
        "reason": reason,
        "terminal": True,
    }


def _episode_selection(url):
    query = parse_qs(urlsplit(url).query, keep_blank_values=True)
    if "season" not in query and "episode" not in query:
        return None
    try:
        if len(query["season"]) != 1 or len(query["episode"]) != 1:
            raise ValueError
        season = int(query["season"][0])
        episode = int(query["episode"][0])
        if season < 0 or episode <= 0:
            raise ValueError
    except (KeyError, ValueError):
        raise HideEpisodeError("Invalid Hide episode selection") from None
    return season, episode


def confirm_hide_episode_selection(links, confirmation):
    """Require browser/helper confirmation for an explicitly selected Hide grab."""
    selections = []
    for link in links or []:
        url = link[0] if isinstance(link, (list, tuple)) else link
        if isinstance(url, str) and urlsplit(url).hostname in (
            "hide.cx",
            "www.hide.cx",
        ):
            selections.append(_episode_selection(url))
    expected = [selection for selection in selections if selection is not None]
    if not expected:
        return
    if len(set(selections)) != 1:
        raise HideEpisodeError("Inconsistent Hide episode selection")
    try:
        if not isinstance(confirmation, dict) or any(
            isinstance(confirmation.get(key), (bool, float))
            for key in ("season", "episode")
        ):
            raise ValueError
        actual = (int(confirmation["season"]), int(confirmation["episode"]))
    except (KeyError, TypeError, ValueError):
        raise HideEpisodeError("Hide episode selection was not confirmed") from None
    if actual != expected[0]:
        raise HideEpisodeError("Hide episode selection was not confirmed")
    return expected[0]


def _native_episode_link_ids(shared_state, container_id, selection):
    """Ask Hide's own frontend to select the episode; never parse filenames here."""
    if not is_flaresolverr_available(shared_state):
        raise HideEpisodeBrowserUnavailable(
            "Hide episode selection requires FlareSolverr"
        )
    token = f"S{selection[0]:02d}E{selection[1]:02d}"
    # Hide's live Vue container view owns extractedEpisodes, selectedEpisode,
    # and items. Use that native selection rather than copying its matching rules.
    script = """return (async () => {
        const wanted = TOKEN, id = CONTAINER_ID;
        function find(view) {
            if (!view) return null;
            if (view.component) {
                if (view.component.type.name === 'ContainerLink')
                    return view.component.proxy;
                const found = find(view.component.subTree);
                if (found) return found;
            }
            if (Array.isArray(view.children)) {
                for (const child of view.children) {
                    const found = find(child);
                    if (found) return found;
                }
            }
            return null;
        }
        for (let attempt = 0; attempt < 100; attempt++) {
            const view = find(document.querySelector('#app')?._vnode);
            if (view?.container && !view.loading) {
                if (view.container.id !== id)
                    return JSON.stringify({error: 'Hide container identity mismatch'});
                if (!Array.isArray(view.extractedEpisodes) ||
                    !view.extractedEpisodes.includes(wanted))
                    return JSON.stringify({error: 'Episode not present in link container'});
                view.selectedEpisode = wanted;
                await new Promise(resolve => setTimeout(resolve, 50));
                if (view.selectedEpisode !== wanted || !Array.isArray(view.items))
                    return JSON.stringify({error: 'Hide episode selection failed'});
                return JSON.stringify({selected: wanted, ids: view.items.map(link => link.id)});
            }
            await new Promise(resolve => setTimeout(resolve, 100));
        }
        return JSON.stringify({error: 'Hide episode selection unavailable'});
    })();""".replace("TOKEN", json.dumps(token)).replace(
        "CONTAINER_ID", json.dumps(container_id)
    )
    session_id = flaresolverr_create_session(shared_state)
    if not session_id:
        raise HideEpisodeBrowserUnavailable(
            "Could not create Hide episode selection session"
        )
    try:
        response = flaresolverr_get(
            shared_state,
            f"https://hide.cx/container/{container_id}?{urlencode({'season': selection[0], 'episode': selection[1]})}",
            timeout=DOWNLOAD_REQUEST_TIMEOUT_SECONDS,
            session_id=session_id,
            execute_js=script,
        )
        data = json.loads(response.execute_js_result or "{}")
        if not isinstance(data, dict):
            raise HideEpisodeError("Invalid Hide episode selection response")
        if data.get("error"):
            raise HideEpisodeError(str(data["error"]))
        ids = data.get("ids")
        if data.get("selected") != token or not isinstance(ids, list):
            raise HideEpisodeError("Hide episode selection was not confirmed")
        if not ids:
            raise HideEpisodeError(EPISODE_NOT_PRESENT)
        if any(not isinstance(link_id, str) or not link_id for link_id in ids):
            raise HideEpisodeError("Invalid selected Hide link IDs")
        return list(dict.fromkeys(ids))
    except HideEpisodeError:
        raise
    except Exception as exc:
        raise HideEpisodeError(f"Hide episode selection failed: {exc}") from exc
    finally:
        flaresolverr_destroy_session(shared_state, session_id)


def unhide_links(shared_state, url, session):
    selection = _episode_selection(url)
    try:
        links = []

        # Support both formats:
        # - https://hide.cx/container/{id}
        # - https://hide.cx/fc/Container/{id}.html
        match = re.search(
            r"/(?:fc/)?container/([a-z0-9A-Z\-]+)(?:\.html)?",
            url,
            re.IGNORECASE,
        )

        if not match:
            info(f"Invalid hide.cx URL: {url}")
            return []

        container_id = match.group(1)
        is_fc = "/fc/" in url.lower()
        # resolve fc foreign ID to canonical container ID
        if is_fc:
            headers = {
                "User-Agent": shared_state.values["user_agent"],
                "Accept": "application/json",
                "X-Requested-With": "XMLHttpRequest",
            }

            info(f"Resolving hide.cx foreign container ID: {container_id}")
            resolve_url = f"https://api.hide.cx/fc/Container/{container_id}"
            resp = session.get(
                resolve_url,
                headers=headers,
                timeout=DOWNLOAD_REQUEST_TIMEOUT_SECONDS,
            )

            try:
                resolved = resp.json()
            except Exception:
                debug(f"Failed to resolve foreign container {container_id}")
                return []

            canonical_id = resolved.get("id")
            if not canonical_id:
                debug(f"No canonical container ID found for {container_id}")
                return []

            container_id = canonical_id
            debug(f"Resolved to canonical container ID: {container_id}")

        headers = {"User-Agent": shared_state.values["user_agent"]}
        info(f"Fetching hide.cx container with ID: {container_id}")

        headers = {"User-Agent": shared_state.values["user_agent"]}

        container_url = f"https://api.hide.cx/containers/{container_id}"
        response = session.get(
            container_url,
            headers=headers,
            timeout=DOWNLOAD_REQUEST_TIMEOUT_SECONDS,
        )
        data = response.json()

        link_ids = [link.get("id") for link in data.get("links", []) if link.get("id")]
        if selection:
            selected_ids = _native_episode_link_ids(
                shared_state, container_id, selection
            )
            if not set(selected_ids).issubset(link_ids):
                raise HideEpisodeError("Selected Hide links changed during download")
            link_ids = selected_ids

        if not link_ids:
            debug(f"No link IDs found in container {container_id}")
            return []

        def fetch_link(link_id):
            debug(f"Fetching hide.cx link with ID: {link_id}")
            link_url = f"https://api.hide.cx/containers/{container_id}/links/{link_id}"
            link_data = session.get(
                link_url,
                headers=headers,
                timeout=DOWNLOAD_REQUEST_TIMEOUT_SECONDS,
            ).json()
            return link_data.get("url")

        # Process links in batches of 10
        batch_size = 10
        for i in range(0, len(link_ids), batch_size):
            batch = link_ids[i : i + batch_size]
            with ThreadPoolExecutor(max_workers=batch_size) as executor:
                futures = [executor.submit(fetch_link, link_id) for link_id in batch]
                for future in as_completed(futures):
                    try:
                        final_url = future.result()
                        if selection and not final_url:
                            raise HideEpisodeError(
                                "Could not resolve all links for requested episode"
                            )
                        if final_url and final_url not in links:
                            links.append(final_url)
                    except Exception as e:
                        if selection:
                            raise HideEpisodeError(
                                "Could not resolve all links for requested episode"
                            ) from e
                        info(f"Error fetching link: {e}")

        success = bool(links)
        if success:
            StatsHelper(shared_state).increment_captcha_decryptions_automatic()
        else:
            StatsHelper(shared_state).increment_failed_decryptions_automatic()

        return links
    except HideEpisodeError:
        raise
    except Exception as e:
        if selection:
            raise HideEpisodeError(f"Hide episode download failed: {e}") from e
        info(f"Error fetching hide.cx links: {e}")
        StatsHelper(shared_state).increment_failed_decryptions_automatic()
        return []


def decrypt_links_if_hide(shared_state: Any, items: List[List[str]]) -> Dict[str, Any]:
    """
    Resolve redirects and decrypt hide.cx links from a list of item lists.

    Each item list must include:
      - index 0: the URL to resolve
      - any additional metadata at subsequent indices (ignored here)

    :param shared_state: State object required by unhide_links function
    :param items: List of lists, where each inner list has the URL at index 0
    :return: Dict with 'status' and 'results' (flat list of decrypted link URLs)
    """
    if not items:
        info("No items provided to decrypt.")
        return {"status": "error", "results": []}

    session = requests.Session()
    session.max_redirects = 5

    hide_urls: List[str] = []
    try:
        selections = [_episode_selection(item[0]) for item in items if item[0]]
    except HideEpisodeError as e:
        return _terminal_episode_error(shared_state, str(e))
    episode_requested = any(selection is not None for selection in selections)
    if episode_requested and len(set(selections)) != 1:
        return _terminal_episode_error(
            shared_state, "Inconsistent Hide episode selection"
        )
    for item in items:
        original_url = item[0]
        if not original_url:
            debug(f"Skipping item without URL: {item}")
            continue

        try:
            selection = _episode_selection(original_url)
            episode_requested = episode_requested or selection is not None
            # Try HEAD first, fallback to GET
            try:
                resp = session.head(
                    original_url,
                    allow_redirects=True,
                    timeout=DOWNLOAD_REQUEST_TIMEOUT_SECONDS,
                )
            except requests.RequestException:
                resp = session.get(
                    original_url,
                    allow_redirects=True,
                    timeout=DOWNLOAD_REQUEST_TIMEOUT_SECONDS,
                )

            final_url = resp.url
            if selection:
                parts = urlsplit(final_url)
                query = parse_qs(parts.query, keep_blank_values=True)
                query.update(season=[str(selection[0])], episode=[str(selection[1])])
                final_url = urlunsplit(
                    parts._replace(query=urlencode(query, doseq=True))
                )

            # accept hide.cx even if it did not redirect
            if "hide.cx" in final_url or "hide.cx" in original_url:
                debug(f"Identified hide.cx link: {final_url}")
                hide_urls.append(final_url)
            else:
                debug(f"Not a hide.cx link (skipped): {final_url}")

        except HideEpisodeError as e:
            return _terminal_episode_error(shared_state, str(e))
        except requests.RequestException as e:
            if episode_requested:
                return _terminal_episode_error(
                    shared_state, "Hide episode container could not be loaded"
                )
            info(f"Error resolving URL {original_url}: {e}")
            continue

    if not hide_urls:
        if episode_requested:
            return _terminal_episode_error(shared_state, EPISODE_NOT_PRESENT)
        debug(f"No hide.cx links found among {len(items)} items.")
        return {"status": "none", "results": []}

    info(f"Found {len(hide_urls)} hide.cx URLs; decrypting...")
    decrypted_links: List[str] = []
    episode_error = None
    browser_unavailable = False
    terminal_episode_error = False
    for url in hide_urls:
        try:
            links = unhide_links(shared_state, url, session)
            if not links:
                debug(f"No links decrypted for {url}")
                continue
            decrypted_links.extend(links)
        except HideEpisodeError as e:
            episode_error = str(e)
            if isinstance(e, HideEpisodeBrowserUnavailable):
                browser_unavailable = True
            else:
                terminal_episode_error = True
        except Exception as e:
            info(f"Failed to decrypt {url}: {e}")
            continue

    if not decrypted_links:
        if episode_requested:
            terminal = terminal_episode_error or not browser_unavailable
            if terminal:
                return _terminal_episode_error(
                    shared_state, episode_error or EPISODE_NOT_PRESENT
                )
            return {
                "status": "error",
                "results": [],
                "reason": episode_error or EPISODE_NOT_PRESENT,
                "terminal": False,
            }
        info("Could not decrypt any links from hide.cx URLs.")
        return {"status": "error", "results": []}

    return {"status": "success", "results": decrypted_links}
