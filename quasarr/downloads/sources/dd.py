# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import base64
import pickle

import requests

from quasarr.providers.log import info, debug


def create_and_persist_session(shared_state):
    dd = shared_state.values["config"]("Hostnames").get("dd")

    dd_session = requests.Session()

    cookies = {}
    headers = {
        'User-Agent': shared_state.values["user_agent"],
    }

    data = {
        'username': shared_state.values["config"]("DD").get("user"),
        'password': shared_state.values["config"]("DD").get("password"),
        'ajax': 'true',
        'Login': 'true',
    }

    dd_response = dd_session.post(f'https://{dd}/index/index',
                                  cookies=cookies, headers=headers, data=data, timeout=10)

    error = False
    if dd_response.status_code == 200:
        try:
            response_data = dd_response.json()
            if not response_data.get('loggedin'):
                info("DD rejected login.")
                raise ValueError
            session_id = dd_response.cookies.get("PHPSESSID")
            if session_id:
                dd_session.cookies.set('PHPSESSID', session_id, domain=dd)
            else:
                info("Invalid DD response on login.")
                error = True
        except ValueError:
            info("Could not parse DD response on login.")
            error = True

        if error:
            shared_state.values["config"]("DD").save("user", "")
            shared_state.values["config"]("DD").save("password", "")
            return None

        serialized_session = pickle.dumps(dd_session)
        session_string = base64.b64encode(serialized_session).decode('utf-8')
        shared_state.values["database"]("sessions").update_store("dd", session_string)
        return dd_session
    else:
        info("Could not create DD session")
        return None


def retrieve_and_validate_session(shared_state):
    session_string = shared_state.values["database"]("sessions").retrieve("dd")
    if not session_string:
        dd_session = create_and_persist_session(shared_state)
    else:
        try:
            serialized_session = base64.b64decode(session_string.encode('utf-8'))
            dd_session = pickle.loads(serialized_session)
            if not isinstance(dd_session, requests.Session):
                raise ValueError("Retrieved object is not a valid requests.Session instance.")
        except Exception as e:
            info(f"Session retrieval failed: {e}")
            dd_session = create_and_persist_session(shared_state)

    return dd_session


def get_dd_download_links(shared_state, mirror, search_string):
    dd = shared_state.values["config"]("Hostnames").get("dd")

    dd_session = retrieve_and_validate_session(shared_state)
    if not dd_session:
        info(f"Could not retrieve valid session for {dd}")
        return []

    links = []

    qualities = [
        "disk-480p",
        "web-480p",
        "movie-480p-x265",
        "disk-1080p-x265",
        "web-1080p",
        "web-1080p-x265",
        "web-2160p-x265-hdr",
        "movie-1080p-x265",
        "movie-2160p-webdl-x265-hdr"
    ]

    headers = {
        'User-Agent': shared_state.values["user_agent"],
    }

    try:
        release_list = []
        for page in range(0, 100, 20):
            url = f'https://{dd}/index/search/keyword/{search_string}/qualities/{','.join(qualities)}/from/{page}/search'

            releases_on_page = dd_session.get(url, headers=headers, timeout=10).json()
            if releases_on_page:
                release_list.extend(releases_on_page)

        for release in release_list:
            try:
                if release.get("fake"):
                    debug(f"Release {release.get('release')} marked as fake. Invalidating DD session...")
                    create_and_persist_session(shared_state)
                    return []
                elif release.get("release") == search_string:
                    filtered_links = []
                    for link in release["links"]:
                        if mirror and mirror not in link["hostname"]:
                            debug(f'Skipping link from "{link["hostname"]}" (not the desired mirror "{mirror}")!')
                            continue

                        if any(
                                existing_link["hostname"] == link["hostname"] and
                                existing_link["url"].endswith(".mkv") and
                                link["url"].endswith(".mkv")
                                for existing_link in filtered_links
                        ):
                            debug(f"Skipping duplicate `.mkv` link from {link['hostname']}")
                            continue  # Skip adding duplicate `.mkv` links from the same hostname
                        filtered_links.append(link)

                    links = [link["url"] for link in filtered_links]
                    break
            except Exception as e:
                info(f"Error parsing DD feed: {e}")
                continue

    except Exception as e:
        info(f"Error loading DD feed: {e}")

    return links
