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
- `imdb_metadata.py` / `xem_metadata.py` — cached metadata chains: IMDb IDs resolve basic title/year/poster and title searches through the local Radarr or Sonarr client; localized titles use locale-specific IMDb release-info HTML and preserve that cache across Arr refreshes; German localized titles are transliterated once at this provider boundary for every source; TheXEM supplies season names
- `radarr_api.py` / `sonarr_api.py` — minimal clients cached in shared_state via `set_client`/`get_client`; IMDb and free-title lookup, IMDb→TMDB/TVDB resolution (`get_tmdb_id`/`get_tvdb_id`), plus library-feed seeds `get_wanted_imdb_ids` / `get_wanted_episodes` (wanted = missing + cutoff-unmet, missing first, capped at the passed `limit`, paging past filtered entries; the movie helper skips not-yet-released titles and the episode helper skips not-yet-aired ones). All return safe empties when the client is unconfigured.
- `statistics.py` — DB-backed counters, constructed inline at call sites
- `version.py` — `__version__`, the single source of version truth
- `obfuscated.py` — generated obfuscated userscripts, document-start browser guards, and captcha-service endpoint values; consumed by `api/captcha` and `cloudflare.py`
- `cloudflare.py` — challenge detection, thread-safe process-local 24-hour per-netloc FlareSolverr gating, lazy per-operation browser sessions, response wrappers, and get/post/session helpers
- `html_templates.py` / `html_images.py` — UI page shell, base64 image constants, and language-flag emoji/SVG fallback assets for setup UI
- `hostname_issues.py` — DB-backed source health tracker (`mark_/clear_/get_hostname_issue`)
- `utils.py` — grab-bag: payload generate/parse, category resolvers, title matching (including shared date-numbering parsing/query/match/canonicalization), online-status checks, `download_package` (the JD linkgrabber submission)
- `sessions/` and `notifications/` — see Child DOX Index

## Local Contracts

- Each process calls `shared_state.set_state(dict, lock)` before use; read `shared_state.values[key]`, write `shared_state.update(key, value)`. `values["config"]`/`["database"]` hold the classes, not instances.
- All JDownloader access goes through `shared_state.get_device()` (blocks and retries forever with escalating backoff) or `run_device_request(name, fn, default)` (one reconnect+retry then the default on JD request errors — but its first attempt calls `get_device()` internally, so it too blocks until a device is connected). `TokenExpiredException`/`RequestTimeoutException`/`MYJDException` from `myjd_api` are the canonical JD error set.
- `generate_download_link` and `parse_payload` must stay in sync: urlsafe-base64 of exactly 6 pipe-separated fields (`title|url|size_mb|password|imdb_id|source_key`). This is the bridge between search results and the `/download/` endpoint.
- Auth: after `add_auth_hook`, every route defaults to browser auth; exceptions are marked with the decorators; `audit_route_auth_modes` raises at startup for unguarded API-prefixed routes; the API key lives in `Config('API')`.
- FlareSolverr: always check `utils.is_flaresolverr_available(shared_state)` first; when a FlareSolverr solution returns a userAgent, update shared_state `user_agent` globally.
- Optional Cloudflare fallback uses `LazyFlareSolverrSession`: an uncached netloc tries plain HTTP first; a real 403 or recognized challenge gates that netloc process-locally for 24 hours, after which same-host requests skip plain HTTP and go directly through FlareSolverr until the monotonic TTL expires. Gate access is thread-safe, first detection logs once at DEBUG, and cached requests stay quiet. Browser sessions remain lazy, are reused within one search/feed/download operation, receive at least the standard session timeout budget even when the plain request has a shorter search budget, and close from an outer `finally`. FileCrypt targets and browser-based redirect resolution carry the FileCrypt document-start clickjacking blocker and require flaresolverr-next to acknowledge it with `solution.documentStartJsResult == "installed"`; unsupported solver images fail closed only on those paths. Solved JSON endpoints may arrive inside a browser-rendered `<pre>` wrapper, which `FlareSolverrResponse.json()` unwraps.
- IMDb metadata must not depend on an unofficial metadata API or GraphQL. Basic metadata comes from local Arr lookup responses. A localized title is guaranteed by accepting an Arr alternate title with an explicit matching ISO language code, a country-matched AKA row from IMDb release-info HTML or embedded page data, or IMDb `titleText` only when embedded request context proves the requested language, full localization, and disabled original-title preference. Unproven `titleText` and Arr base titles are not localized-title fallbacks. If no authoritative localized source exists, the lookup logs an error and returns no title. The cache preserves sanitized localized metadata, while `get_localized_title` returns one source-facing form: German umlauts and sharp S are transliterated on every successful return path, so individual sources must not add retries for spelling variants. Movie categories resolve stale or missing base metadata only through Radarr; TV categories resolve it only through Sonarr.
- DB tables owned here: `sessions`, `hostname_issues`, `imdb_metadata`, `imdb_searches`, `xem_all_names`, `xem_season_names`, `statistics`.
- `utils.is_site_usable()` shares setup's *arr requirement check: a dual-category hostname needs either cached client; a movie-only or TV-only hostname needs its matching client.

## Work Guidance

- `log.py` and `auth.py` have import-time side effects (logger init, env reads).
- Circular imports are avoided with lazy imports inside functions — follow that pattern when a module needs storage at import time.
- `obfuscated.py` (2.2MB) and `html_images.py` have extremely long lines — grep them and do not Read whole or deobfuscate the JS blobs. Regenerate `obfuscated.py` only through the private Quasarr-UserScripts generator, and never add source hostnames to it.
- New shared service: accept `shared_state` as a parameter (don't import it directly), use constants for timeouts, add a context-emoji entry to `log._context_replace`.
- Failure handling is log-and-return-default rather than raising; exceptions are reserved for programmer errors.

## Verification

- Full unit suite: `uv run python -X utf8 -m unittest discover -s tests`

## Child DOX Index

- `quasarr/providers/sessions/AGENTS.md` — per-source authenticated session contract
- `quasarr/providers/notifications/AGENTS.md` — multi-provider notification subsystem and its extension pattern
