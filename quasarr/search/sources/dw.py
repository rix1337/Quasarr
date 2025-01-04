# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import datetime
import re
from base64 import urlsafe_b64encode

import requests
from bs4 import BeautifulSoup


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
        download_buttons = content.findAll("button", {"class": "show_link"})
    except:
        print("DW hat die Detail-Seite angepasst. Parsen von Download-Links für " + title + " nicht möglich!")
        return False

    dw = shared_state.values["config"]("Hostnames").get("dw")
    ajax_url = "https://" + dw + "/wp-admin/admin-ajax.php"

    download_links = []
    try:
        for button in download_buttons:
            payload = "action=show_link&link_id=" + button["value"]

            headers = {
                'User-Agent': shared_state.values["user_agent"],
            }

            response = requests.post(ajax_url, payload, headers=headers).json()
            if response["success"]:
                link = response["data"].split(",")[0]

                if dw in link:
                    match = re.search(r'https://' + dw + r'/azn/af\.php\?v=([A-Z0-9]+)(#.*)?', link)
                    if match:
                        link = (f'https://filecrypt.cc/Container/{match.group(1)}'
                                f'.html{match.group(2) if match.group(2) else ""}')

                hoster = button.nextSibling.img["src"].split("/")[-1].replace(".png", "")
                download_links.append([link, hoster])
    except:
        print("DW site has been updated. Parsing download links not possible!")
        pass

    return download_links


def dw_feed(shared_state, request_from):
    releases = []
    dw = shared_state.values["config"]("Hostnames").get("dw")
    password = dw

    if "Radarr" in request_from:
        feed_type = "videos/filme/"
    else:
        feed_type = "videos/serien/"

    url = f'https://{dw}/{feed_type}'
    headers = {
        'User-Agent': shared_state.values["user_agent"],
    }

    try:
        request = requests.get(url, headers=headers).content
        feed = BeautifulSoup(request, "html.parser")
        articles = feed.findAll('h4')

        for article in articles:
            try:
                source = article.a["href"]
                title = article.a.text.strip()
                size_info = article.find("span").text.strip()
                size_item = extract_size(size_info)
                mb = shared_state.convert_to_mb(size_item) * 1024 * 1024
                date = article.parent.parent.find("span", {"class": "date updated"}).text.strip()
                published = convert_to_rss_date(date)
                payload = urlsafe_b64encode(f"{title}|{source}|{mb}|{password}".encode("utf-8")).decode(
                    "utf-8")
                link = f"{shared_state.values['internal_address']}/download/?payload={payload}"
            except Exception as e:
                print(f"Error parsing DW feed: {e}")
                continue

            releases.append({
                "details": {
                    "title": f"[DW] {title}",
                    "link": link,
                    "size": mb,
                    "date": published,
                    "source": source
                },
                "type": "protected"
            })

    except Exception as e:
        print(f"Error loading DW feed: {e}")

    return releases


def dw_search(shared_state, request_from, search_string):
    releases = []
    dw = shared_state.values["config"]("Hostnames").get("dw")
    password = dw

    if "Radarr" in request_from:
        search_type = "videocategory=filme"
    else:
        search_type = "videocategory=serien"

    url = f'https://{dw}/?s={search_string}&{search_type}'
    headers = {
        'User-Agent': shared_state.values["user_agent"],
    }

    try:
        request = requests.get(url, headers=headers).content
        search = BeautifulSoup(request, "html.parser")
        results = search.findAll('h4')

    except Exception as e:
        print(f"Error loading DW search feed: {e}")
        return releases

    if results:
        for result in results:
            try:
                source = result.a["href"]
                title = result.a.text.strip()
                size_info = result.find("span").text.strip()
                size_item = extract_size(size_info)
                mb = shared_state.convert_to_mb(size_item) * 1024 * 1024
                date = result.parent.parent.find("span", {"class": "date updated"}).text.strip()
                published = convert_to_rss_date(date)
                payload = urlsafe_b64encode(f"{title}|{source}|{mb}|{password}".encode("utf-8")).decode(
                    "utf-8")
                link = f"{shared_state.values['internal_address']}/download/?payload={payload}"
            except Exception as e:
                print(f"Error parsing DW search: {e}")
                continue

            releases.append({
                "details": {
                    "title": f"[DW] {title}",
                    "link": link,
                    "size": mb,
                    "date": published,
                    "source": source
                },
                "type": "protected"
            })

    return releases
