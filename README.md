# Quasarr

<img src="https://raw.githubusercontent.com/rix1337/Quasarr/main/Quasarr.png" data-canonical-src="https://raw.githubusercontent.com/rix1337/Quasarr/main/Quasarr.png" width="64" height="64" />

Quasarr is a Bridge to use JDownloader in Radarr and Sonarr.

[![PyPI version](https://badge.fury.io/py/quasarr.svg)](https://badge.fury.io/py/quasarr)
[![Discord](https://img.shields.io/discord/1075348594225315891)](https://discord.gg/eM4zA2wWQb)
[![GitHub Sponsorship](https://img.shields.io/badge/support-me-red.svg)](https://github.com/users/rix1337/sponsorship)

Quasarr poses as a Newznab Indexer and a SABnzbd client.
It will thus never work in parallel with a real NZB indexer and download client set up.
Torrents are unaffected.

Quasarr includes a solution to quickly and easily decrypt protected links.
[Active Sponsors get access to SponsorsHelper to do so automatically.](https://github.com/users/rix1337/sponsorship)
Alternatively follow the link from the console output (or discord notification) to solve the CAPTCHA manually.
Quasarr will confidently handle the rest.

# Instructions

* Follow instructions to set up at least one hostname for Quasarr
* Provide your [MyJDownloader credentials](https://my.jdownloader.org)
* Set up Quasarr's URL as 'Newznab Indexer' and 'SABnzbd Download Client' in Sonarr/Radarr.
    * Leave settings at default
    * Use this API key: `quasarr`
* As with other download clients, you must ensure the download path used by JDownloader is accessible to *arr.

# Setup

`pip install quasarr`

* Requires Python 3.12 or later

# Run

```
quasarr
  --port=8080
  --discord=https://discord.com/api/webhooks/1234567890/ABCDEFGHIJKLMN
  --external_address=http://foo.bar/
  ```

* `--discord` must be a valid Discord Webhook URL and is optional.
* `--external_address` is used in Discord notifications and is optional.

# Docker

```
docker run -d \
  --name="Quasarr" \
  -p port:8080 \
  -v /path/to/config/:/config:rw \
  -e 'INTERNAL_ADDRESS'='http://192.168.0.1:8080' \
  -e 'EXTERNAL_ADDRESS'='http://foo.bar/' \
  -e 'DISCORD'='https://discord.com/api/webhooks/1234567890/ABCDEFGHIJKLMN' \
  rix1337/docker-quasarr:latest
  ```

* `INTERNAL_ADDRESS` is required so Radarr/Sonarr can reach Quasarr. **Must** include port!
* `EXTERNAL_ADDRESS` is optional and used in Discord notifications.
* `DISCORD` is optional and must be a valid Discord Webhook URL.
