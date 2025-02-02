# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import re
import time
from base64 import urlsafe_b64encode

import requests
from bs4 import BeautifulSoup

from quasarr.providers.log import info, debug


def extract_size(text):
    match = re.match(r"(\d+)\s*([A-Za-z]+)", text)
    if match:
        size = match.group(1)
        unit = match.group(2)
        return {"size": size, "sizeunit": unit}
    else:
        raise ValueError(f"Invalid size format: {text}")


def fx_feed(shared_state, start_time):
    releases = []

    fx = shared_state.values["config"]("Hostnames").get("fx")

    password = fx.split(".")[0]
    url = f'https://{fx}/'
    headers = {
        'User-Agent': shared_state.values["user_agent"],
    }

    try:
        request = requests.get(url, headers=headers, timeout=10).content
        feed = BeautifulSoup(request, "html.parser")
        items = feed.find_all("article")
    except Exception as e:
        info(f"Error loading FX feed: {e}")
        return releases

    if items:
        for item in items:
            try:
                article = BeautifulSoup(str(item), "html.parser")
                try:
                    source = article.find('h2', class_='entry-title').a["href"]
                    titles = article.find_all("a", href=re.compile("(filecrypt|safe." + fx + ")"))
                except:
                    continue
                i = 0
                for title in titles:
                    link = title["href"]
                    title = (title.text.encode("ascii", errors="ignore").decode().
                             replace("/", "").replace(" ", ".").strip())

                    try:
                        imdb_link = article.find("a", href=re.compile(r"imdb\.com"))
                        imdb_id = re.search(r'tt\d+', str(imdb_link)).group()
                    except:
                        imdb_id = None

                    try:
                        size_info = article.find_all("strong", text=re.compile(r"(size|größe)", re.IGNORECASE))[
                            i].next.next.text.replace("|", "").strip()
                        size_item = extract_size(size_info)
                        mb = shared_state.convert_to_mb(size_item)
                        size = mb * 1024 * 1024
                        payload = urlsafe_b64encode(f"{title}|{link}|{mb}|{password}|{imdb_id}".encode("utf-8")).decode(
                            "utf-8")
                        link = f"{shared_state.values['internal_address']}/download/?payload={payload}"
                    except:
                        continue

                    try:
                        dates = article.find_all("time")
                        for date in dates:
                            published = date["datetime"]
                    except:
                        continue

                    releases.append({
                        "details": {
                            "title": f"[FX] {title}",
                            "imdb_id": imdb_id,
                            "link": link,
                            "size": size,
                            "date": published,
                            "source": source
                        },
                        "type": "protected"
                    })

            except Exception as e:
                info(f"Error parsing FX feed: {e}")

    elapsed_time = time.time() - start_time
    debug(f"Time taken: {elapsed_time:.2f} seconds (fx)")

    return releases


def fx_search(shared_state, start_time, search_string):
    releases = []

    fx = shared_state.values["config"]("Hostnames").get("fx")

    password = fx.split(".")[0]
    url = f'https://{fx}/?s={search_string}'
    headers = {
        'User-Agent': shared_state.values["user_agent"],
    }

    try:
        request = requests.get(url, headers=headers, timeout=10).content
        search = BeautifulSoup(request, "html.parser")
        results = search.find('h2', class_='entry-title')

    except Exception as e:
        info(f"Error loading FX feed: {e}")
        return releases

    imdb_id = shared_state.is_imdb_id(search_string)

    if results:
        for result in results:
            try:
                result_source = result["href"]
                request = requests.get(result_source, headers=headers, timeout=10).content
                feed = BeautifulSoup(request, "html.parser")
                items = feed.find_all("article")
            except Exception as e:
                info(f"Error loading FX feed: {e}")
                return releases

            for item in items:
                try:
                    article = BeautifulSoup(str(item), "html.parser")
                    try:
                        titles = article.find_all("a", href=re.compile(r"filecrypt\."))
                    except:
                        continue
                    i = 0
                    for title in titles:
                        link = title["href"]
                        title = (title.text.encode("ascii", errors="ignore").decode().
                                 replace("/", "").replace(" ", ".").strip())

                        if not imdb_id and not shared_state.search_string_in_sanitized_title(search_string, title):
                            continue

                        if not imdb_id:
                            try:
                                imdb_link = article.find("a", href=re.compile(r"imdb\.com"))
                                imdb_id = re.search(r'tt\d+', str(imdb_link)).group()
                            except:
                                imdb_id = None

                        try:
                            size_info = article.find_all("strong", text=re.compile(r"(size|größe)", re.IGNORECASE))[
                                i].next.next.text.replace("|", "").strip()
                            size_item = extract_size(size_info)
                            mb = shared_state.convert_to_mb(size_item)
                            size = mb * 1024 * 1024
                            payload = urlsafe_b64encode(
                                f"{title}|{link}|{mb}|{password}|{imdb_id}".encode("utf-8")).decode("utf-8")
                            link = f"{shared_state.values['internal_address']}/download/?payload={payload}"
                        except:
                            continue

                        try:
                            dates = article.find_all("time")
                            for date in dates:
                                published = date["datetime"]
                        except:
                            continue

                        releases.append({
                            "details": {
                                "title": f"[FX] {title}",
                                "imdb_id": imdb_id,
                                "link": link,
                                "size": size,
                                "date": published,
                                "source": result_source
                            },
                            "type": "protected"
                        })

                except Exception as e:
                    info(f"Error parsing FX search: {e}")

    elapsed_time = time.time() - start_time
    debug(f"Time taken: {elapsed_time:.2f} seconds (fx)")

    return releases
