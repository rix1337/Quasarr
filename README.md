# Quasarr

[![PyPI version](https://badge.fury.io/py/quasarr.svg)](https://badge.fury.io/py/quasarr)
[![GitHub Sponsorship](https://img.shields.io/badge/support-me-red.svg)](https://github.com/users/rix1337/sponsorship)

Quasarr is a Bridge to use JDownloader in Radarr and (later also) Sonarr.

Quasarr includes a solution to quickly and easily decrypt protected links.
Just follow the link from the console output and solve the CAPTCHA.
Quasarr will confidently handle the rest.

Quasarr poses as a Newznab Indexer and a SABnzbd client.
It will thus never work in parallel with a real NZB indexer and download client set up.
Torrents are unaffected.

* Follow instructions to set up at least one hostname for Quasarr
* Provide your [MyJDownloader credentials](https://my.jdownloader.org)
* Set up Quasarr's URL as 'Newznab Indexer' and 'SABnzbd Download Client' in Sonarr/Radarr.
    * Leave settings at default
    * Use this API key: `quasarr`
* As with other download clients, you must ensure the download path used by JDownloader is accessible to *arr.

**Warning: this project is still in the proof-of-concept stage.
It is only tested with Radarr and only two hostname are currently supported.**

# Setup

`pip install quasarr`

* Requires Python 3.12 or later

# Run

```
quasarr
  --port=8080
  ```

# Docker

```
docker run -d \
  --name="Quasarr" \
  -p port:8080 \
  -v /path/to/config/:/config:rw \
  -e 'INTERNAL_ADDRESS'='http://192.168.0.1:8080' \
  rix1337/docker-quasarr:latest
  ```

* Internal Address: required so Radarr/Sonarr can reach Quasarr. **Must** include port!
