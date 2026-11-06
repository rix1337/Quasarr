#

<img src="https://raw.githubusercontent.com/rix1337/Quasarr/main/Quasarr.png" data-canonical-src="https://raw.githubusercontent.com/rix1337/Quasarr/main/Quasarr.png" width="64" height="64" />

Quasarr connects JDownloader with Radarr, Sonarr, Lidarr and Magazarr. It reads download sites, offers their releases
to your apps and sends the ones they pick to JDownloader, including links protected by CAPTCHAs.

[![PyPI version](https://badge.fury.io/py/quasarr.svg)](https://badge.fury.io/py/quasarr)
[![SimpleX Community](https://img.shields.io/badge/SimpleX-Community-blue)](https://smp14.simplex.im/c#huQ65mF5BdP6HJ7wCfByVkwy6w2zghW3WF-YLK8O5wc)
[![GitHub Sponsorship](https://img.shields.io/badge/support-me-red.svg)](https://github.com/users/rix1337/sponsorship)

To your apps, Quasarr looks like a `Newznab Indexer` and a `SABnzbd client`. It does not work with real usenet
indexers and does not know what NZB files are.

# Getting started

1. Set up and run [JDownloader 2](https://jdownloader.org/download/index).
2. Run Quasarr, preferably with [Docker](#docker).
3. Open the web UI and follow the setup: My JDownloader login, then at least one site.
4. Add Quasarr to [Radarr, Sonarr and Lidarr](#radarr--sonarr--lidarr), [Prowlarr](#prowlarr) or
   [Magazarr](#magazarr).
5. Optional: set up [flaresolverr-next](https://github.com/rix1337/flaresolverr-next) for sites that show a browser
   check.

> **Finding your Quasarr URL and API key**
> Both are shown in the console output under **API Information** and in the web UI.

> **Authentication** is optional but strongly recommended.
> - 🔐 Set `USER` and `PASS` to enable form-based login (30-day session).
> - 🔑 Set `AUTH=basic` to use HTTP Basic Authentication instead.

# Sites

Quasarr needs at least one site to start. It does not provide or endorse any sources.

## Adding sites

Paste the hostnames you use under **Sites** in the web UI, one per line, or load a list from a URL. Lines such as
`xy = example.org` from community lists work too. Quasarr opens each site, tells you which built-in template matches it
and adds them in one go. Sites that need your login ask for it right in the list.

Community-maintained lists help you find hostnames:

🔗 **[https://quasarr-hostnames.pages.dev](https://quasarr-hostnames.pages.dev)**: community guide for finding
hostnames

📋 Community suggestions via [pastebin search](https://pastebin.com/search?q=hostnames+quasarr) (login required).

## Sites without a matching template

When no built-in template matches a hostname, Quasarr says so and offers **Set it up yourself**: a guided setup for
experienced users that works on desktop and phones and needs no code.

1. **Site:** hostname, a name and the language of its releases. You can also import a template someone shared.
2. **Feed:** Quasarr finds the page for each kind in the site menu, picks the release block and the release name,
   link, size and date, and tests every page. A preview shows what it read; pick a dropdown entry or click the page
   to change it.
3. **Search:** Quasarr finds the site's search and tests it with each kind's newest release, by IMDb ID or, when the
   site cannot find IDs, by title. Results laid out differently from the feed get their own fields.
4. **Downloads:** Quasarr opens a release page and frames its download or crypter links. When there are none, the
   site needs a userscript.
5. **Save:** a summary of everything set up, and the template to export.

Every step has a test that runs the same code Quasarr uses for your apps, so you see the releases and links before
saving.

Sites that need a login cannot be set up this way. They need Python code, contributed as a pull request.

A site you set up yourself is yours to maintain. Issues about it are not supported.

<details>
<summary>Links that only appear in a browser</summary>

Some sites show their download links only after a CAPTCHA or a click. In the downloads step you can hand such release
pages to a userscript you write: when your app grabs a release, the CAPTCHA page opens it in your browser and your
script sends the links back.

Install [Tampermonkey](https://www.tampermonkey.net/) first, then the userscript template the setup links to. The
template does not work out of the box. It only connects the page to Quasarr, and you add the code that finds the links.
Unlike the shipped userscripts it is not obfuscated, so you can read and extend it. It never updates itself, so your
code stays. Do not change the part marked as the Quasarr connection.

</details>

## Share a site

Once a site of your own reads its newest releases and finds what you search for, **Share** on the sites page turns it
into a template. The hostname is never part of it. Others can import it under **Set it up yourself**. If it runs
stable for you, please open a pull request with it, so the site becomes built-in for everyone.

## Changing a built-in site

When a site changes and an update is not out yet, experienced users can change its template under **Sites → More**.
The editor shows the template as JSON and tests every step before you save. Sites whose steps run Quasarr's own code
let you change the addresses that code requests.

A changed site is yours to maintain. Issues about it are not supported, so reset it to the shipped version before you
report a problem. Removing a changed site resets it.

## Hostname rules

Quasarr refuses hostnames of link protection services (such as FileCrypt) and file hosters. Those are where downloads
end up, not sites that list releases.

Sites behind a browser check are loaded through FlareSolverr when it is set up. Quasarr passes the check once per site
and reuses it, so FlareSolverr only steps in again when the check expires.

# CAPTCHAs and protected links

Quasarr includes a way to quickly decrypt protected links.
[Active monthly sponsors get access to SponsorsHelper to do so automatically.](https://github.com/rix1337/Quasarr?tab=readme-ov-file#sponsorshelper)
Otherwise, follow the link from the console output or a notification and solve the CAPTCHA in your browser.

This needs [Tampermonkey](https://www.tampermonkey.net/) and the matching Quasarr userscript; the CAPTCHA page guides
you through installing both once. You solve the CAPTCHA on the crypter's own page, and the userscript sends the links
back to Quasarr. The shipped userscripts are obfuscated, which makes it harder for crypters to detect and block them.

If a crypter stops working for a while, switch it off under **Web UI → Crypter Kill Switches**. New grabs that only
have links from it then fail, so your app can try another release instead of stalling.

# JDownloader

> ⚠️ If using Docker:
> JDownloader's download path must be available to Radarr/Sonarr/Lidarr/Magazarr with **identical internal and
> external path mappings**. Matching only the external path is not enough.

1. Start JDownloader and connect it to [My JDownloader](https://my.jdownloader.org).
2. Enter your My JDownloader credentials during Quasarr setup.

<details>
<summary>Fresh install recommended</summary>

Consider a fresh JDownloader instance. Quasarr changes JDownloader's settings for the Radarr/Sonarr/Lidarr/Magazarr
integration.

</details>

# Categories and mirrors

Manage categories in the web UI.

* **Download categories** organize your downloads. Inside one you can allow only certain mirrors: downloads then
  fail unless the release is available from them. This affects the **Quasarr download client** in your apps, not
  search results.
* **Search categories** can be limited to certain sites. Only those sites are then searched for that category. This
  affects the **Quasarr Newznab indexer** in your apps.

# Radarr / Sonarr / Lidarr

Add Quasarr as both a **Newznab Indexer** and a **SABnzbd Download Client** with your Quasarr URL and API key.

Set a category in the **SABnzbd Download Client** (default: `movies` for Radarr, `tv` for Sonarr and `music` for
Lidarr).

<details>
<summary>Show download status in Radarr/Sonarr/Lidarr</summary>

**Activity → Queue → Options** → enable `Release Title`.

</details>

# Prowlarr

Add Quasarr as a **Generic Newznab Indexer**.

* **Url:** your Quasarr URL
* **ApiKey:** your Quasarr API key

<details>
<summary>Allowed search parameters and categories</summary>

#### Movies / TV

* Search by IMDb ID, syntax `{ImdbId:tt0133093}`, with category `2000` (Movies) or `5000` (TV).
* Plain text search is **not** supported.

#### Music / Books / Magazines

* Plain text search with category `3000` (Music) or `7000` (Books/Magazines).

</details>

# Magazarr

[Magazarr](https://github.com/rix1337/Magazarr) is the magazine companion for Quasarr. It keeps your magazine list,
searches Quasarr, sends selected releases to Quasarr for download, imports completed PDFs from JDownloader folders and
serves your library through OPDS.

<details>
<summary>Configure Magazarr</summary>

Run Magazarr and open `http://127.0.0.1:8090`:

```bash
docker run -d \
  --name="Magazarr" \
  -p 8090:8090 \
  -v /path/to/magazarr-config:/config:rw \
  -v /path/to/magazine-library:/library:rw \
  -v /path/to/jdownloader-output:/output:rw \
  -e TZ=Europe/Berlin \
  ghcr.io/rix1337/magazarr:latest
```

Set these values in Magazarr:

| Setting                 | Value                                                                                    |
|-------------------------|------------------------------------------------------------------------------------------|
| Quasarr URL             | Your Quasarr URL                                                                         |
| Quasarr API Key         | Your Quasarr API key                                                                     |
| Search category         | `7000`                                                                                   |
| Download category       | `docs`                                                                                   |
| JDownloader import root | `/output`, or the same internal path where completed JDownloader packages are visible    |
| Library directory       | `/library`, or wherever Magazarr should store imported PDFs                              |

Magazarr imports the PDF and cleans up the completed package folder.

</details>

# Docker

Run the latest image with all optional variables set.

```
docker run -d \
  --name="Quasarr" \
  -p port:8080 \
  -v /path/to/config/:/config:rw \
  -e INTERNAL_ADDRESS=http://192.168.0.1:8080 \
  -e EXTERNAL_ADDRESS=https://foo.bar/ \
  -e USER=admin \
  -e PASS=change-me \
  -e AUTH=form \
  -e TZ=Europe/Berlin \
  ghcr.io/rix1337/quasarr:latest
```

| Parameter          | Description                                                                                       |
|--------------------|---------------------------------------------------------------------------------------------------|
| `INTERNAL_ADDRESS` | **Required.** Internal URL so Radarr/Sonarr/Lidarr/Magazarr can reach Quasarr. **Include the port.** |
| `EXTERNAL_ADDRESS` | Optional. External URL, for example behind a reverse proxy. Always protect it with authentication. |
| `USER` / `PASS`    | Optional, but recommended. Username and password for the web UI.                                  |
| `AUTH`             | Authentication mode: `form` or `basic`.                                                           |
| `TZ`               | Timezone. A wrong value can cause HTTPS/SSL errors.                                               |

Keep `/config` on persistent storage. It holds your settings, including your own sites.

# Manual setup

> Only use this if you can't run the Docker image.

> ⚠️ Requires Python 3.12 or later and [uv](https://docs.astral.sh/uv/#installation).

`uv tool install quasarr`

```
export INTERNAL_ADDRESS=http://192.168.0.1:8080
export EXTERNAL_ADDRESS=https://foo.bar/
quasarr
```

`EXTERNAL_ADDRESS` works as described for Docker.

# Notifications

Quasarr notifies you through Discord, Telegram or Pushover. Configure them under **Web UI → Notifications
Configuration**: set provider credentials and choose which notifications each provider gets. *Silent* notifications
play no sound.

## Discord

<details>
<summary>Configure Discord</summary>

1. In your Discord server, open **Server Settings → Integrations → Webhooks**.
2. Click **New Webhook**, choose the target channel and copy the **Webhook URL**.
3. In Quasarr, open **Notifications**.
4. Paste the webhook URL into **Discord → Webhook URL**.
5. Click **Save Notification Settings**, then **Send Discord Test**.

</details>

## Telegram

<details>
<summary>Configure a Telegram bot</summary>

1. **Create a bot:** in Telegram, open [@BotFather](https://t.me/BotFather), send `/newbot` and follow the prompts.
2. **Copy the token:** BotFather replies with an HTTP API token (e.g. `123456789:ABCdefGHI...`). This is your
   `TELEGRAM_BOT_TOKEN`.
3. **Start a chat with the bot:** send it any message (e.g. `/start`) so it can message you back.
4. **Get your chat ID:** open this URL in a browser, with `<TOKEN>` replaced by your bot token:
   ```
   https://api.telegram.org/bot<TOKEN>/getUpdates
   ```
   The number after `"chat":{"id":` is your `TELEGRAM_CHAT_ID`.
   > **Tip:** for a group chat, add the bot to the group, send a message there, then call `getUpdates`.
5. In Quasarr, open **Notifications**.
6. Paste both values into **Telegram → Bot Token / Chat ID**.
7. Click **Save Notification Settings**, then **Send Telegram Test**.

</details>

## Pushover

<details>
<summary>Configure Pushover</summary>

[Pushover](https://pushover.net) sends notifications to its iOS, Android and desktop apps. After a 30-day trial, each
platform needs a one-time purchase. Up to 10,000 messages a month are free.

1. **Get your user key:** sign up at [pushover.net](https://pushover.net), log in and copy the **User Key** shown on
   your dashboard. To notify several people, create a group in Pushover and use its group key instead.
2. **Register an application:** open [pushover.net/apps/build](https://pushover.net/apps/build), name it `Quasarr`
   (an icon is optional), accept the terms and copy the application's API token.
3. **Install the Pushover app** on your phone or computer and log in, so the device receives messages.
4. In Quasarr, open **Notifications**.
5. Paste the values into **Pushover → Application API Token** and **User or Group Key**. Both are 30 letters and digits.
6. Click **Save Notification Settings**, then **Send Pushover Test**.

Notifications arrive with their links, and with the poster when one is available. *Silent* notifications use Pushover's lowest priority: they show up
in the app without a sound or an alert. The notice that SponsorsHelper was switched off uses high priority, so it sounds
even during quiet hours.

</details>
<br>

# Philosophy

Complexity is the killer of small projects like this one. It must be fought at all cost.

We do not spend time on features that slow future development down. Most feature requests are already covered by:

- settings in Radarr/Sonarr/Lidarr/Magazarr
- settings in JDownloader
- tools from the *arr ecosystem that integrate directly with Radarr/Sonarr/Lidarr/Magazarr

# Contributing

- Assume there are no known issues
  [unless an issue is open in this repository](https://github.com/rix1337/Quasarr/issues).
- Still stuck? File a detailed report [here](https://github.com/rix1337/Quasarr/issues/new/choose). Reports about
  built-in sites you changed or sites you set up yourself are not supported.
- No site integration is in development unless a [pull request](https://github.com/rix1337/Quasarr/pulls) is open.
- **Pull requests are welcome**, especially for popular sites:
    - The easiest way to add a site is to [set it up yourself](#sites-without-a-matching-template) and
      [share it](#share-a-site) as a template.
    - Sites that need a login, an API or other code ship as a template package: the template plus the site's
      search and download modules beside it, which read the site's addresses from the template.
    - Start with [AGENTS.md](AGENTS.md) for repository guidelines: development setup, local run commands, tests,
      linting and commit/PR conventions. Development environment setup also lives in [CONTRIBUTING.md](CONTRIBUTING.md).
    - Reach out on [SimpleX](https://smp14.simplex.im/c#huQ65mF5BdP6HJ7wCfByVkwy6w2zghW3WF-YLK8O5wc) before starting
      work on a new feature.
    - Follow the existing code style and project structure.
    - CAPTCHA solving for new link crypters runs through Tampermonkey userscripts. Provide a working userscript that
      integrates with the CAPTCHA flow of the Quasarr web UI.
    - Show that it works (screenshots or examples) in your pull request.

# SponsorsHelper

<img src="https://raw.githubusercontent.com/rix1337/Quasarr/main/SponsorsHelper.png" data-canonical-src="https://raw.githubusercontent.com/rix1337/Quasarr/main/SponsorsHelper.png" width="64" height="64" />

SponsorsHelper is a Docker image that solves CAPTCHAs and decrypts links for Quasarr.  
The image is public, but requires a valid [active monthly GitHub sponsor](https://github.com/users/rix1337/sponsorship) check at runtime.
Crypters change their CAPTCHAs all the time, so SponsorsHelper needs constant upkeep. The recurring monthly sponsorship
pays for that upkeep, which is why the check looks for an active one rather than a one-time payment.

[![Github Sponsorship](https://img.shields.io/badge/support-me-red.svg)](https://github.com/users/rix1337/sponsorship)

---

## 🔐 Quasarr API Key Setup

1. Open your Quasarr web UI in a browser
2. On the main page, expand **"Show API Settings"**
3. Copy the **API Key** value
4. Use this value for the `QUASARR_API_KEY` environment variable

> **Note:** The API key is required for SponsorsHelper to communicate securely with Quasarr. Without it, all requests
> will be rejected with a 401/403 error.

---

## 🔑 GitHub Auth

> ⚠️ Mount `/config` to persistent storage. Otherwise the auth token is lost on container recreation/update.

1. Start your [sponsorship](https://github.com/users/rix1337/sponsorship).
2. Start SponsorsHelper.
3. In container logs, open the GitHub authorization URL shown by SponsorsHelper.
4. Confirm the authorization in browser.
5. Done. SponsorsHelper caches the auth token in `/config/github_oauth_token.json`.

---

## ▶️ Run SponsorsHelper

```bash
docker run -d \
  --name=SponsorsHelper \
  -v /path/to/sponsorshelper-config:/config \
  -e QUASARR_URL=http://192.168.0.1:8080 \
  -e QUASARR_API_KEY=your_quasarr_api_key_here \
  -e FLARESOLVERR_URL=http://192.168.0.1:8191/v1 \
  -e APIKEY_2CAPTCHA=your_2captcha_api_key_here \
  -e TZ=Europe/Berlin \
  ghcr.io/rix1337/sponsors-helper:latest
```

| Parameter              | Description                                                                                   |
|------------------------|-----------------------------------------------------------------------------------------------|
| `QUASARR_URL`          | Local URL of Quasarr (e.g., `http://192.168.0.1:8080`)                                        |
| `QUASARR_API_KEY`      | Your Quasarr API key (found in Quasarr web UI under "API Settings")                           |
| `FLARESOLVERR_URL`     | Local URL of [flaresolverr-next](https://github.com/rix1337/flaresolverr-next)                |
| `APIKEY_2CAPTCHA`      | [2Captcha](https://2captcha.com/?from=27506687) account API key                               |
| `TZ`                   | Timezone for SponsorsHelper (e.g., `Europe/Berlin`)                                 |
