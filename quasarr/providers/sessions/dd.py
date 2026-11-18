# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import base64
import pickle

import requests

from quasarr.constants import SESSION_REQUEST_TIMEOUT_SECONDS
from quasarr.providers.hostname_issues import clear_hostname_issue, mark_hostname_issue
from quasarr.providers.log import debug, info
from quasarr.providers.utils import is_site_usable

hostname = "dd"


def create_and_persist_session(shared_state):
    dd = shared_state.values["config"]("Hostnames").get("dd")

    dd_session = requests.Session()
    headers = {
        "User-Agent": shared_state.values["user_agent"],
    }

    try:
        r = dd_session.get(
            f"https://{dd}/api/csrf-token",
            headers=headers,
            timeout=SESSION_REQUEST_TIMEOUT_SECONDS,
        )
        r.raise_for_status()
        csrf_token = r.json().get("csrfToken")
    except Exception as e:
        info(f"Could not retrieve DD CSRF token: {e}")
        mark_hostname_issue(hostname, "session", e)
        return None

    if not csrf_token:
        info("Could not parse DD CSRF token.")
        mark_hostname_issue(hostname, "session", "Missing CSRF token")
        return None

    data = {
        "login": shared_state.values["config"]("DD").get("user"),
        "password": shared_state.values["config"]("DD").get("password"),
    }

    try:
        r = dd_session.post(
            f"https://{dd}/api/auth/login",
            json=data,
            headers={**headers, "x-csrf-token": csrf_token},
            timeout=SESSION_REQUEST_TIMEOUT_SECONDS,
        )
    except Exception as e:
        info(f"DD login request failed: {e}")
        mark_hostname_issue(hostname, "session", e)
        return None

    if r.status_code == 401:
        info("DD rejected login.")
        mark_hostname_issue(hostname, "session", "Login rejected")
        _blank_dd_credentials(shared_state)
        return None

    try:
        r.raise_for_status()
        response_data = r.json()
    except Exception as e:
        info(f"Invalid DD response on login: {e}")
        mark_hostname_issue(hostname, "session", "Invalid login response")
        return None

    if not response_data.get("user"):
        info("DD rejected login.")
        mark_hostname_issue(hostname, "session", "Login rejected")
        _blank_dd_credentials(shared_state)
        return None

    serialized_session = pickle.dumps(dd_session)
    session_string = base64.b64encode(serialized_session).decode("utf-8")
    shared_state.values["database"]("sessions").update_store("dd", session_string)
    clear_hostname_issue(hostname)
    return dd_session


def _blank_dd_credentials(shared_state):
    shared_state.values["config"]("DD").save("user", "")
    shared_state.values["config"]("DD").save("password", "")


def retrieve_and_validate_session(shared_state):
    if not is_site_usable(shared_state, hostname):
        debug("Site not usable (login skipped or no credentials)")
        return None

    session_string = shared_state.values["database"]("sessions").retrieve("dd")
    if not session_string:
        dd_session = create_and_persist_session(shared_state)
    else:
        try:
            serialized_session = base64.b64decode(session_string.encode("utf-8"))
            dd_session = pickle.loads(serialized_session)
            if not isinstance(dd_session, requests.Session):
                raise ValueError(
                    "Retrieved object is not a valid requests.Session instance."
                )
        except Exception as e:
            info(f"Session retrieval failed: {e}")
            mark_hostname_issue(hostname, "session", e)
            dd_session = create_and_persist_session(shared_state)

    return dd_session
