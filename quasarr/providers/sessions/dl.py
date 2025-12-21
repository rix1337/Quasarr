# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import base64
import pickle

import requests
from bs4 import BeautifulSoup

from quasarr.providers.log import info, debug

hostname = "dl"


def create_and_persist_session(shared_state):
    """
    Create and persist a session using user and password.
    
    Args:
        shared_state: Shared state object
    
    Returns:
        requests.Session or None
    """
    cfg = shared_state.values["config"]("Hostnames")
    host = cfg.get(hostname)
    credentials_cfg = shared_state.values["config"](hostname.upper())
    
    user = credentials_cfg.get("user")
    password = credentials_cfg.get("password")

    if not user or not password:
        info(f'Missing credentials for: "{hostname}" - user and password are required')
        return None

    sess = requests.Session()
    
    # Set user agent
    ua = shared_state.values["user_agent"]
    sess.headers.update({'User-Agent': ua})
    
    try:
        # Step 1: Get login page to retrieve CSRF token
        login_page_url = f'https://www.{host}/login/'
        login_page = sess.get(login_page_url, timeout=30)
        
        if login_page.status_code != 200:
            info(f'Failed to load login page for: "{hostname}" - Status {login_page.status_code}')
            return None
        
        # Extract CSRF token from login form
        soup = BeautifulSoup(login_page.text, 'html.parser')
        csrf_input = soup.find('input', {'name': '_xfToken'})
        
        if not csrf_input or not csrf_input.get('value'):
            info(f'Could not find CSRF token on login page for: "{hostname}"')
            return None
        
        csrf_token = csrf_input['value']
        
        # Step 2: Submit login form
        login_data = {
            'login': user,
            'password': password,
            '_xfToken': csrf_token,
            'remember': '1',
            '_xfRedirect': f'https://www.{host}/'
        }
        
        login_url = f'https://www.{host}/login/login'
        login_response = sess.post(login_url, data=login_data, timeout=30)
        
        # Step 3: Verify login success
        # Check if we're logged in by accessing the main page
        verify_response = sess.get(f'https://www.{host}/', timeout=30)
        
        if 'data-logged-in="true"' not in verify_response.text:
            info(f'Login verification failed for: "{hostname}" - invalid credentials or login failed')
            return None
        
        info(f'Session successfully created for: "{hostname}" using user/password')
    except Exception as e:
        info(f'Failed to create session for: "{hostname}" - {e}')
        return None

    # Persist session to database
    blob = pickle.dumps(sess)
    token = base64.b64encode(blob).decode("utf-8")
    shared_state.values["database"]("sessions").update_store(hostname, token)
    
    return sess


def retrieve_and_validate_session(shared_state):
    """
    Retrieve session from database or create a new one.
    
    Args:
        shared_state: Shared state object
    
    Returns:
        requests.Session or None
    """
    db = shared_state.values["database"]("sessions")
    token = db.retrieve(hostname)
    if not token:
        return create_and_persist_session(shared_state)

    try:
        blob = base64.b64decode(token.encode("utf-8"))
        sess = pickle.loads(blob)
        if not isinstance(sess, requests.Session):
            raise ValueError("Not a Session")
    except Exception as e:
        debug(f"{hostname}: session load failed: {e}")
        return create_and_persist_session(shared_state)

    return sess


def invalidate_session(shared_state):
    """
    Invalidate the current session.
    
    Args:
        shared_state: Shared state object
    """
    db = shared_state.values["database"]("sessions")
    db.delete(hostname)
    debug(f'Session for "{hostname}" marked as invalid!')


def _persist_session_to_db(shared_state, sess):
    """
    Serialize & store the given requests.Session into the database under `hostname`.
    
    Args:
        shared_state: Shared state object
        sess: requests.Session to persist
    """
    blob = pickle.dumps(sess)
    token = base64.b64encode(blob).decode("utf-8")
    shared_state.values["database"]("sessions").update_store(hostname, token)


def fetch_via_requests_session(shared_state, method: str, target_url: str, post_data: dict = None, get_params: dict = None, timeout: int = 30):
    """
    Execute request using the session.
    
    Args:
        shared_state: Shared state object
        method: "GET" or "POST"
        target_url: URL to fetch
        post_data: POST data (for POST requests)
        get_params: URL parameters (for GET requests)
        timeout: Request timeout in seconds
    
    Returns:
        Response object
    """
    sess = retrieve_and_validate_session(shared_state)
    if not sess:
        raise Exception(f"Could not retrieve valid session for {hostname}")

    # Execute request
    if method.upper() == "GET":
        resp = sess.get(target_url, params=get_params, timeout=timeout)
    else:  # POST
        resp = sess.post(target_url, data=post_data, timeout=timeout)

    # Re-persist cookies, since the site might have modified them during the request
    _persist_session_to_db(shared_state, sess)

    return resp
