# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import base64
import pickle

import requests

from quasarr.providers.hostname_issues import clear_hostname_issue, mark_hostname_issue
from quasarr.providers.log import debug, info
from quasarr.providers.utils import is_site_usable

hostname = "dd"


def create_and_persist_session(shared_state):
    dd = shared_state.values["config"]("Hostnames").get("dd")

    dd_session = requests.Session()

    cookies = {}
    headers = {
        "User-Agent": shared_state.values["user_agent"],
    }

    data = {
        "username": shared_state.values["config"]("DD").get("user"),
        "password": shared_state.values["config"]("DD").get("password"),
        "ajax": "true",
        "Login": "true",
    }

    r = dd_session.post(
        f"https://{dd}/index/index",
        cookies=cookies,
        headers=headers,
        data=data,
        timeout=10,
    )
    r.raise_for_status()

    error = False
    if r.status_code == 200:
        try:
            response_data = r.json()
            if not response_data.get("loggedin"):
                info("DD rejected login.")
                mark_hostname_issue(hostname, "session", "Login rejected")
                raise ValueError
            session_id = r.cookies.get("PHPSESSID")
            if session_id:
                dd_session.cookies.set("PHPSESSID", session_id, domain=dd)
            else:
                info("Invalid DD response on login.")
                mark_hostname_issue(hostname, "session", "Invalid login response")
                error = True
        except ValueError:
            info("Could not parse DD response on login.")
            mark_hostname_issue(hostname, "session", "Could not parse login response")
            error = True

        if error:
            shared_state.values["config"]("DD").save("user", "")
            shared_state.values["config"]("DD").save("password", "")
            return None

        serialized_session = pickle.dumps(dd_session)
        session_string = base64.b64encode(serialized_session).decode("utf-8")
        shared_state.values["database"]("sessions").update_store("dd", session_string)
        clear_hostname_issue(hostname)
        return dd_session
    else:
        info("Could not create DD session")
        mark_hostname_issue(hostname, "session", f"HTTP {r.status_code}")
        return None


def retrieve_and_validate_session(shared_state):
    if not is_site_usable(shared_state, hostname):
        debug(f"Skipping {hostname}: site not usable (login skipped or no credentials)")
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
            mark_hostname_issue(hostname, "session", str(e))
            dd_session = create_and_persist_session(shared_state)

    return dd_session
