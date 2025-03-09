# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import datetime
import re
import time
from base64 import urlsafe_b64encode

import requests
from bs4 import BeautifulSoup

from quasarr.providers.log import info, debug

hostname = "dw"
supported_mirrors = ["1fichier", "rapidgator", "ddownload", "katfile"]


def convert_to_rss_date(date_str):
    german_months = ["Januar", "Februar", "März", "April", "Mai", "Juni",
                     "Juli", "August", "September", "Oktober", "November", "Dezember"]
    english_months = ["January", "February", "March", "April", "May", "June",
                      "July", "August", "September", "October", "November", "December"]

    for german, english in zip(german_months, english_months):
        if german in date_str:
            date_str = date_str.replace(german, english)
            break

    parsed_date = datetime.datetime.strptime(date_str, '%d. %B %Y / %H:%M')
    rss_date = parsed_date.strftime('%a, %d %b %Y %H:%M:%S %z')

    return rss_date


def extract_size(text):
    match = re.match(r"(\d+) ([A-Za-z]+)", text)
    if match:
        size = match.group(1)
        unit = match.group(2)
        return {"size": size, "sizeunit": unit}
    else:
        raise ValueError(f"Invalid size format: {text}")


def dw_get_download_links(shared_state, content, title):
    try:
        try:
            content = BeautifulSoup(content, "html.parser")
        except:
            content = BeautifulSoup(str(content), "html.parser")
        download_buttons = content.find_all("button", {"class": "show_link"})
    except:
        info(f"{hostname.upper()} has changed the details page. Parsing links for {title} failed!")
        return False

    dw = shared_state.values["config"]("Hostnames").get(hostname.lower())
    ajax_url = "https://" + dw + "/wp-admin/admin-ajax.php"

    download_links = []
    try:
        for button in download_buttons:
            payload = "action=show_link&link_id=" + button["value"]

            headers = {
                'User-Agent': shared_state.values["user_agent"],
            }

            response = requests.post(ajax_url, payload, headers=headers, timeout=10).json()
            if response["success"]:
                link = response["data"].split(",")[0]

                if dw in link:
                    match = re.search(r'https://' + dw + r'/azn/af\.php\?v=([A-Z0-9]+)(#.*)?', link)
                    if match:
                        link = (f'https://filecrypt.cc/Container/{match.group(1)}'
                                f'.html{match.group(2) if match.group(2) else ""}')

                mirror = button.nextSibling.img["src"].split("/")[-1].replace(".png", "")
                download_links.append([link, mirror])
    except:
        info(f"{hostname.upper()} has changed the site structure. Parsing links for {title} failed!")
        pass

    return download_links


def dw_feed(shared_state, start_time, request_from, mirror=None):
    releases = []
    dw = shared_state.values["config"]("Hostnames").get(hostname.lower())
    password = dw

    if "Radarr" in request_from:
        feed_type = "videos/filme/"
    else:
        feed_type = "videos/serien/"

    if mirror and mirror not in supported_mirrors:
        debug(f'Mirror "{mirror}" not supported by "{hostname.upper()}". Supported mirrors: {supported_mirrors}.'
              ' Skipping search!')
        return releases

    url = f'https://{dw}/{feed_type}'
    headers = {
        'User-Agent': shared_state.values["user_agent"],
    }

    try:
        request = requests.get(url, headers=headers, timeout=10).content
        feed = BeautifulSoup(request, "html.parser")
        articles = feed.find_all('h4')

        for article in articles:
            try:
                source = article.a["href"]
                title = article.a.text.strip()

                try:
                    imdb_id = re.search(r'tt\d+', str(article)).group()
                except:
                    imdb_id = None

                size_info = article.find("span").text.strip()
                size_item = extract_size(size_info)
                mb = shared_state.convert_to_mb(size_item)
                size = mb * 1024 * 1024
                date = article.parent.parent.find("span", {"class": "date updated"}).text.strip()
                published = convert_to_rss_date(date)
                payload = urlsafe_b64encode(
                    f"{title}|{source}|{mirror}|{mb}|{password}|{imdb_id}".encode("utf-8")).decode("utf-8")
                link = f"{shared_state.values['internal_address']}/download/?payload={payload}"
            except Exception as e:
                info(f"Error parsing {hostname.upper()} feed: {e}")
                continue

            releases.append({
                "details": {
                    "title": title,
                    "hostname": hostname.lower(),
                    "imdb_id": imdb_id,
                    "link": link,
                    "mirror": mirror,
                    "size": size,
                    "date": published,
                    "source": source
                },
                "type": "protected"
            })

    except Exception as e:
        info(f"Error loading {hostname.upper()} feed: {e}")

    elapsed_time = time.time() - start_time
    debug(f"Time taken: {elapsed_time:.2f} seconds ({hostname.lower()})")

    return releases


def dw_search(shared_state, start_time, request_from, search_string, mirror=None):
    releases = []
    dw = shared_state.values["config"]("Hostnames").get(hostname.lower())
    password = dw

    if "Radarr" in request_from:
        search_type = "videocategory=filme"
    else:
        search_type = "videocategory=serien"

    if mirror and mirror not in ["1fichier", "rapidgator", "ddownload", "katfile"]:
        debug(f'Mirror "{mirror}" not not supported by {hostname.upper()}. Skipping search!')
        return releases

    url = f'https://{dw}/?s={search_string}&{search_type}'
    headers = {
        'User-Agent': shared_state.values["user_agent"],
    }

    try:
        request = requests.get(url, headers=headers, timeout=10).content
        search = BeautifulSoup(request, "html.parser")
        results = search.find_all('h4')

    except Exception as e:
        info(f"Error loading {hostname.upper()} search feed: {e}")
        return releases

    imdb_id = shared_state.is_imdb_id(search_string)

    if results:
        for result in results:
            try:
                title = result.a.text.strip()

                if not imdb_id and not shared_state.search_string_in_sanitized_title(search_string, title):
                    continue

                if not imdb_id:
                    try:
                        imdb_id = re.search(r'tt\d+', str(result)).group()
                    except:
                        imdb_id = None

                source = result.a["href"]
                size_info = result.find("span").text.strip()
                size_item = extract_size(size_info)
                mb = shared_state.convert_to_mb(size_item)
                size = mb * 1024 * 1024
                date = result.parent.parent.find("span", {"class": "date updated"}).text.strip()
                published = convert_to_rss_date(date)
                payload = urlsafe_b64encode(
                    f"{title}|{source}|{mirror}|{mb}|{password}|{imdb_id}".encode("utf-8")).decode("utf-8")
                link = f"{shared_state.values['internal_address']}/download/?payload={payload}"
            except Exception as e:
                info(f"Error parsing {hostname.upper()} search: {e}")
                continue

            releases.append({
                "details": {
                    "title": title,
                    "hostname": hostname.lower(),
                    "imdb_id": imdb_id,
                    "link": link,
                    "mirror": mirror,
                    "size": size,
                    "date": published,
                    "source": source
                },
                "type": "protected"
            })

    elapsed_time = time.time() - start_time
    debug(f"Time taken: {elapsed_time:.2f} seconds ({hostname.lower()})")

    return releases
