# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import base64
import pickle

import requests

from quasarr.providers.hostname_issues import clear_hostname_issue, mark_hostname_issue
from quasarr.providers.log import debug, info
from quasarr.providers.utils import is_site_usable

hostname = "nx"


def create_and_persist_session(shared_state):
    nx = shared_state.values["config"]("Hostnames").get("nx")

    nx_session = requests.Session()

    cookies = {}
    headers = {
        "User-Agent": shared_state.values["user_agent"],
    }

    json_data = {
        "username": shared_state.values["config"]("NX").get("user"),
        "password": shared_state.values["config"]("NX").get("password"),
    }

    r = nx_session.post(
        f"https://{nx}/api/user/auth",
        cookies=cookies,
        headers=headers,
        json=json_data,
        timeout=10,
    )
    r.raise_for_status()

    error = False
    if r.status_code == 200:
        try:
            response_data = r.json()
            if response_data.get("err", {}).get("status") == 403:
                info("Invalid NX credentials provided.")
                mark_hostname_issue(hostname, "session", "Invalid credentials")
                error = True
            elif response_data.get("user").get("username") != shared_state.values[
                "config"
            ]("NX").get("user"):
                info("Invalid NX response on login.")
                mark_hostname_issue(hostname, "session", "Invalid login response")
                error = True
            else:
                sessiontoken = response_data.get("user").get("sessiontoken")
                nx_session.cookies.set("sessiontoken", sessiontoken, domain=nx)
        except ValueError:
            info("Could not parse NX response on login.")
            mark_hostname_issue(hostname, "session", "Could not parse login response")
            error = True

        if error:
            shared_state.values["config"]("NX").save("user", "")
            shared_state.values["config"]("NX").save("password", "")
            return None

        serialized_session = pickle.dumps(nx_session)
        session_string = base64.b64encode(serialized_session).decode("utf-8")
        shared_state.values["database"]("sessions").update_store("nx", session_string)
        clear_hostname_issue(hostname)
        return nx_session
    else:
        info("Could not create NX session")
        mark_hostname_issue(hostname, "session", f"HTTP {r.status_code}")
        return None


def retrieve_and_validate_session(shared_state):
    if not is_site_usable(shared_state, hostname):
        debug(f"Skipping {hostname}: site not usable (login skipped or no credentials)")
        return None

    session_string = shared_state.values["database"]("sessions").retrieve("nx")
    if not session_string:
        nx_session = create_and_persist_session(shared_state)
    else:
        try:
            serialized_session = base64.b64decode(session_string.encode("utf-8"))
            nx_session = pickle.loads(serialized_session)
            if not isinstance(nx_session, requests.Session):
                raise ValueError(
                    "Retrieved object is not a valid requests.Session instance."
                )
        except Exception as e:
            info(f"Session retrieval failed: {e}")
            mark_hostname_issue(hostname, "session", str(e))
            nx_session = create_and_persist_session(shared_state)

    return nx_session
