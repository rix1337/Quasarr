# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import requests
from bs4 import BeautifulSoup


def is_cloudflare_challenge(html: str) -> bool:
    soup = BeautifulSoup(html, "html.parser")

    # Check <title>
    title = (soup.title.string or "").strip().lower() if soup.title else ""
    if "just a moment" in title or "attention required" in title:
        return True

    # Check known Cloudflare elements
    if soup.find(id="challenge-form"):
        return True
    if soup.find("div", {"class": "cf-browser-verification"}):
        return True
    if soup.find("div", {"id": "cf-challenge-running"}):
        return True

    # Check scripts referencing Cloudflare
    for script in soup.find_all("script", src=True):
        if "cdn-cgi/challenge-platform" in script["src"]:
            return True

    # Optional: look for Cloudflare comment or beacon
    if "data-cf-beacon" in html or "<!-- cloudflare -->" in html.lower():
        return True

    return False


def update_session_via_flaresolverr(info,
                                    shared_state,
                                    sess,
                                    target_url: str,
                                    timeout: int = 60):
    flaresolverr_url = shared_state.values["config"]('FlareSolverr').get('url')
    if not flaresolverr_url:
        info("Cannot proceed without FlareSolverr. Please set it up to try again!")
        return False

    fs_payload = {
        "cmd": "request.get",
        "url": target_url,
        "maxTimeout": timeout * 1000,
    }

    # Send the JSON request to FlareSolverr
    fs_headers = {"Content-Type": "application/json"}
    try:
        resp = requests.post(
            flaresolverr_url,
            headers=fs_headers,
            json=fs_payload,
            timeout=timeout + 10
        )
        resp.raise_for_status()
    except requests.exceptions.RequestException as e:
        info(f"Could not reach FlareSolverr: {e}")
        return {
            "status_code": None,
            "headers": {},
            "json": None,
            "text": "",
            "cookies": [],
            "error": f"FlareSolverr request failed: {e}"
        }
    except Exception as e:
        raise RuntimeError(f"Could not reach FlareSolverr: {e}")

    fs_json = resp.json()
    if fs_json.get("status") != "ok" or "solution" not in fs_json:
        raise RuntimeError(f"FlareSolverr did not return a valid solution: {fs_json.get('message', '<no message>')}")

    solution = fs_json["solution"]

    # Replace our requests.Session cookies with whatever FlareSolverr solved
    sess.cookies.clear()
    for ck in solution.get("cookies", []):
        sess.cookies.set(
            ck.get("name"),
            ck.get("value"),
            domain=ck.get("domain"),
            path=ck.get("path", "/")
        )
    return {"session": sess, "user_agent": solution.get("userAgent", None)}


def ensure_session_cf_bypassed(info, shared_state, session, url, headers):
    """
    Performs a GET and, if Cloudflare challenge or 403 is present, tries FlareSolverr.
    Returns tuple: (session, headers, response) or (None, None, None) on failure.
    """
    try:
        resp = session.get(url, headers=headers, timeout=30)
    except requests.RequestException as e:
        info(f"Initial GET failed: {e}")
        return None, None, None

    # If page is protected, try FlareSolverr
    if resp.status_code == 403 or is_cloudflare_challenge(resp.text):
        info("Encountered Cloudflare protection. Solving challenge with FlareSolverr...")
        flaresolverr_result = update_session_via_flaresolverr(info, shared_state, session, url)
        if not flaresolverr_result:
            info("FlareSolverr did not return a result.")
            return None, None, None

        # update session and possibly user-agent
        session = flaresolverr_result.get("session", session)
        user_agent = flaresolverr_result.get("user_agent")
        if user_agent and user_agent != shared_state.values.get("user_agent"):
            info("Updating User-Agent from FlareSolverr solution: " + user_agent)
            shared_state.update("user_agent", user_agent)
            headers = {'User-Agent': shared_state.values["user_agent"]}

        # re-fetch using the new session/headers
        try:
            resp = session.get(url, headers=headers, timeout=30)
        except requests.RequestException as e:
            info(f"GET after FlareSolverr failed: {e}")
            return None, None, None

        if resp.status_code == 403 or is_cloudflare_challenge(resp.text):
            info("Could not bypass Cloudflare protection with FlareSolverr!")
            return None, None, None

    return session, headers, resp


class FlareSolverrResponse:
    """
    Minimal Response-like object so it behaves like requests.Response.
    """

    def __init__(self, url, status_code, headers, text):
        self.url = url
        self.status_code = status_code
        self.headers = headers or {}
        self.text = text or ""
        self.content = self.text.encode("utf-8")

        # Cloudflare cookies are irrelevant here, but keep attribute for compatibility
        self.cookies = requests.cookies.RequestsCookieJar()

    def raise_for_status(self):
        if 400 <= self.status_code:
            raise requests.HTTPError(f"{self.status_code} Error for URL: {self.url}")


def flaresolverr_get(shared_state, url, timeout=60):
    """
    Core function for performing a GET request via FlareSolverr only.
    Used internally by FlareSolverrSession.get()
    """
    flaresolverr_url = shared_state.values["config"]('FlareSolverr').get('url')
    if not flaresolverr_url:
        raise RuntimeError("FlareSolverr URL not configured in shared_state.")

    payload = {
        "cmd": "request.get",
        "url": url,
        "maxTimeout": timeout * 1000
    }

    try:
        resp = requests.post(
            flaresolverr_url,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=timeout + 10
        )
        resp.raise_for_status()
    except Exception as e:
        raise RuntimeError(f"Error communicating with FlareSolverr: {e}")

    data = resp.json()

    if data.get("status") != "ok":
        raise RuntimeError(f"FlareSolverr returned error: {data.get('message')}")

    solution = data.get("solution", {})
    html = solution.get("response", "")
    status_code = solution.get("status", 200)
    url = solution.get("url", url)

    # headers → convert list-of-keyvals to dict
    fs_headers = {h["name"]: h["value"] for h in solution.get("headers", [])}

    # Update global UA if provided
    user_agent = solution.get("userAgent")
    if user_agent and user_agent != shared_state.values.get("user_agent"):
        shared_state.update("user_agent", user_agent)

    return FlareSolverrResponse(
        url=url,
        status_code=status_code,
        headers=fs_headers,
        text=html
    )
