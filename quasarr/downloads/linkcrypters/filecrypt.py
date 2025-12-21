# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import base64
import json
import random
import re
import xml.dom.minidom
from urllib.parse import urlparse

import dukpy
import requests
from Cryptodome.Cipher import AES
from bs4 import BeautifulSoup

from quasarr.providers.cloudflare import is_cloudflare_challenge, ensure_session_cf_bypassed
from quasarr.providers.log import info, debug


class CNL:
    def __init__(self, crypted_data):
        debug("Initializing CNL with crypted_data.")
        self.crypted_data = crypted_data

    def jk_eval(self, f_def):
        debug("Evaluating JavaScript key function.")
        js_code = f"""
        {f_def}
        f();
        """

        result = dukpy.evaljs(js_code).strip()
        debug("JavaScript evaluation complete.")
        return result

    def aes_decrypt(self, data, key):
        debug("Starting AES decrypt.")
        try:
            encrypted_data = base64.b64decode(data)
            debug("Base64 decode for AES decrypt successful.")
        except Exception as e:
            debug("Base64 decode for AES decrypt failed.")
            raise ValueError("Failed to decode base64 data") from e

        try:
            key_bytes = bytes.fromhex(key)
            debug("Key successfully converted from hex.")
        except Exception as e:
            debug("Failed converting key from hex.")
            raise ValueError("Failed to convert key to bytes") from e

        iv = key_bytes
        cipher = AES.new(key_bytes, AES.MODE_CBC, iv)

        try:
            decrypted_data = cipher.decrypt(encrypted_data)
            debug("AES decrypt operation successful.")
        except ValueError as e:
            debug("AES decrypt operation failed.")
            raise ValueError("Decryption failed") from e

        try:
            decoded = decrypted_data.decode('utf-8').replace('\x00', '').replace('\x08', '')
            debug("Decoded AES output successfully.")
            return decoded
        except UnicodeDecodeError as e:
            debug("Failed decoding decrypted AES output.")
            raise ValueError("Failed to decode decrypted data") from e

    def decrypt(self):
        debug("Starting Click'N'Load decrypt sequence.")
        crypted = self.crypted_data[2]
        jk = "function f(){ return \'" + self.crypted_data[1] + "';}"
        key = self.jk_eval(jk)
        uncrypted = self.aes_decrypt(crypted, key)
        urls = [result for result in uncrypted.split("\r\n") if len(result) > 0]
        debug(f"Extracted {len(urls)} URLs from CNL decrypt.")
        return urls


class DLC:
    def __init__(self, shared_state, dlc_file):
        debug("Initializing DLC decrypt handler.")
        self.shared_state = shared_state
        self.data = dlc_file
        self.KEY = b"cb99b5cbc24db398"
        self.IV = b"9bc24cb995cb8db3"
        self.API_URL = "http://service.jdownloader.org/dlcrypt/service.php?srcType=dlc&destType=pylo&data="

    def parse_packages(self, start_node):
        debug("Parsing DLC packages from XML.")
        return [
            (
                base64.b64decode(node.getAttribute("name")).decode("utf-8"),
                self.parse_links(node)
            )
            for node in start_node.getElementsByTagName("package")
        ]

    def parse_links(self, start_node):
        debug("Parsing DLC links in package.")
        return [
            base64.b64decode(node.getElementsByTagName("url")[0].firstChild.data).decode("utf-8")
            for node in start_node.getElementsByTagName("file")
        ]

    def decrypt(self):
        debug("Starting DLC decrypt flow.")
        if not isinstance(self.data, bytes):
            debug("DLC data type invalid.")
            raise TypeError("data must be bytes.")

        all_urls = []

        try:
            debug("Preparing DLC data buffer.")
            data = self.data.strip()
            data += b"=" * (-len(data) % 4)

            dlc_key = data[-88:].decode("utf-8")
            dlc_data = base64.b64decode(data[:-88])
            debug("DLC base64 decode successful.")

            headers = {'User-Agent': self.shared_state.values["user_agent"]}

            debug("Requesting DLC decryption service.")
            dlc_content = requests.get(self.API_URL + dlc_key, headers=headers, timeout=10).content.decode("utf-8")

            rc = base64.b64decode(re.search(r"<rc>(.+)</rc>", dlc_content, re.S).group(1))[:16]
            debug("Received DLC RC block.")

            cipher = AES.new(self.KEY, AES.MODE_CBC, self.IV)
            key = iv = cipher.decrypt(rc)
            debug("Decrypted DLC key material.")

            cipher = AES.new(key, AES.MODE_CBC, iv)
            xml_data = base64.b64decode(cipher.decrypt(dlc_data)).decode("utf-8")
            debug("Final DLC decrypt successful.")

            root = xml.dom.minidom.parseString(xml_data).documentElement
            content_node = root.getElementsByTagName("content")[0]
            debug("Parsed DLC XML content.")

            packages = self.parse_packages(content_node)
            debug(f"Found {len(packages)} DLC packages.")

            for package in packages:
                urls = package[1]
                all_urls.extend(urls)

        except Exception as e:
            info("DLC Error: " + str(e))
            return None

        debug(f"DLC decrypt yielded {len(all_urls)} URLs.")
        return all_urls


def get_filecrypt_links(shared_state, token, title, url, password=None, mirror=None):
    info("Attempting to decrypt Filecrypt link: " + url)
    debug("Initializing Filecrypt session & headers.")
    session = requests.Session()
    headers = {'User-Agent': shared_state.values["user_agent"]}

    debug("Ensuring Cloudflare bypass is ready.")
    session, headers, output = ensure_session_cf_bypassed(info, shared_state, session, url, headers)
    if not session or not output:
        debug("Cloudflare bypass failed.")
        return False

    soup = BeautifulSoup(output.text, 'html.parser')
    debug("Parsed initial Filecrypt HTML.")

    password_field = None
    try:
        debug("Attempting password field auto-detection.")
        input_elem = soup.find('input', attrs={'type': 'password'})
        if not input_elem:
            input_elem = soup.find('input', placeholder=lambda v: v and 'password' in v.lower())
        if not input_elem:
            input_elem = soup.find('input',
                                   attrs={'name': lambda v: v and ('pass' in v.lower() or 'password' in v.lower())})
        if input_elem and input_elem.has_attr('name'):
            password_field = input_elem['name']
            info("Password field name identified: " + password_field)
            debug(f"Password field detected: {password_field}")
    except Exception as e:
        info(f"Password-field detection error: {e}")
        debug("Password-field detection error raised.")

    if password and password_field:
        info("Using Password: " + password)
        debug("Submitting password via POST.")
        post_headers = {'User-Agent': shared_state.values["user_agent"],
                        'Content-Type': 'application/x-www-form-urlencoded'}
        data = {password_field: password}
        try:
            output = session.post(output.url, data=data, headers=post_headers, timeout=30)
            debug("Password POST request successful.")
        except requests.RequestException as e:
            info(f"POSTing password failed: {e}")
            debug("Password POST request failed.")
            return False

        if output.status_code == 403 or is_cloudflare_challenge(output.text):
            info("Encountered Cloudflare after password POST. Re-running FlareSolverr...")
            debug("Cloudflare reappeared after password submit, retrying bypass.")
            session, headers, output = ensure_session_cf_bypassed(info, shared_state, session, output.url, headers)
            if not session or not output:
                debug("Cloudflare bypass failed after password POST.")
                return False

    url = output.url
    soup = BeautifulSoup(output.text, 'html.parser')
    debug("Re-parsed HTML after password submit or initial load.")

    if bool(soup.find_all("input", {"id": "p4assw0rt"})):
        info(f"Password was wrong or missing. Could not get links for {title}")
        debug("Incorrect password detected via p4assw0rt.")
        return False

    no_captcha_present = bool(soup.find("form", {"class": "cnlform"}))
    if no_captcha_present:
        info("No CAPTCHA present. Skipping token!")
        debug("Detected no CAPTCHA (CNL direct form).")
    else:
        circle_captcha = bool(soup.find_all("div", {"class": "circle_captcha"}))
        debug(f"Circle captcha present: {circle_captcha}")
        i = 0
        while circle_captcha and i < 3:
            debug(f"Submitting fake circle captcha click attempt {i+1}.")
            random_x = str(random.randint(100, 200))
            random_y = str(random.randint(100, 200))
            output = session.post(url, data="buttonx.x=" + random_x + "&buttonx.y=" + random_y,
                                  headers={'User-Agent': shared_state.values["user_agent"],
                                           'Content-Type': 'application/x-www-form-urlencoded'})
            url = output.url
            soup = BeautifulSoup(output.text, 'html.parser')
            circle_captcha = bool(soup.find_all("div", {"class": "circle_captcha"}))
            i += 1
            debug(f"Circle captcha still present: {circle_captcha}")

        debug("Submitting final CAPTCHA token.")
        output = session.post(url, data="cap_token=" + token, headers={'User-Agent': shared_state.values["user_agent"],
                                                                       'Content-Type': 'application/x-www-form-urlencoded'})
    url = output.url

    if "/404.html" in url:
        info("Filecrypt returned 404 - current IP is likely banned or the link is offline.")
        debug("Detected Filecrypt 404 page.")

    soup = BeautifulSoup(output.text, 'html.parser')
    debug("Parsed post-captcha response HTML.")

    solved = bool(soup.find_all("div", {"class": "container"}))
    if not solved:
        info("Token rejected by Filecrypt! Try another CAPTCHA to proceed...")
        debug("Token rejected; no 'container' div found.")
        return False
    else:
        debug("CAPTCHA token accepted by Filecrypt.")

        season_number = ""
        episode_number = ""
        episode_in_title = re.findall(r'.*\.s(\d{1,3})e(\d{1,3})\..*', title, re.IGNORECASE)
        season_in_title = re.findall(r'.*\.s(\d{1,3})\..*', title, re.IGNORECASE)
        debug("Attempting episode/season number parsing from title.")

        if episode_in_title:
            try:
                season_number = str(int(episode_in_title[0][0]))
                episode_number = str(int(episode_in_title[0][1]))
                debug(f"Detected S{season_number}E{episode_number} from title.")
            except:
                debug("Failed parsing S/E numbers from title.")
                pass
        elif season_in_title:
            try:
                season_number = str(int(season_in_title[0]))
                debug(f"Detected season {season_number} from title.")
            except:
                debug("Failed parsing season number from title.")
                pass

        season = ""
        episode = ""
        tv_show_selector = soup.find("div", {"class": "dlpart"})
        debug(f"TV show selector found: {bool(tv_show_selector)}")

        if tv_show_selector:

            season = "season="
            episode = "episode="

            season_selection = soup.find("div", {"id": "selbox_season"})
            try:
                if season_selection:
                    season += str(season_number)
                    debug(f"Assigned season parameter: {season}")
            except:
                debug("Failed assigning season parameter.")
                pass

            episode_selection = soup.find("div", {"id": "selbox_episode"})
            try:
                if episode_selection:
                    episode += str(episode_number)
                    debug(f"Assigned episode parameter: {episode}")
            except:
                debug("Failed assigning episode parameter.")
                pass

        if episode_number and not episode:
            info(f"Missing select for episode number {episode_number}! Expect undesired links in the output.")
            debug("Episode number present but no episode selector container found.")

        links = []

        mirrors = []
        mirrors_available = soup.select("a[href*=mirror]")
        debug(f"Mirrors available: {len(mirrors_available)}")

        if not mirror and mirrors_available:
            for mirror in mirrors_available:
                try:
                    mirror_query = mirror.get("href").split("?")[1]
                    base_url = url.split("?")[0] if "mirror" in url else url
                    mirrors.append(f"{base_url}?{mirror_query}")
                    debug(f"Discovered mirror: {mirrors[-1]}")
                except IndexError:
                    debug("Mirror parsing failed due to missing '?'.")
                    continue
        else:
            mirrors = [url]
            debug("Using direct URL as only mirror.")

        for mirror in mirrors:
            if not len(mirrors) == 1:
                debug(f"Loading mirror: {mirror}")
                output = session.get(mirror, headers=headers)
                url = output.url
                soup = BeautifulSoup(output.text, 'html.parser')

            try:
                debug("Attempting Click'n'Load decrypt.")
                crypted_payload = soup.find("form", {"class": "cnlform"}).get('onsubmit')
                crypted_data = re.findall(r"'(.*?)'", crypted_payload)
                if not title:
                    title = crypted_data[3]
                crypted_data = [
                    crypted_data[0],
                    crypted_data[1],
                    crypted_data[2],
                    title
                ]

                if episode and season:
                    debug("Applying episode/season filtering to CNL.")
                    domain = urlparse(url).netloc
                    filtered_cnl_secret = soup.find("input", {"name": "hidden_cnl_id"}).attrs["value"]
                    filtered_cnl_link = f"https://{domain}/_CNL/{filtered_cnl_secret}.html?{season}&{episode}"
                    filtered_cnl_result = session.post(filtered_cnl_link,
                                                       headers=headers)
                    if filtered_cnl_result.status_code == 200:
                        filtered_cnl_data = json.loads(filtered_cnl_result.text)
                        if filtered_cnl_data["success"]:
                            debug("Season/Episode filter applied successfully.")
                            crypted_data = [
                                crypted_data[0],
                                filtered_cnl_data["data"][0],
                                filtered_cnl_data["data"][1],
                                title
                            ]
                links.extend(CNL(crypted_data).decrypt())
            except:
                debug("CNL decrypt failed; trying DLC fallback.")
                if "The owner of this folder has deactivated all hosts in this container in their settings." in soup.text:
                    info(f"Mirror deactivated by the owner: {mirror}")
                    debug("Mirror deactivated detected in page text.")
                    continue

                info("Click'n'Load not found! Falling back to DLC...")
                try:
                    debug("Attempting DLC fallback.")
                    crypted_payload = soup.find("button", {"class": "dlcdownload"}).get("onclick")
                    crypted_data = re.findall(r"'(.*?)'", crypted_payload)
                    dlc_secret = crypted_data[0]
                    domain = urlparse(url).netloc
                    if episode and season:
                        dlc_link = f"https://{domain}/DLC/{dlc_secret}.dlc?{episode}&{season}"
                    else:
                        dlc_link = f"https://{domain}/DLC/{dlc_secret}.dlc"
                    dlc_file = session.get(dlc_link, headers=headers).content
                    links.extend(DLC(shared_state, dlc_file).decrypt())
                except:
                    debug("DLC fallback failed, trying button fallback.")
                    info("DLC not found! Falling back to first available download Button...")

                    base_url = urlparse(url).netloc
                    phpsessid = session.cookies.get('PHPSESSID')
                    if not phpsessid:
                        info("PHPSESSID cookie not found! Cannot proceed with download links extraction.")
                        debug("Missing PHPSESSID cookie.")
                        return False

                    results = []
                    debug("Parsing fallback buttons for download links.")

                    for button in soup.find_all('button'):
                        data_attrs = [v for k, v in button.attrs.items() if k.startswith('data-') and k != 'data-i18n']
                        if not data_attrs:
                            continue

                        link_id = data_attrs[0]
                        row = button.find_parent('tr')
                        mirror_tag = row.find('a', class_='external_link') if row else None
                        mirror_name = mirror_tag.get_text(strip=True) if mirror_tag else 'unknown'
                        full_url = f"http://{base_url}/Link/{link_id}.html"
                        results.append((full_url, mirror_name))

                    sorted_results = sorted(results, key=lambda x: 0 if 'rapidgator' in x[1].lower() else 1)
                    debug(f"Found {len(sorted_results)} fallback link candidates.")

                    for result_url, mirror in sorted_results:
                        info("You must solve circlecaptcha separately!")
                        debug(f'Session "{phpsessid}" for {result_url} will not live long. Submit new CAPTCHA quickly!')
                        return {
                            "status": "replaced",
                            "replace_url": result_url,
                            "mirror": mirror,
                            "session": phpsessid
                        }

    if not links:
        info("No links found in Filecrypt response!")
        debug("Extraction completed but yielded no links.")
        return False

    debug(f"Returning success with {len(links)} extracted links.")
    return {
        "status": "success",
        "links": links
    }
