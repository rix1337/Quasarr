# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import re
from base64 import urlsafe_b64encode

import requests
from bs4 import BeautifulSoup


def extract_size(text):
    match = re.match(r"(\d+)\s*([A-Za-z]+)", text)
    if match:
        size = match.group(1)
        unit = match.group(2)
        return {"size": size, "sizeunit": unit}
    else:
        raise ValueError(f"Invalid size format: {text}")


def fx_feed(shared_state):
    releases = []

    fx = shared_state.values["config"]("Hostnames").get("fx")

    password = fx.split(".")[0]
    url = f'https://{fx}/'
    headers = {
        'User-Agent': shared_state.values["user_agent"],
    }

    try:
        request = requests.get(url, headers=headers).content
        feed = BeautifulSoup(request, "html.parser")
        items = feed.findAll("article")
    except Exception as e:
        print(f"Error loading FX feed: {e}")
        return releases

    if items:
        for item in items:
            try:
                article = BeautifulSoup(str(item), "html.parser")
                try:
                    source = article.find('h2', class_='entry-title').a["href"]
                    titles = article.findAll("a", href=re.compile("(filecrypt|safe." + fx + ")"))
                except:
                    continue
                i = 0
                for title in titles:
                    link = title["href"]
                    title = (title.text.encode("ascii", errors="ignore").decode().
                             replace("/", "").replace(" ", ".").strip())

                    try:
                        size_info = article.findAll("strong", text=re.compile(r"(size|größe)", re.IGNORECASE))[
                            i].next.next.text.replace("|", "").strip()
                        size_item = extract_size(size_info)
                        mb = shared_state.convert_to_mb(size_item)
                        size = mb * 1024 * 1024
                        payload = urlsafe_b64encode(f"{title}|{link}|{mb}|{password}".encode("utf-8")).decode("utf-8")
                        link = f"{shared_state.values['internal_address']}/download/?payload={payload}"
                    except:
                        continue

                    try:
                        dates = article.findAll("time")
                        for date in dates:
                            published = date["datetime"]
                    except:
                        continue

                    releases.append({
                        "details": {
                            "title": f"[FX] {title}",
                            "link": link,
                            "size": size,
                            "date": published,
                            "source": source
                        },
                        "type": "protected"
                    })

            except Exception as e:
                print(f"Error parsing FX feed: {e}")

    return releases


def fx_search(shared_state, search_string):
    releases = []

    fx = shared_state.values["config"]("Hostnames").get("fx")

    password = fx.split(".")[0]
    url = f'https://{fx}/?s={search_string}'
    headers = {
        'User-Agent': shared_state.values["user_agent"],
    }

    try:
        request = requests.get(url, headers=headers).content
        search = BeautifulSoup(request, "html.parser")
        results = search.find('h2', class_='entry-title')

    except Exception as e:
        print(f"Error loading FX feed: {e}")
        return releases

    if results:
        for result in results:
            result_source = result["href"]
            try:
                request = requests.get(result_source, headers=headers).content
                feed = BeautifulSoup(request, "html.parser")
                items = feed.findAll("article")
            except Exception as e:
                print(f"Error loading FX feed: {e}")
                return releases

            for item in items:
                try:
                    article = BeautifulSoup(str(item), "html.parser")
                    try:
                        titles = article.findAll("a", href=re.compile("(filecrypt|safe." + fx + ")"))
                    except:
                        continue
                    i = 0
                    for title in titles:
                        link = title["href"]
                        title = (title.text.encode("ascii", errors="ignore").decode().
                                 replace("/", "").replace(" ", ".").strip())
                        try:
                            size_info = article.findAll("strong", text=re.compile(r"(size|größe)", re.IGNORECASE))[
                                i].next.next.text.replace("|", "").strip()
                            size_item = extract_size(size_info)
                            mb = shared_state.convert_to_mb(size_item)
                            size = mb * 1024 * 1024
                            payload = urlsafe_b64encode(f"{title}|{link}|{mb}|{password}".encode("utf-8")).decode(
                                "utf-8")
                            link = f"{shared_state.values['internal_address']}/download/?payload={payload}"
                        except:
                            continue

                        try:
                            dates = article.findAll("time")
                            for date in dates:
                                published = date["datetime"]
                        except:
                            continue

                        releases.append({
                            "details": {
                                "title": f"[FX] {title}",
                                "link": link,
                                "size": size,
                                "date": published,
                                "source": result_source
                            },
                            "type": "protected"
                        })

                except Exception as e:
                    print(f"Error parsing FX search: {e}")

    return releases
