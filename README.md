# Quasarr

[![PyPI version](https://badge.fury.io/py/quasarr.svg)](https://badge.fury.io/py/quasarr)
[![GitHub Sponsorship](https://img.shields.io/badge/support-me-red.svg)](https://github.com/users/rix1337/sponsorship)

JDownloader Bridge for Radarr and (later also) Sonarr.
Quasarr poses as Newznab Indexer and SABnzbd Download Client.
Thus it will not work in parallel with a real indexer/download client set up.
Torrents will remain unaffected.

* Follow instructions to set up at least one hostname for Quasarr
* Provide your [MyJDownloader credentials](https://my.jdownloader.org)
* Set up Quasarr's URL as 'Newznab Indexer' and 'SABnzbd Download Client' in Sonarr/Radarr.
    * Leave settings at default
    * Use this API key: `quasarr`

**Warning: this is a very early proof-of-concept.
It is only tested with Radarr and only one hostname at the moment.**

Everything should work in Radarr, except:

- Deleting downloads

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
