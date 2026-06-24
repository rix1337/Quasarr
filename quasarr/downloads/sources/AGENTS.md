# quasarr/downloads/sources/ — Download Source Plug-ins

## Purpose

Per-source modules that resolve a release page URL into actual hoster/crypter links. Most new source work lands here and in the search twin.

## Ownership

Two-letter lowercase source modules (`dw.py`, `nx.py`, ...) plus `helpers/`: `abstract_source.py` (the ABC), `download_release.py` (return shape), `junkies.py` (SJ/DJ mirror pre-check), `anime_title.py` (release-title synthesis, also imported by the search side).

## Local Contracts

- Plug-in contract: a module directly in this folder (not `helpers`, not `_`-prefixed) must expose a class named exactly `Source` subclassing `AbstractDownloadSource`, with an `initials` property equal to the lowercase filename and `Hostnames` config key, and `get_download_links(self, shared_state, url, mirrors, title, password) -> DownloadRelease`.
- Discovery is automatic via `pkgutil` and cached for the process lifetime — adding a source requires a restart; there is no manual registry to edit. Registration must never raise; bad modules are logged and skipped.
- `DownloadRelease`: `{links: [[url, mirror]] or [[url, mirror, state_url]], title?, password?, imdb_id?}`. Empty/missing `links` means "no match" and the orchestrator tries the next candidate; return `{"links": []}` on failure rather than raising.
- `mirrors` is the lowercase download-category whitelist; links whose hoster is not in it should be skipped (substring matching is the prevailing style).
- Every download source has a same-key search twin under `quasarr/search/sources/`, but not the reverse: a download module exists only when release links need source-specific extraction (FX is search-only). A new source adds entries to the Per-Source Notes here and in the search AGENTS.md in the same change.
- SJ/DJ: the site itself is the crypter — they return `[[url, "junkies"]]`; the literal mirror string `junkies` routes the package to the protected bucket and the junkies userscript flow.
- Error idiom: broad try/except, `info(...)` with user-facing text, `mark_hostname_issue(Source.initials, "download", str(e))`, return `{"links": []}`.

## Work Guidance

- Hostnames are never hardcoded: resolve via `shared_state.values["config"]("Hostnames").get(Source.initials)`.
- Timeouts from `constants.DOWNLOAD_REQUEST_TIMEOUT_SECONDS`; User-Agent from `shared_state.values["user_agent"]`. Login-required sources use `quasarr/providers/sessions/<xx>.py` and invalidate the session on API errors.
- Never load or probe crypter/hoster URLs beyond what extraction requires (e.g. SF stops redirect resolution as soon as `detect_crypter_type()` recognizes the URL). The mirror-selection policy in the parent doc applies to every selection decision here.
- Do not infer payloads or response shapes — the root `Third-Party Source Work` rules require real traffic captures or direct curl confirmation before changing how a source is requested, parsed, or matched.

### Per-Source Notes (download side)

Search-side notes live in `quasarr/search/sources/AGENTS.md`.

- **AL** — link protection in `linkcrypters/al.py` (pick-the-different-image CAPTCHA + CNL); FlareSolverr required. Session-binding contract: the details page and initial captcha request are armed on the FlareSolverr browser session, but the solve and the final validation MUST run on the same `requests.Session` — the source binds a solved CAPTCHA to the solving client, and validating via FlareSolverr is rejected as an invalid captcha id. CAPTCHA POSTs send browser-style AJAX headers and the requests session keeps the current FlareSolverr User-Agent. The `password` argument arrives repurposed as the release id (set by the search twin); the image captcha is retried 3× with a 30s backoff on slow-down responses; returns an overridden title and a `www.<host>` password.
- **AT** — direct links resolved against requested mirrors; the returned title is re-synthesized via `helpers/anime_title.guess_release_title` with XEM season-name resolution.
- **BY** — links come from same-host iframes inside the post: hide/filecrypt container links (or legacy `go.php` redirects) are extracted and their redirect chains resolved manually (`allow_redirects=False`, max 8 hops, loop/404 detection, stopping as soon as a crypter is detected — the crypter page is never loaded); protected links are returned tagged `filecrypt` for the CAPTCHA flow; direct links are accepted only from a fixed hoster-prefix whitelist; the mirror filter is substring matching on the link's hoster label.
- **DD** — queries the API and applies its own hostname-based mirror filter; dedupes multiple `.mkv` links per hoster; the API's `fake` release flag triggers session re-creation and abort.
- **DJ / SJ** — the site itself is the crypter: requested mirrors are pre-checked via `helpers/junkies.py` against the site's releases API, then the page URL is returned tagged `junkies`, routing the package to the protected bucket and the junkies userscript CAPTCHA flow.
- **DL** — anchor and plaintext URLs are extracted from forum posts (crypter URLs — filecrypt/hide/keeplinks/tolink — plus whitelisted direct hosters; the plaintext scan skips text inside anchors to avoid duplicates); posts are iterated until one yields links verified online via their status URLs, keeping the first unverifiable post as fallback; when the post names no password, a `www.<host>` default is used.
- **DT** — plain direct-link extraction; no download-side quirks.
- **DW** — scrapes `show_link` buttons, then POSTs per button to the site's admin-ajax endpoint; affiliate redirect links (`af.php?v=ID`) are rewritten into filecrypt container URLs; the hoster name is parsed from the button's sibling image filename (`fichier*` → `1fichier`).
- **FF** — movie-only companion to the search source. `/external` URLs are resolved manually (`allow_redirects=False`, max 8 hops, loop/404 detection) and resolution returns as soon as a crypter is detected or the redirect leaves the configured FF host, so hoster/crypter pages are not probed. Release-page URLs are reloaded at grab time, the movie-token API is fetched, the requested release title is matched exactly, and the first requested mirror is resolved.
- **FX** — no module here; its filecrypt links flow through the orchestrator's crypter fallback and `linkcrypters/filecrypt.py`.
- **HE** — links sit behind a content-protector access form that the module extracts (including JS-injected payload fields) and submits to unlock them; the unlocked links are direct, with a FlareSolverr retry loop (up to 3 attempts) when the plain fetch is challenged; mirrors filtered by normalized hostname against the configured mirror list.
- **HS** — extracts filecrypt container links from the post; mirror names come from link text labels, with an affiliate-link pairing fallback.
- **MB** — extracts filecrypt container links only; the mirror name comes from the anchor text.
- **MX** — no fetch: the search twin already decoded the final hoster URL (1Fichier, Send, ...) into the payload, so the module just returns `[[url, mirror]]` with the mirror derived from the URL host (`_derive_mirror_from_url`), honoring the `mirrors` whitelist via substring match.
- **NK** — on-site `/go/` redirect links are manually resolved into filecrypt links (max 8 hops, never fetching the crypter page); unresolved `/go/` links must never be yielded — they bypass protected-link classification and land in JDownloader as broken direct links; supported mirrors are limited to a two-hoster whitelist.
- **NX** — single supported hoster (`filer`): mirror requests not including it are rejected outright; folder URLs are expanded through the hoster's folder API into per-file links; the session DB row is deleted whenever the API errors.
- **RM** — API-backed; returns a title override and `imdb_id` from the JSON payload; defines the `_bootstrap_session` helper that the search twin imports.
- **SF** — two URL modes: `/external` redirect URLs are resolved manually (`allow_redirects=False`, max 8 hops, loop detection, 404 detection) and resolution stops as soon as `detect_crypter_type()` recognizes the URL — the crypter page itself is never loaded; series pages are matched via a strict release-title regex against the season API.
- **SL** — every fetch requires Cloudflare clearance via the shared bypass helper (like its search side); direct links restricted to a two-hoster whitelist.
- **WD** — resolves on-site redirects into filecrypt protected links via `detect_crypter_type`, with a FlareSolverr fallback on Cloudflare challenges.
- **WX** — 4-tier mirror selection on source-provided status badges: green hide container > green filecrypt container > green direct links > first offline-flagged mirror as last resort. The badge certifies the crypted container, not the separately-uploaded direct links; link sets are never merged across mirrors; the tier-4 fallback keeps all multipart URLs. Uploads from the user ids in `HIDE_CX_MIRROR_USER_IDS` get their filecrypt container rewritten to the hide-crypter `/fc/` twin so `hide.py` auto-resolves it without a CAPTCHA — this mirrors the site's own frontend logic; when the hide twin is missing, `hide.py` returns nothing and the normal protected fallback applies.

## Verification

- Targeted tests exist for several sources (`test_protected_redirect_resolution.py`, `test_wx_direct_links.py`, `test_dl_plaintext_links.py`); run the full suite after changes: `uv run python -X utf8 -m unittest discover -s tests`

## Child DOX Index

None.
