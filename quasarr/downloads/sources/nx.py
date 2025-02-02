# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import base64
import pickle
import re

import requests
from bs4 import BeautifulSoup

from quasarr.providers.log import info


def create_and_persist_session(shared_state):
    nx = shared_state.values["config"]("Hostnames").get("nx")

    nx_session = requests.Session()

    cookies = {}
    headers = {
        'User-Agent': shared_state.values["user_agent"],
    }

    json_data = {
        'username': shared_state.values["config"]("NX").get("user"),
        'password': shared_state.values["config"]("NX").get("password")
    }

    nx_response = nx_session.post(f'https://{nx}/api/user/auth', cookies=cookies, headers=headers, json=json_data,
                                  timeout=10)

    error = False
    if nx_response.status_code == 200:
        try:
            response_data = nx_response.json()
            if response_data.get('err', {}).get('status') == 403:
                info("Invalid NX credentials provided.")
                error = True
            elif response_data.get('user').get('username') != shared_state.values["config"]("NX").get("user"):
                info("Invalid NX response on login.")
                error = True
            else:
                sessiontoken = response_data.get('user').get('sessiontoken')
                nx_session.cookies.set('sessiontoken', sessiontoken, domain=nx)
        except ValueError:
            info("Could not parse NX response on login.")
            error = True

        if error:
            shared_state.values["config"]("NX").save("user", "")
            shared_state.values["config"]("NX").save("password", "")
            return None

        serialized_session = pickle.dumps(nx_session)
        session_string = base64.b64encode(serialized_session).decode('utf-8')
        shared_state.values["database"]("sessions").update_store("nx", session_string)
        return nx_session
    else:
        info("Could not create NX session")
        return None


def retrieve_and_validate_session(shared_state):
    session_string = shared_state.values["database"]("sessions").retrieve("nx")
    if not session_string:
        nx_session = create_and_persist_session(shared_state)
    else:
        try:
            serialized_session = base64.b64decode(session_string.encode('utf-8'))
            nx_session = pickle.loads(serialized_session)
            if not isinstance(nx_session, requests.Session):
                raise ValueError("Retrieved object is not a valid requests.Session instance.")
        except Exception as e:
            info(f"Session retrieval failed: {e}")
            nx_session = create_and_persist_session(shared_state)

    return nx_session


def get_filer_folder_links(shared_state, url):
    try:
        headers = {
            'User-Agent': shared_state.values["user_agent"],
            'Referer': url
        }
        response = requests.get(url, headers=headers, timeout=10)
        links = []
        if response:
            soup = BeautifulSoup(response.content, 'html.parser')
            folder_links = soup.find_all('a', href=re.compile("/get/"))
            for link in folder_links:
                link = "https://filer.net" + link.get('href')
                if link not in links:
                    links.append(link)
        return links
    except:
        pass
    return url


def get_nx_download_links(shared_state, url, title):
    nx = shared_state.values["config"]("Hostnames").get("nx")

    if f"{nx}/release/" not in url:
        info("Link is not a Release link, could not proceed:" + url)

    nx_session = retrieve_and_validate_session(shared_state)
    if not nx_session:
        info(f"Could not retrieve valid session for {nx}")
        return []

    headers = {
        'User-Agent': shared_state.values["user_agent"],
        'Referer': url
    }

    json_data = {}

    url_segments = url.split('/')
    payload_url = '/'.join(url_segments[:-2]) + '/api/getLinks/' + url_segments[-1]

    payload = nx_session.post(payload_url,
                              headers=headers,
                              json=json_data,
                              timeout=10
                              )

    if payload.status_code == 200:
        try:
            payload = payload.json()
        except:
            info("Invalid response decrypting " + str(title) + " URL: " + str(url))
            shared_state.values["database"]("sessions").delete("nx")
            return []

    try:
        decrypted_url = payload['link'][0]['url']
        if decrypted_url:
            if "filer.net/folder/" in decrypted_url:
                urls = get_filer_folder_links(shared_state, decrypted_url)
            else:
                urls = [decrypted_url]
            return urls
    except:
        pass

    info("Something went wrong decrypting " + str(title) + " URL: " + str(url))
    shared_state.values["database"]("sessions").delete("nx")
    return []
