#  

<img src="https://raw.githubusercontent.com/rix1337/Quasarr/main/Quasarr.png" data-canonical-src="https://raw.githubusercontent.com/rix1337/Quasarr/main/Quasarr.png" width="64" height="64" />

Quasarr connects JDownloader with Radarr and Sonarr. It also decrypts links protected by CAPTCHAs.

[![PyPI version](https://badge.fury.io/py/quasarr.svg)](https://badge.fury.io/py/quasarr)
[![Discord](https://img.shields.io/discord/1075348594225315891)](https://discord.gg/eM4zA2wWQb)
[![GitHub Sponsorship](https://img.shields.io/badge/support-me-red.svg)](https://github.com/users/rix1337/sponsorship)

Quasarr poses as a Newznab Indexer and a SABnzbd client.
It will thus never work in parallel with a real NZB indexer and download client set up.
Torrents are unaffected. To still use NZB indexers, you must set fixed download clients in the advanced indexer
settings for Radarr/Sonarr.

Quasarr includes a solution to quickly and easily decrypt protected links.
[Active Sponsors get access to SponsorsHelper to do so automatically.](https://github.com/users/rix1337/sponsorship)
Alternatively follow the link from the console output (or discord notification) to solve the CAPTCHA manually.
Quasarr will confidently handle the rest.

# Instructions

* Set up at least one hostname for Quasarr to use
    * Chose your own or use the `HOSTNAMES` variable to provide a list of hostnames.
    * This project will not condone nor provide you with hostnames. Search Google, Pastebin, etc. for suggestions.
    * Always redact hostnames when creating issues in this repo.
    * Quasarr will become available once at least one suitable hostname is set.
* Provide your [My-JDownloader-Credentials](https://my.jdownloader.org)
    * Consider setting up a fresh JDownloader before you begin.
    * Quasarr will modify settings of JDownloader so downloads can be properly handled by Radarr/Sonarr.
    * If using docker make extra sure that JDownloader's download path is available to Radarr/Sonarr with the exakt same
      internal and external path mapping. Just matching the external path is not enough.
* Set up Quasarr as `Newznab Indexer` and `SABnzbd Download Client` in Radarr/Sonarr
    * Use the API key from console output (or copy it from the Quasarr web UI)
    * Leave all other settings at default.
    * If you prefer to only get releases for a specific mirror, add the mirror name to the
      API path in the advanced indexer settings.
      * Example: `/api/dropbox/` results will only return releases where `dropbox` is explicitly mentioned in link.
      * This means that if a mirror is not available at a hostname, the release will be ignored.
* To see download status information
    * Open `Activity` → `Queue` → `Options` in Radarr/Sonarr
    * Enable `Release Title`

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
  ghcr.io/rix1337/quasarr:latest
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

`pip install `

* Requires Python 3.12 or later

```
  --port=8080
  --discord=https://discord.com/api/webhooks/1234567890/ABCDEFGHIJKLMN
  --external_address=https://foo.bar/
  --hostnames=https://pastebin.com/raw/eX4Mpl3
  ```

* `--discord` see `DISCORD`docker variable
* `--external_address` see `EXTERNAL_ADDRESS`docker variable
* `--hostnames` see `HOSTNAMES`docker variable

# Philosophy

Complexity is the killer of solo projects like this one. It must be fought at all cost!

Therefore, feature toggles to modify Quasarr's behavior will never be introduced to this project.

Consider that every choice for the user must be reflected throughout the project.
Every feature toggle therefore is a negative multiplier for future development efforts.
This project's predecessor [FeedCrawler](https://github.com/rix1337/FeedCrawler) died because it allowed an insane
amount of flexibility.

I will not waste my precious time on features that will slow future development cycles down.
Issues, feature and pull requests that are meant to introduce feature toggles will therefore be rejected.

## Intentional design decisions
* There is no settings UI after the initial setup.
  If you need to update hostnames or My-JDownloader-Credentials, simply delete the `Quasarr.ini` and restart Quasarr.
* Radarr and Sonarr provide custom formats to automatically choose the most fitting release for a given search
  based on the release's title. Quasarr prefixes release titles with the source hostname in square brackets in case you
  want to apply custom format scores to certain hostnames.

# Roadmap

- Assume there are zero known
  issues [unless you find one or more open issues in this repository](https://github.com/rix1337/Quasarr/issues).
- Still having an issue? Provide a detailed report [here](https://github.com/rix1337/Quasarr/issues/new/choose)!
- The feature set is considered complete. Most feature requests can be satisfied by:
    - Existing settings in Radarr/Sonarr
    - Existing settings in JDownloader
    - Existing tools from the *arr ecosystem that integrate directly with Radarr/Sonarr
- There are no hostname integrations in active development.
- Adding one or more hostnames focused on English content is highly desired.
  - Please provide suggestions in a private thread on Discord.
- Pull requests are welcome. Especially for popular hostnames.
    - Always reach out on Discord before starting work on a new feature.
    - Please follow the existing code style and project structure.
    - Anti-bot measures must be circumvented without relying on third party tools like Flaresolverr.
    - Please provide proof of functionality (screenshots/examples) when submitting your pull request.

## Development Setup for Pull Requests

To test your changes before submitting a pull request:

### 1. Run Quasarr with the `--internal_address` parameter

```bash
python Quasarr.py --internal_address=http://<host-ip>:<port>
```

Replace `<host-ip>` and `<port>` with the scheme, IP, and port of your host machine.
The `--internal_address` parameter is **mandatory**.

### 2. Start the required services using the `dev-services-compose.yml` file

```bash
CONFIG_VOLUMES=/path/to/config docker-compose -f docker/dev-services-compose.yml up
```

Replace `/path/to/config` with your desired configuration location. The `CONFIG_VOLUMES` environment variable is **mandatory**.
