#

<img src="https://raw.githubusercontent.com/rix1337/Quasarr/main/Quasarr.png" data-canonical-src="https://raw.githubusercontent.com/rix1337/Quasarr/main/Quasarr.png" width="64" height="64" />

Quasarr connects JDownloader with Radarr, Sonarr and LazyLibrarian. It also decrypts links protected by CAPTCHAs.

[![PyPI version](https://badge.fury.io/py/quasarr.svg)](https://badge.fury.io/py/quasarr)
[![Discord](https://img.shields.io/discord/1075348594225315891)](https://discord.gg/eM4zA2wWQb)
[![GitHub Sponsorship](https://img.shields.io/badge/support-me-red.svg)](https://github.com/users/rix1337/sponsorship)

Quasarr pretends to be both `Newznab Indexer` and `SABnzbd client`. Therefore, do not try to use it with real usenet
indexers. It simply does not know what NZB files are.

Quasarr includes a solution to quickly and easily decrypt protected links.
[Active monthly Sponsors get access to SponsorsHelper to do so automatically.](https://github.com/rix1337/Quasarr?tab=readme-ov-file#sponsorshelper)
Alternatively, follow the link from the console output (or discord notification) to solve CAPTCHAs manually.
Quasarr will confidently handle the rest. Some CAPTCHA types require [Tampermonkey](https://www.tampermonkey.net/) to be
installed in your browser.

# Instructions

1. Set up and run [JDownloader 2](https://jdownloader.org/download/index)
2. Configure the integrations below
3. (Optional) Set up [FlareSolverr 3](https://github.com/FlareSolverr/FlareSolverr) for sites that require it

> **Finding your Quasarr URL and API Key**  
> Both values are shown in the console output under **API Information**, or in the Quasarr web UI.

---

## FlareSolverr (Optional)

FlareSolverr is **optional** but **required for some sites** (e.g., AL) that use Cloudflare protection. You can skip
FlareSolverr during setup and configure it later via the web UI.

If using FlareSolverr, provide your URL including the version path:

```
http://192.168.1.1:8191/v1
```

> **Note:** Sites requiring FlareSolverr will show a warning in the console when it's not configured.

---

## Quasarr

> ⚠️ Quasarr requires at least one valid hostname to start. It does not provide or endorse any specific sources, but
> community-maintained lists are available:

🔗 **[https://quasarr-host.name](https://quasarr-host.name)** — community guide for finding hostnames

📋 Alternatively, browse community suggestions via [pastebin search](https://pastebin.com/search?q=hostnames+quasarr) (
login required).

> Authentication is optional but strongly recommended.
>
> - 🔐 Set `USER` and `PASS` to enable form-based login (30-day session)
> - 🔑 Set `AUTH=basic` to use HTTP Basic Authentication instead

---

## JDownloader

> ⚠️ If using Docker:
> JDownloader's download path must be available to Radarr/Sonarr/LazyLibrarian with **identical internal and external
path mappings**!
> Matching only the external path is not sufficient.

1. Start and connect JDownloader to [My JDownloader](https://my.jdownloader.org)
2. Provide your My JDownloader credentials during Quasarr setup

<details>
<summary>Fresh install recommended</summary>

Consider setting up a fresh JDownloader instance. Quasarr will modify JDownloader's settings to enable
Radarr/Sonarr/LazyLibrarian integration.

</details>

---

## Radarr / Sonarr

> ⚠️ **Sonarr users:** Set all shows (including anime) to the **Standard** series type. Quasarr cannot find releases for
> shows set to Anime/Absolute.


Add Quasarr as both a **Newznab Indexer** and **SABnzbd Download Client** using your Quasarr URL and API Key.

<details>
<summary>Show download status in Radarr/Sonarr</summary>

**Activity → Queue → Options** → Enable `Release Title`

</details>

<details>
<summary>Restrict results to a specific mirror</summary>

1. In the Newznab Settings for Quasarr, enable advanced settings.
2. Append the desired mirror name to the `API Path` field.

```
/api/dropbox/
```

Using the `URL` field will not work!

Only releases with `dropbox` in a link will be returned. If the mirror isn't available, the release will fail.

</details>

---

## LazyLibrarian

> ⚠️ **Experimental feature** — Report issues when a hostname returns results on its website but not in LazyLibrarian.

<details>
<summary>Setup instructions</summary>

### SABnzbd+ Downloader

| Setting  | Value                      |
|----------|----------------------------|
| URL/Port | Your Quasarr host and port |
| API Key  | Your Quasarr API Key       |
| Category | `docs`                     |

### Newznab Provider

| Setting | Value                |
|---------|----------------------|
| URL     | Your Quasarr URL     |
| API     | Your Quasarr API Key |

### Fix Import & Processing

**Importing:**

- Enable `OpenLibrary api for book/author information`
- Set Primary Information Source to `OpenLibrary`
- Add to Import languages: `, Unknown` (German users: `, de, ger, de-DE`)

**Processing → Folders:**

- Add your Quasarr download path (typically `/downloads/Quasarr/`)

</details>

---

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
  -e 'HOSTNAMES'='https://quasarr-host.name/ini?token=123...' \
  -e 'USER'='admin' \
  -e 'PASS'='change-me' \
  -e 'AUTH'='form' \
  -e 'SILENT'='True' \
  -e 'DEBUG'='' \
  -e 'TZ'='Europe/Berlin' \
  ghcr.io/rix1337/quasarr:latest
  ```

| Parameter          | Description                                                                                                                                                                                                                                 |
|--------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `INTERNAL_ADDRESS` | **Required.** Internal URL so Radarr/Sonarr/LazyLibrarian can reach Quasarr. **Must include port.**                                                                                                                                         |
| `EXTERNAL_ADDRESS` | Optional. External URL (e.g. reverse proxy). Always protect external access with authentication.                                                                                                                                            |
| `DISCORD`          | Optional. Discord webhook URL for notifications.                                                                                                                                                                                            |
| `HOSTNAMES`        | Optional. URL to a hostname list to skip manual setup. Must be a publicly accessible `HTTP`/`HTTPS` link, point to a raw `.ini` or plain text file (not HTML or JSON), and contain at least one hostname per line in the format `ab = xyz`. |
| `USER`             | Username to protect the web UI.                                                                                                                                                                                                             |
| `PASS`             | Password to protect the web UI.                                                                                                                                                                                                             |
| `AUTH`             | Authentication mode. Supported values: `form` or `basic`.                                                                                                                                                                                   |
| `SILENT`           | Optional. If `True`, silences all Discord notifications except SponsorHelper error messages.                                                                                                                                                |
| `DEBUG`            | Optional. If `True`, enables debug logging.                                                                                                                                                                                                 |
| `TZ`               | Optional. Timezone. Incorrect values may cause HTTPS/SSL issues.                                                                                                                                                                            |

# Manual setup

Use this only in case you can't run the docker image.

`pip install quasarr`

* Requires Python 3.12 or later

```
  --port=8080
  --discord=https://discord.com/api/webhooks/1234567890/ABCDEFGHIJKLMN
  --external_address=https://foo.bar/
  --hostnames=https://quasarr-host.name/ini?token=123...
  ```

* `--discord` see `DISCORD`docker variable
* `--external_address` see `EXTERNAL_ADDRESS`docker variable
* `--hostnames` see `HOSTNAMES`docker variable

# Philosophy

Complexity is the killer of small projects like this one. It must be fought at all cost!

We will not waste precious time on features that will slow future development cycles down.
Most feature requests can be satisfied by:

- Existing settings in Radarr/Sonarr/LazyLibrarian
- Existing settings in JDownloader
- Existing tools from the *arr ecosystem that integrate directly with Radarr/Sonarr/LazyLibrarian

# Roadmap

- Assume there are zero known
  issues [unless you find one or more open issues in this repository](https://github.com/rix1337/Quasarr/issues).
- Still having an issue? Provide a detailed report [here](https://github.com/rix1337/Quasarr/issues/new/choose)!
- There are no hostname integrations in active development unless you see an open pull request
  [here](https://github.com/rix1337/Quasarr/pulls).
- **Pull requests are welcome!** Especially for popular hostnames.
    - A short guide to set up required dev services is found
      in [/docker/dev-setup.md](https://github.com/rix1337/Quasarr/blob/main/docker/dev-setup.md)
    - Always reach out on Discord before starting work on a new feature to prevent waste of time.
    - Please follow the existing code style and project structure.
    - Anti-bot measures must be circumvented fully by Quasarr. Thus, you will need to provide a working solution for new
      CAPTCHA types by integrating it in the Quasarr Web UI.
    - Please provide proof of functionality (screenshots/examples) when submitting your pull request.

# SponsorsHelper

<img src="https://imgur.com/iHBqLwT.png" width="64" height="64" />

SponsorsHelper is a Docker image that solves CAPTCHAs and decrypts links for Quasarr.  
Image access is limited to [active monthly GitHub sponsors](https://github.com/users/rix1337/sponsorship).

[![Github Sponsorship](https://img.shields.io/badge/support-me-red.svg)](https://github.com/users/rix1337/sponsorship)

---

## 🔑 GitHub Token Setup

1. Start your [sponsorship](https://github.com/users/rix1337/sponsorship) first.
2. Open [GitHub Classic Token Settings](https://github.com/settings/tokens/new?type=classic)
3. Name it (e.g., `SponsorsHelper`) and choose unlimited expiration
4. Enable these scopes:
    - `read:packages`
    - `read:user`
    - `read:org`
5. Click **Generate token** and copy it for the next steps

---

## 🔐 Quasarr API Key Setup

1. Open your Quasarr web UI in a browser
2. On the main page, expand **"Show API Settings"**
3. Copy the **API Key** value
4. Use this value for the `QUASARR_API_KEY` environment variable

> **Note:** The API key is required for SponsorsHelper to communicate securely with Quasarr. Without it, all requests
> will be rejected with a 401/403 error.

---

## 🐋 Docker Login

⚠️ **If not logged in, the image will not download.**

```bash
echo "GITHUB_TOKEN" | docker login ghcr.io -u USERNAME --password-stdin
````

* `USERNAME` → your GitHub username
* `GITHUB_TOKEN` → the token you just created

## ▶️ Run SponsorsHelper

⚠️ **Without a valid GitHub token linked to an active sponsorship, the image will not run.**

```bash
docker run -d \
  --name='SponsorsHelper' \
  -e 'QUASARR_URL'='http://192.168.0.1:8080' \
  -e 'QUASARR_API_KEY'='your_quasarr_api_key_here' \
  -e 'DEATHBYCAPTCHA_TOKEN'='2FMum5zuDBxMmbXDIsADnllEFl73bomydIpzo7...' \
  -e 'GITHUB_TOKEN'='ghp_123.....456789' \
  -e 'FLARESOLVERR_URL'='http://10.10.0.1:8191/v1' \
  -e 'NX_USER'='your_nx_username' \
  -e 'NX_PASS'='your_nx_password' \
  -e 'JUNKIES_USER'='your_junkies_username' \
  -e 'JUNKIES_PASS'='your_junkies_password' \
  -e 'JUNKIES_HOSTER'='your_desired_hoster' \
  ghcr.io/rix1337-sponsors/docker/helper:latest
```

| Parameter                       | Description                                                                           |
|---------------------------------|---------------------------------------------------------------------------------------|
| `QUASARR_URL`                   | Local URL of Quasarr (e.g., `http://192.168.0.1:8080`)                                |
| `QUASARR_API_KEY`               | Your Quasarr API key (found in Quasarr web UI under "API Settings")                   |
| `DEATHBYCAPTCHA_TOKEN`          | [DeathByCaptcha](https://deathbycaptcha.com/register?refid=6184288242b) account token |
| `GITHUB_TOKEN`                  | Classic GitHub PAT with the scopes listed above                                       |
| `FLARESOLVERR_URL`              | Local URL of [FlareSolverr](https://github.com/FlareSolverr/FlareSolverr)             |
| `NX_USER` / `NX_PASS`           | Optional. NX account credentials                                                      |
| `JUNKIES_USER` / `JUNKIES_PASS` | Optional. Junkies account credentials                                                 |
| `JUNKIES_HOSTER`                | Optional. Preferred hoster for Junkies links                                          |
