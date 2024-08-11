# Quasarr

[![PyPI version](https://badge.fury.io/py/quasarr.svg)](https://badge.fury.io/py/quasarr)
[![GitHub Sponsorship](https://img.shields.io/badge/support-me-red.svg)](https://github.com/users/rix1337/sponsorship)

JDownloader Bridge for Radarr and (later also) Sonarr.

* Follow instructions to set up at least one hostname
* Provide your [My JDownloader credentials](https://my.jdownloader.org)
* Then use Quasarr's URL as 'Newznab Indexer' and 'SABnzbd Download Client' in Sonarr/Radarr.
    * Leave settings at default
    * Use this API key: `quasarr`

**Warning: this is a very early dev version. Only tested with Radarr. Only one hostname supported.**

# Setup

`pip install quasarr`
* Requires Python 3.12

# Run

```
quasarr
  --port=8080
  --external_address=https://quasarr.example.org:9443
  ```

* External Address: required, if you want to fully use Quasarr from outside your local network

# Docker

```
docker run -d \
  --name="Quasarr" \
  -p port:8080 \
  -v /path/to/config/:/config:rw \
  -e 'INTERNAL_ADDRESS'='http://quasarr:8080' \
  -e 'EXTERNAL_ADDRESS'='https://quasarr.example.org:9443' \
  rix1337/docker-quasarr:latest
  ```

* Internal Address: required so Radarr/Sonarr can reach Quasarr
* External Address: required, if you want to fully use Quasarr from outside your local network
