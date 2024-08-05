#  Quasarr

[![PyPI version](https://badge.fury.io/py/quasarr.svg)](https://badge.fury.io/py/quasarr)
[![GitHub Sponsorship](https://img.shields.io/badge/support-me-red.svg)](https://github.com/users/rix1337/sponsorship)

JDownloader Bridge for Radarr and Sonarr

# Setup

`pip install quasarr`

# Run

```
quasarr
  --port=8080
  --config=/tmp/config
  --example=test
  ```

# Docker
```
docker run -d \
  --name="Quasarr" \
  -p port:8080 \
  -v /path/to/config/:/config:rw \
  -e 'EXAMPLE'='test'
  rix1337/docker-quasarr:latest
  ```
