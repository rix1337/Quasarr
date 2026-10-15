# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import base64
import hashlib
import hmac
import html
import json
import os
import time
from functools import wraps
from urllib.parse import urlsplit

from bottle import abort, redirect, request, response

import quasarr.providers.html_images as images
from quasarr.providers.version import get_version
from quasarr.storage.config import Config

# Auth configuration from environment
_AUTH_USER = os.environ.get("USER", "")
_AUTH_PASS = os.environ.get("PASS", "")
_AUTH_TYPE = os.environ.get("AUTH", "form").lower()

# Cookie settings
_COOKIE_NAME = "quasarr_session"
_COOKIE_MAX_AGE = 30 * 24 * 60 * 60  # 30 days

# Stable secret derived from PASS (restart-safe)
_SECRET_KEY = hashlib.sha256(_AUTH_PASS.encode("utf-8")).digest()

_AUTH_MODE_ATTR = "__quasarr_auth_mode__"
_AUTH_MODE_PUBLIC = "public"
_AUTH_MODE_BROWSER = "browser"
_AUTH_MODE_API_KEY = "api_key"


def is_auth_enabled():
    """Check if authentication is enabled (both USER and PASS set)."""
    return bool(_AUTH_USER and _AUTH_PASS)


def is_form_auth():
    """Check if form-based auth is enabled."""
    return _AUTH_TYPE == "form"


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
        "exp": int(time.time()) + _COOKIE_MAX_AGE,
    }
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    sig = _sign(raw)
    return f"{_b64encode(raw)}.{_b64encode(sig)}"


def _invalidate_cookie():
    try:
        response.delete_cookie(_COOKIE_NAME, path="/")
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

        if payload.get("u") != _mask_user(_AUTH_USER):
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
        return user == _AUTH_USER and passwd == _AUTH_PASS
    except:
        return False


def check_form_auth():
    """Check session cookie. Returns True if valid."""
    cookie = request.get_cookie(_COOKIE_NAME)
    return bool(cookie and _verify_session_cookie(cookie))


def require_basic_auth():
    """Send 401 response for Basic Auth."""
    response.status = 401
    response.set_header("WWW-Authenticate", 'Basic realm="Quasarr"')
    return "Authentication required"


def is_browser_authenticated():
    """Check whether the current browser request is authenticated."""
    if not is_auth_enabled():
        return False
    if is_form_auth():
        return check_form_auth()
    return check_basic_auth()


def _mark_auth_mode(func, mode):
    setattr(func, _AUTH_MODE_ATTR, mode)
    return func


def public_endpoint(func):
    """Mark a route as public."""
    return _mark_auth_mode(func, _AUTH_MODE_PUBLIC)


def _normalize_next_url(next_url):
    """Allow only internal post-login redirects."""
    if not next_url:
        return "/"

    candidate = str(next_url).strip()
    if not candidate.startswith("/") or candidate.startswith("//"):
        return "/"

    parsed = urlsplit(candidate)
    if parsed.scheme or parsed.netloc or not parsed.path.startswith("/"):
        return "/"
    if parsed.path in {"/login", "/logout"}:
        return "/"

    normalized = parsed.path or "/"
    if parsed.query:
        normalized += f"?{parsed.query}"
    return normalized


def _render_login_page(error=None):
    """Render login form page using Quasarr styling."""
    error_html = (
        f'<p style="color: #dc3545; margin-bottom: 1rem;"><b>{html.escape(str(error))}</b></p>'
        if error
        else ""
    )
    next_url = html.escape(
        _normalize_next_url(request.query.get("next", "/")), quote=True
    )

    # Inline the centered HTML to avoid circular import
    return f'''<html>
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>Quasarr - Login</title>
        <link rel="icon" href="{images.favicon}" type="image/png" sizes="16x16">
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
            .logo {{ height: 64px; width: 64px; vertical-align: middle; margin-right: 0.5rem; filter: invert(1); }}
            @media (prefers-color-scheme: dark) {{
                .logo {{ filter: none; }}
            }}
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
    next_url = _normalize_next_url(request.forms.get("next", "/"))

    if username == _AUTH_USER and password == _AUTH_PASS:
        cookie = _create_session_cookie(username)
        secure_flag = request.url.startswith("https://")
        response.set_cookie(
            _COOKIE_NAME,
            cookie,
            max_age=_COOKIE_MAX_AGE,
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
        @public_endpoint
        def login_get():
            if check_form_auth():
                redirect("/")
            return _render_login_page()

        @app.post("/login")
        @public_endpoint
        def login_post():
            return _handle_login_post()

        @app.get("/logout")
        def logout():
            return _handle_logout()


def add_auth_hook(app, whitelist=None):
    """Install the Quasarr authentication policy on a Bottle app.

    Args:
        app: Bottle application
        whitelist: List of path prefixes or suffixes to keep public
    """
    if whitelist is None:
        whitelist = []

    if any(getattr(plugin, "name", None) == "quasarr-auth" for plugin in app.plugins):
        return

    class AuthPlugin:
        name = "quasarr-auth"
        api = 2

        def __init__(self, public_whitelist):
            self.public_whitelist = tuple(public_whitelist)

        def _is_public_rule(self, rule):
            for item in self.public_whitelist:
                if rule.startswith(item) or rule.endswith(item):
                    return True
            return False

        def _get_auth_mode(self, callback, route):
            if self._is_public_rule(route.rule):
                return _AUTH_MODE_PUBLIC
            return getattr(callback, _AUTH_MODE_ATTR, _AUTH_MODE_BROWSER)

        def apply(self, callback, route):
            mode = self._get_auth_mode(callback, route)
            if mode == _AUTH_MODE_PUBLIC:
                return callback
            if mode == _AUTH_MODE_API_KEY:

                @wraps(callback)
                def api_key_wrapper(*args, **kwargs):
                    api_key = Config("API").get("key")
                    request_api_key = _get_request_api_key()
                    if not request_api_key:
                        return abort(401, "Missing API Key")
                    if request_api_key != api_key:
                        return abort(403, "Invalid API Key")
                    return callback(*args, **kwargs)

                return api_key_wrapper

            @wraps(callback)
            def browser_wrapper(*args, **kwargs):
                if not is_auth_enabled():
                    return callback(*args, **kwargs)

                path = request.path.split("?")[0]

                if is_form_auth():
                    if not check_form_auth():
                        _invalidate_cookie()
                        if path == "/logout":
                            redirect("/login")
                        redirect(f"/login?next={path}")
                else:
                    if not check_basic_auth():
                        return require_basic_auth()

                return callback(*args, **kwargs)

            return browser_wrapper

    app.install(AuthPlugin(whitelist))


def _get_request_api_key():
    api_key = request.query.get("apikey") or request.forms.get("apikey")
    if api_key:
        return api_key

    api_key = request.headers.get("X-API-Key") or request.headers.get("X-Api-Key")
    if api_key:
        return api_key

    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header[7:].strip()

    return None


def require_api_key(func):
    """Mark a route to require the Quasarr API key."""
    return _mark_auth_mode(func, _AUTH_MODE_API_KEY)


def require_browser_auth(func):
    """Mark a route to require browser authentication."""
    return _mark_auth_mode(func, _AUTH_MODE_BROWSER)


def audit_route_auth_modes(app, api_key_prefixes=None, public_whitelist=None):
    """Fail fast if protected route groups are not explicitly API-key guarded."""
    if api_key_prefixes is None:
        api_key_prefixes = ()
    if public_whitelist is None:
        public_whitelist = ()

    violations = []
    for route in app.routes:
        rule = route.rule

        is_public = any(
            rule.startswith(item) or rule.endswith(item) for item in public_whitelist
        )
        mode = (
            _AUTH_MODE_PUBLIC
            if is_public
            else getattr(route.callback, _AUTH_MODE_ATTR, _AUTH_MODE_BROWSER)
        )

        if any(rule.startswith(prefix) for prefix in api_key_prefixes):
            if mode != _AUTH_MODE_API_KEY:
                violations.append(f"{route.method} {rule} -> {mode}")

    if violations:
        joined = ", ".join(sorted(violations))
        raise RuntimeError(f"Auth policy violation: {joined}")
