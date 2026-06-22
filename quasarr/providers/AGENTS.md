# quasarr/providers/ — Shared Services

## Purpose

The shared-services layer consumed by every other subsystem: cross-process state and the My.JDownloader device lifecycle, web server, logging, auth, per-source sessions, notifications, metadata lookups, statistics, Cloudflare/FlareSolverr helpers, HTML templating, and generic utils.

## Ownership

- `shared_state.py` — process-shared singleton (`set_state()` per process) and the JD device lifecycle (`get_device`, `run_device_request`, `set_device_settings`)
- `web_server.py` — WSGI wrapper; `serve_forever()` for the API, `serve_temporarily()` + `temp_server_success` flag for setup wizards
- `log.py` — loguru wrapper; context emoji from the caller's module name via `_context_replace`; per-context levels via `LOG`/`LOG_<CONTEXT>` env vars
- `auth.py` — route auth modes (`public_endpoint`/`require_api_key`/browser default), Bottle auth hook, startup audit
- `myjd_api.py` — vendored, modified My.JDownloader client (MIT, third-party) — keep modifications minimal
- `jd_cache.py` — `JDPackageCache`, valid for exactly one `get_packages()`/`delete_package()` call, never reused across requests
- `imdb_metadata.py` / `xem_metadata.py` — cached metadata chains (IMDb 3-tier fallback; TheXEM season names)
- `radarr_api.py` / `sonarr_api.py` — minimal clients cached in shared_state via `set_client`/`get_client`; IMDb→TMDB/TVDB resolution (`get_tmdb_id`/`get_tvdb_id`) plus library-feed seeds `get_wanted_imdb_ids` / `get_wanted_episodes` (wanted = missing + cutoff-unmet, missing first, capped at the passed `limit`; the movie helper also skips not-yet-released titles). All return safe empties when the client is unconfigured.
- `statistics.py` — DB-backed counters, constructed inline at call sites
- `version.py` — `__version__`, the single source of version truth
- `obfuscated.py` — obfuscated userscripts and captcha-service endpoint values; consumed only by `api/captcha`
- `cloudflare.py` — challenge detection, `ensure_session_cf_bypassed`, FlareSolverr get/post/session helpers
- `html_templates.py` / `html_images.py` — UI page shell and base64 image constants
- `hostname_issues.py` — DB-backed source health tracker (`mark_/clear_/get_hostname_issue`)
- `utils.py` — grab-bag: payload generate/parse, category resolvers, title matching, online-status checks, `download_package` (the JD linkgrabber submission)
- `sessions/` and `notifications/` — see Child DOX Index

## Local Contracts

- Each process calls `shared_state.set_state(dict, lock)` before use; read `shared_state.values[key]`, write `shared_state.update(key, value)`. `values["config"]`/`["database"]` hold the classes, not instances.
- All JDownloader access goes through `shared_state.get_device()` (blocks and retries forever with escalating backoff) or `run_device_request(name, fn, default)` (one reconnect+retry then the default on JD request errors — but its first attempt calls `get_device()` internally, so it too blocks until a device is connected). `TokenExpiredException`/`RequestTimeoutException`/`MYJDException` from `myjd_api` are the canonical JD error set.
- `generate_download_link` and `parse_payload` must stay in sync: urlsafe-base64 of exactly 6 pipe-separated fields (`title|url|size_mb|password|imdb_id|source_key`). This is the bridge between search results and the `/download/` endpoint.
- Auth: after `add_auth_hook`, every route defaults to browser auth; exceptions are marked with the decorators; `audit_route_auth_modes` raises at startup for unguarded API-prefixed routes; the API key lives in `Config('API')`.
- FlareSolverr: always check `utils.is_flaresolverr_available(shared_state)` first; when a FlareSolverr solution returns a userAgent, update shared_state `user_agent` globally.
- DB tables owned here: `sessions`, `hostname_issues`, `imdb_metadata`, `imdb_searches`, `xem_all_names`, `xem_season_names`, `statistics`.

## Work Guidance

- `log.py` and `auth.py` have import-time side effects (logger init, env reads).
- Circular imports are avoided with lazy imports inside functions — follow that pattern when a module needs storage at import time.
- `obfuscated.py` (2.2MB) and `html_images.py` have extremely long lines — grep them; do not Read whole, do not deobfuscate or regenerate the JS blobs, and never add source hostnames to them.
- New shared service: accept `shared_state` as a parameter (don't import it directly), use constants for timeouts, add a context-emoji entry to `log._context_replace`.
- Failure handling is log-and-return-default rather than raising; exceptions are reserved for programmer errors.

## Verification

- Full unit suite: `uv run python -X utf8 -m unittest discover -s tests`

## Child DOX Index

- `quasarr/providers/sessions/AGENTS.md` — per-source authenticated session contract
- `quasarr/providers/notifications/AGENTS.md` — multi-provider notification subsystem and its extension pattern
