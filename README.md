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

* Follow instructions to :
    * Set up at least one hostname for Quasarr to use
        * Chose your own or use the `HOSTNAMES` variable to provide a list of hostnames.
        * Always redact hostnames when creating issues in this repo.
        * Quasarr will become available once at least one suitable hostname is set.
    * Provide your [My-JDownloader-Credentials](https://my.jdownloader.org)
* Set up Quasarr's URL as 'Newznab Indexer' and 'SABnzbd Download Client' in Sonarr/Radarr.
    * Leave settings at default
    * Use this API key: `quasarr`
* As with other download clients, you must ensure the download path used by JDownloader is accessible to *arr.

# Docker

It is highly recommended to run the latest docker image with all optional variables set.

```
docker run -d \
  --name="Quasarr" \
  -p port:8080 \
  -v /path/to/config/:/config:rw \
  -e 'INTERNAL_ADDRESS'='http://192.168.0.1:8080' \
  -e 'EXTERNAL_ADDRESS'='https://foo.bar/' \
  -e 'DISCORD'='https://discord.com/api/webhooks/1234567890/ABCDEFGHIJKLMN' \
  -e 'HOSTNAMES'='https://pastebin.com/raw/eX4Mpl3'
  rix1337/docker-quasarr:latest
  ```

* `INTERNAL_ADDRESS` is required so Radarr/Sonarr can reach Quasarr. **Must** include port!
* `EXTERNAL_ADDRESS` is optional and used in Discord notifications.
* `DISCORD` is optional and must be a valid Discord Webhook URL.
* `HOSTNAMES` is optional and allows skipping the manual hostname step during setup.
    * Must be a publicly available `HTTP` or `HTTPs` link
    * Must be a raw `.ini` / text file (not html or json)
    * Must contain at least one valid Hostname per line `ab = xyz`

# Manual setup

Use this only in case you cant run the docker image.

`pip install quasarr`

* Requires Python 3.12 or later

```
quasarr
  --port=8080
  --discord=https://discord.com/api/webhooks/1234567890/ABCDEFGHIJKLMN
  --external_address=https://foo.bar/
  --hostnames=https://pastebin.com/raw/eX4Mpl3
  ```

* `--discord` see `DISCORD`docker variable
* `--external_address` see `EXTERNAL_ADDRESS`docker variable
* `--hostnames` see `HOSTNAMES`docker variable
