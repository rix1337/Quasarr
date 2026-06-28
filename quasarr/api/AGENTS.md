# quasarr/api/ — HTTP Surface

## Purpose

The single Bottle app serving (1) the Newznab-indexer and SABnzbd-client emulation consumed by the *arr apps, (2) the browser web UI, (3) the JSON config endpoints behind that UI, and (4) the SponsorsHelper companion API. `get_api()` is the main process's blocking entrypoint, called from `quasarr/__init__.py` after the helper workers are spawned as daemon processes.

## Ownership

Submodules are packages with all code in their `__init__.py`: `arr/` (emulation core), `captcha/` (manual decryption pages, userscript flows, solver proxying), `config/` (settings endpoints), `jdownloader/` (page-fragment helpers, registers no routes), `packages/` (package list UI), `sponsors_helper/`, `statistics/`.

## Local Contracts

- Each route submodule exposes one setup function taking the Bottle app (or app + shared_state), wired into `get_api()` in `quasarr/api/__init__.py` (`jdownloader/` is the exception: a helper module with no routes and no setup function). The auth routes and auth hook must be installed before any route module registers.
- Auth is enforced structurally: every route under `/api`, `/download/`, or `/sponsors_helper/api/` must carry `@require_api_key`, or the startup call `audit_route_auth_modes(...)` raises `RuntimeError` and the app will not start. Routes ending in `.user.js` are public by whitelist. Everything else defaults to browser auth, which is a no-op unless `USER` and `PASS` env vars are set.
- SABnzbd emulation (`GET/POST /api` with `?mode=`): responses mimic SABnzbd JSON; Quasarr package IDs are surfaced as `nzo_ids`; `get_cats` keeps `*` as the first category; `get_config` returns `misc.quasarr=True` so the *arrs can detect Quasarr; queue/history embed a nonstandard `linkgrabber` object; failures add `quasarr_error: True`.
- Newznab emulation (`GET /api` with `?t=`): movie/tv searches (`t=movie`, `t=tvsearch`) are imdbid-only (q-only requests are deliberately ignored, except q-as-episode alongside an imdbid); `t=book`/`t=music` search by author/title phrase; `t=search` is honored only for magazarr/lidarr User-Agents; RSS titles are prefixed `[<XY>]` except for magazarr; enclosures use type `application/x-nzb`; a placeholder "No results found" item is returned when neither imdbid nor q is present and the search produced no items — it keeps *arr connectivity tests passing.
- The fake-NZB roundtrip: search results embed `/download/?payload=...`; `GET /download/` renders `<nzb><file title url size_mb password imdb_id source_key/></nzb>` (the free-text `title`/`url`/`password` attributes are XML-escaped via `_xml_attr`, so source-specific characters like `&` in hoster URLs or accents in French titles do not corrupt the NZB); the *arr app posts that file back via `POST /api` (multipart field `name`) or `mode=addurl`, and both paths decode the same payload and call `quasarr.downloads.download()`. The payload format is owned by `providers/utils.py` (`generate_download_link`/`parse_payload`).
- Client identity comes exclusively from the User-Agent header (`extract_client_type` and the category resolvers in `providers/utils.py`).
- Every successful CAPTCHA flow ends in `downloads.submit_final_download_urls(..., remove_protected=True, notification_details=...)` and increments the matching `StatsHelper` counters; manual flows identify their solution method and SponsorsHelper passes solver details. Terminal submission failures increment failed counters and update the same tracked release notification. SponsorsHelper disable persists the advanced notification case/silence state so a later manual solution evaluates the next transition correctly.
- SponsorsHelper routes use trailing slashes; most require an active helper (HTTP 402 otherwise), tracked via `helper_last_seen` with a 300s timeout; `to_decrypt/` only hands out packages matching the helper's advertised `supported_urls`.
- The external CAPTCHA-solver host and all userscript bodies come only from `quasarr.providers.obfuscated`; source hostnames come only from `Config("Hostnames")` at runtime.

## Work Guidance

- JSON config endpoints return `{success: bool, message: str}` unless they are read endpoints with richer payloads; frontend JS calls protected `/api` endpoints through the global `quasarrApiFetch` helper injected by `html_templates`.
- HTML is built with f-strings (double `{{ }}` for literal CSS/JS braces) via `providers.html_templates` and `providers.html_images`; follow the brace style of the file being edited.
- `/api/packages/content` intentionally returns an HTML fragment (not JSON) despite requiring the API key.
- The dashboard hostname-status pill replicates logic from `storage/setup`; changes there must stay in sync.
- `/api/restart` works by SIGINT-ing its own process — it relies on the Docker restart-loop contract in `docker/AGENTS.md`.

## Verification

- Full unit suite: `uv run python -X utf8 -m unittest discover -s tests`
- Live behavior against a running instance: `uv run cli_tester.py`

## Child DOX Index

None.
