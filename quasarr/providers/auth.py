# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import base64
import hashlib
import hmac
import json
import os
import time
from functools import wraps

from bottle import abort, redirect, request, response

import quasarr.providers.html_images as images
from quasarr.providers.version import get_version
from quasarr.storage.config import Config

# Auth configuration from environment
AUTH_USER = os.environ.get("USER", "")
AUTH_PASS = os.environ.get("PASS", "")
AUTH_TYPE = os.environ.get("AUTH", "").lower()

# Cookie settings
COOKIE_NAME = "quasarr_session"
COOKIE_MAX_AGE = 30 * 24 * 60 * 60  # 30 days

# Stable secret derived from PASS (restart-safe)
_SECRET_KEY = hashlib.sha256(AUTH_PASS.encode("utf-8")).digest()


def is_auth_enabled():
    """Check if authentication is enabled (both USER and PASS set)."""
    return bool(AUTH_USER and AUTH_PASS)


def is_form_auth():
    """Check if form-based auth is enabled."""
    return AUTH_TYPE == "form"


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def _sign(data: bytes) -> bytes:
    return hmac.new(_SECRET_KEY, data, hashlib.sha256).digest()


def _mask_user(user: str) -> str:
    """
    One-way masked user identifier.
    Stable across restarts, not reversible.
    """
    return hashlib.sha256(f"user:{user}".encode("utf-8")).hexdigest()


def _create_session_cookie(user: str) -> str:
    """
    Stateless, signed cookie.
    Stores only masked user + expiry.
    """
    payload = {
        "u": _mask_user(user),
        "exp": int(time.time()) + COOKIE_MAX_AGE,
    }
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    sig = _sign(raw)
    return f"{_b64encode(raw)}.{_b64encode(sig)}"


def _invalidate_cookie():
    try:
        response.delete_cookie(COOKIE_NAME, path="/")
    except Exception:
        pass


def _verify_session_cookie(value: str) -> bool:
    """
    Verify signature, expiry, and masked user.
    On ANY failure → force logout (cookie deletion).
    """
    try:
        if not value or "." not in value:
            raise ValueError

        raw_b64, sig_b64 = value.split(".", 1)
        raw = _b64decode(raw_b64)
        sig = _b64decode(sig_b64)

        if not hmac.compare_digest(sig, _sign(raw)):
            raise ValueError

        payload = json.loads(raw.decode("utf-8"))

        if payload.get("u") != _mask_user(AUTH_USER):
            raise ValueError

        if int(time.time()) > int(payload.get("exp", 0)):
            raise ValueError

        return True
    except Exception:
        _invalidate_cookie()
        return False


def check_basic_auth():
    """Check HTTP Basic Auth header. Returns True if valid."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Basic "):
        return False
    try:
        decoded = base64.b64decode(auth[6:]).decode("utf-8")
        user, passwd = decoded.split(":", 1)
        return user == AUTH_USER and passwd == AUTH_PASS
    except:
        return False


def check_form_auth():
    """Check session cookie. Returns True if valid."""
    cookie = request.get_cookie(COOKIE_NAME)
    return bool(cookie and _verify_session_cookie(cookie))


def require_basic_auth():
    """Send 401 response for Basic Auth."""
    response.status = 401
    response.set_header("WWW-Authenticate", 'Basic realm="Quasarr"')
    return "Authentication required"


def _render_login_page(error=None):
    """Render login form page using Quasarr styling."""
    error_html = (
        f'<p style="color: #dc3545; margin-bottom: 1rem;"><b>{error}</b></p>'
        if error
        else ""
    )
    next_url = request.query.get("next", "/")

    # Inline the centered HTML to avoid circular import
    return f'''<html>
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>Quasarr - Login</title>
        <link rel="icon" href="{images.favicon}" type="image/png">
        <style>
            :root {{
                --bg-color: #ffffff;
                --fg-color: #212529;
                --card-bg: #ffffff;
                --card-shadow: rgba(0, 0, 0, 0.1);
                --primary: #0d6efd;
                --secondary: #6c757d;
                --spacing: 1rem;
            }}
            @media (prefers-color-scheme: dark) {{
                :root {{
                    --bg-color: #181a1b;
                    --fg-color: #f1f1f1;
                    --card-bg: #242526;
                    --card-shadow: rgba(0, 0, 0, 0.5);
                }}
            }}
            *, *::before, *::after {{ box-sizing: border-box; }}
            html, body {{
                margin: 0; padding: 0; width: 100%; height: 100%;
                background-color: var(--bg-color); color: var(--fg-color);
                font-family: system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif;
                line-height: 1.6; display: flex; flex-direction: column; min-height: 100vh;
            }}
            .outer {{ flex: 1; display: flex; justify-content: center; align-items: center; padding: var(--spacing); }}
            .inner {{
                background-color: var(--card-bg); border-radius: 1rem;
                box-shadow: 0 0.5rem 1.5rem var(--card-shadow);
                padding: calc(var(--spacing) * 2); text-align: center; width: 100%; max-width: 400px;
            }}
            .logo {{ height: 64px; width: 64px; vertical-align: middle; margin-right: 0.5rem; }}
            h1 {{ margin: 0 0 1rem 0; font-size: 1.75rem; }}
            h2 {{ margin: 0 0 1.5rem 0; font-size: 1.25rem; font-weight: 500; }}
            label {{ display: block; text-align: left; margin-bottom: 0.25rem; font-weight: 500; }}
            input[type="text"], input[type="password"] {{
                width: 100%; padding: 0.5rem; margin-bottom: 1rem;
                border: 1px solid var(--secondary); border-radius: 0.5rem;
                font-size: 1rem; background: var(--card-bg); color: var(--fg-color);
            }}
            .btn-primary {{
                background-color: var(--primary); color: #fff; border: 1.5px solid #0856c7;
                padding: 0.5rem 1.5rem; font-size: 1rem; border-radius: 0.5rem;
                font-weight: 500; cursor: pointer; width: 100%;
            }}
            .btn-primary:hover {{ background-color: #0b5ed7; }}
            footer {{ text-align: center; font-size: 0.75rem; color: var(--secondary); padding: 0.5rem 0; }}
        </style>
    </head>
    <body>
        <div class="outer">
            <div class="inner">
                <h1><img src="{images.logo}" class="logo" alt="Quasarr"/>Quasarr</h1>
                {error_html}
                <form method="post" action="/login">
                    <input type="hidden" name="next" value="{next_url}">
                    <label for="username">Username</label>
                    <input type="text" id="username" name="username" autocomplete="username" required>
                    <label for="password">Password</label>
                    <input type="password" id="password" name="password" autocomplete="current-password" required>
                    <button type="submit" class="btn-primary">Login</button>
                </form>
            </div>
        </div>
        <footer>Quasarr v.{get_version()}</footer>
    </body>
    </html>'''


def _handle_login_post():
    """Handle login form submission."""
    username = request.forms.get("username", "")
    password = request.forms.get("password", "")
    next_url = request.forms.get("next", "/")

    if username == AUTH_USER and password == AUTH_PASS:
        cookie = _create_session_cookie(username)
        secure_flag = request.url.startswith("https://")
        response.set_cookie(
            COOKIE_NAME,
            cookie,
            max_age=COOKIE_MAX_AGE,
            path="/",
            httponly=True,
            secure=secure_flag,
            samesite="Lax",
        )
        redirect(next_url)
    else:
        _invalidate_cookie()
        return _render_login_page("Invalid username or password")


def _handle_logout():
    _invalidate_cookie()
    redirect("/login")


def show_logout_link():
    """Returns True if logout link should be shown (form auth enabled and authenticated)."""
    return is_auth_enabled() and is_form_auth() and check_form_auth()


def add_auth_routes(app):
    """Add login/logout routes to a Bottle app (for form auth only)."""
    if not is_auth_enabled():
        return

    if is_form_auth():

        @app.get("/login")
        def login_get():
            if check_form_auth():
                redirect("/")
            return _render_login_page()

        @app.post("/login")
        def login_post():
            return _handle_login_post()

        @app.get("/logout")
        def logout():
            return _handle_logout()


def add_auth_hook(app, whitelist_prefixes=[], whitelist_suffixes=[]):
    """Add authentication hook to a Bottle app.

    Args:
        app: Bottle application
        whitelist_prefixes: List of path prefixes to skip auth (e.g., ['/api/', '/sponsors_helper/'])
    """
    if whitelist_prefixes is None:
        whitelist_prefixes = []

    @app.hook("before_request")
    def auth_hook():
        if not is_auth_enabled():
            return

        path = request.path

        # Always allow login/logout
        if path in ["/login", "/logout"]:
            return

        # Check whitelist prefixes
        for prefix in whitelist_prefixes:
            if path.startswith(prefix):
                return

        # Check whitelist suffixes:
        for suffix in whitelist_suffixes:
            if path.endswith(suffix):
                return

        # Check authentication
        if is_form_auth():
            if not check_form_auth():
                _invalidate_cookie()
                redirect(f"/login?next={path}")
        else:
            if not check_basic_auth():
                return require_basic_auth()


def require_api_key(func):
    @wraps(func)
    def decorated(*args, **kwargs):
        api_key = Config("API").get("key")
        if not request.query.apikey:
            return abort(401, "Missing API Key")
        if request.query.apikey != api_key:
            return abort(403, "Invalid API Key")
        return func(*args, **kwargs)

    return decorated
