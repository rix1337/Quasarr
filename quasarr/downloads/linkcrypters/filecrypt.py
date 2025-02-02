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

from quasarr.providers.log import info


class CNL:
    def __init__(self, crypted_data):
        self.crypted_data = crypted_data

    def jk_eval(self, f_def):
        js_code = f"""
        {f_def}
        f();
        """

        result = dukpy.evaljs(js_code).strip()

        return result

    def aes_decrypt(self, data, key):
        try:
            encrypted_data = base64.b64decode(data)
        except Exception as e:
            raise ValueError("Failed to decode base64 data") from e

        try:
            key_bytes = bytes.fromhex(key)
        except Exception as e:
            raise ValueError("Failed to convert key to bytes") from e

        iv = key_bytes
        cipher = AES.new(key_bytes, AES.MODE_CBC, iv)

        try:
            decrypted_data = cipher.decrypt(encrypted_data)
        except ValueError as e:
            raise ValueError("Decryption failed") from e

        try:
            return decrypted_data.decode('utf-8').replace('\x00', '').replace('\x08', '')
        except UnicodeDecodeError as e:
            raise ValueError("Failed to decode decrypted data") from e

    def decrypt(self):
        crypted = self.crypted_data[2]
        jk = "function f(){ return \'" + self.crypted_data[1] + "';}"
        key = self.jk_eval(jk)
        uncrypted = self.aes_decrypt(crypted, key)
        urls = [result for result in uncrypted.split("\r\n") if len(result) > 0]

        return urls


class DLC:
    def __init__(self, shared_state, dlc_file):
        global user_agent
        self.shared_state = shared_state
        self.data = dlc_file
        self.KEY = b"cb99b5cbc24db398"
        self.IV = b"9bc24cb995cb8db3"
        self.API_URL = "http://service.jdownloader.org/dlcrypt/service.php?srcType=dlc&destType=pylo&data="

    def parse_packages(self, start_node):
        return [
            (
                base64.b64decode(node.getAttribute("name")).decode("utf-8"),
                self.parse_links(node)
            )
            for node in start_node.getElementsByTagName("package")
        ]

    def parse_links(self, start_node):
        return [
            base64.b64decode(node.getElementsByTagName("url")[0].firstChild.data).decode("utf-8")
            for node in start_node.getElementsByTagName("file")
        ]

    def decrypt(self):
        if not isinstance(self.data, bytes):
            raise TypeError("data must be bytes.")

        all_urls = []

        try:
            data = self.data.strip()

            data += b"=" * (-len(data) % 4)

            dlc_key = data[-88:].decode("utf-8")
            dlc_data = base64.b64decode(data[:-88])

            headers = {'User-Agent': self.shared_state.values["user_agent"]}

            dlc_content = requests.get(self.API_URL + dlc_key, headers=headers, timeout=10).content.decode("utf-8")

            rc = base64.b64decode(re.search(r"<rc>(.+)</rc>", dlc_content, re.S).group(1))[:16]

            cipher = AES.new(self.KEY, AES.MODE_CBC, self.IV)
            key = iv = cipher.decrypt(rc)

            cipher = AES.new(key, AES.MODE_CBC, iv)
            xml_data = base64.b64decode(cipher.decrypt(dlc_data)).decode("utf-8")

            root = xml.dom.minidom.parseString(xml_data).documentElement
            content_node = root.getElementsByTagName("content")[0]

            packages = self.parse_packages(content_node)

            for package in packages:
                urls = package[1]
                all_urls.extend(urls)

        except Exception as e:
            info("DLC Error: " + str(e))
            return None

        return all_urls


def get_filecrypt_links(shared_state, token, title, url, password=None):
    info("Attempting to decrypt Filecrypt link: " + url)
    session = requests.Session()

    headers = {'User-Agent': shared_state.values["user_agent"]}

    password_field = None
    if password:
        try:
            output = session.get(url, headers=headers)
            soup = BeautifulSoup(output.text, 'html.parser')
            input_element = soup.find('input', placeholder=lambda value: value and 'password' in value.lower())
            password_field = input_element['name']
            info("Password field name identified: " + password_field)
            url = output.url
        except:
            info("No password field found. Skipping password entry!")

    if password and password_field:
        info("Using Password: " + password)
        output = session.post(url, data=password_field + "=" + password,
                              headers={'User-Agent': shared_state.values["user_agent"],
                                       'Content-Type': 'application/x-www-form-urlencoded'})
    else:
        output = session.get(url, headers=headers)

    url = output.url
    soup = BeautifulSoup(output.text, 'html.parser')
    if bool(soup.find_all("input", {"id": "p4assw0rt"})):
        info(f"Password was wrong or missing. Could not get links for {title}")
        return False

    no_captcha_present = bool(soup.find("form", {"class": "cnlform"}))
    if no_captcha_present:
        info("No CAPTCHA present. Skipping token!")
    else:
        circle_captcha = bool(soup.find_all("div", {"class": "circle_captcha"}))
        i = 0
        while circle_captcha and i < 3:
            random_x = str(random.randint(100, 200))
            random_y = str(random.randint(100, 200))
            output = session.post(url, data="buttonx.x=" + random_x + "&buttonx.y=" + random_y,
                                  headers={'User-Agent': shared_state.values["user_agent"],
                                           'Content-Type': 'application/x-www-form-urlencoded'})
            url = output.url
            soup = BeautifulSoup(output.text, 'html.parser')
            circle_captcha = bool(soup.find_all("div", {"class": "circle_captcha"}))

        output = session.post(url, data="cap_token=" + token, headers={'User-Agent': shared_state.values["user_agent"],
                                                                       'Content-Type': 'application/x-www-form-urlencoded'})
    url = output.url

    if "/404.html" in url:
        info("Filecrypt returned 404 - current IP is likely banned or the link is offline.")

    soup = BeautifulSoup(output.text, 'html.parser')

    solved = bool(soup.find_all("div", {"class": "container"}))
    if not solved:
        info("Token rejected by Filecrypt! Try another CAPTCHA to proceed...")
        return False
    else:
        season_number = ""
        episode_number = ""
        episode_in_title = re.findall(r'.*\.s(\d{1,3})e(\d{1,3})\..*', title, re.IGNORECASE)
        season_in_title = re.findall(r'.*\.s(\d{1,3})\..*', title, re.IGNORECASE)
        if episode_in_title:
            try:
                season_number = str(int(episode_in_title[0][0]))
                episode_number = str(int(episode_in_title[0][1]))
            except:
                pass
        elif season_in_title:
            try:
                season_number = str(int(season_in_title[0]))
            except:
                pass

        season = ""
        episode = ""
        tv_show_selector = soup.find("div", {"class": "dlpart"})
        if tv_show_selector:

            season = "season="
            episode = "episode="

            season_selection = soup.find("div", {"id": "selbox_season"})
            try:
                if season_selection:
                    season += str(season_number)
            except:
                pass

            episode_selection = soup.find("div", {"id": "selbox_episode"})
            try:
                if episode_selection:
                    episode += str(episode_number)
            except:
                pass

        if episode_number and not episode:
            info(f"Missing select for episode number {episode_number}! Expect undesired links in the output.")

        links = []

        mirrors = []
        mirrors_available = soup.select("a[href*=mirror]")
        if mirrors_available:
            for mirror in mirrors_available:
                try:
                    mirror_query = mirror.get("href").split("?")[1]
                    base_url = url.split("?")[0] if "mirror" in url else url
                    mirrors.append(f"{base_url}?{mirror_query}")
                except IndexError:
                    continue
        else:
            mirrors = [url]

        for mirror in mirrors:
            if not len(mirrors) == 1:
                output = session.get(mirror, headers=headers)
                url = output.url
                soup = BeautifulSoup(output.text, 'html.parser')

            try:
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
                    domain = urlparse(url).netloc
                    filtered_cnl_secret = soup.find("input", {"name": "hidden_cnl_id"}).attrs["value"]
                    filtered_cnl_link = f"https://{domain}/_CNL/{filtered_cnl_secret}.html?{season}&{episode}"
                    filtered_cnl_result = session.post(filtered_cnl_link,
                                                       headers=headers)
                    if filtered_cnl_result.status_code == 200:
                        filtered_cnl_data = json.loads(filtered_cnl_result.text)
                        if filtered_cnl_data["success"]:
                            crypted_data = [
                                crypted_data[0],
                                filtered_cnl_data["data"][0],
                                filtered_cnl_data["data"][1],
                                title
                            ]
                links.extend(CNL(crypted_data).decrypt())
            except:
                info("Click'n'Load not found! Falling back to DLC...")
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

    return links
