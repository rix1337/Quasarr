# quasarr/storage/setup/ — Setup Flows

## Purpose

First-run and reconfiguration flows: each prerequisite gets a temporary web server that blocks startup until configured or explicitly skipped, plus reusable save/verify handlers consumed by the main config API.

## Ownership

`path.py`, `hostnames.py`, `jdownloader.py`, `flaresolverr.py`, `radarr.py`, `sonarr.py`, `notifications.py`, `timeouts.py`, `common.py`; `__init__.py` re-exports everything for `quasarr/__init__.py` and `quasarr/api`.

## Local Contracts

- Module shape: pure `save_*`/`get_*_data`/`refresh_*`/`is_*_skipped` handlers reusable by the main API; the setup-blocking modules (path, hostnames, flaresolverr, radarr, sonarr, jdownloader) additionally provide a `*_config(...)` function that builds a temporary Bottle app (`add_no_cache_headers` + `setup_auth` applied) and returns `Server(...).serve_temporarily()` — signatures vary (`radarr_config`/`sonarr_config` also take `required_sites`; `hostname_credentials_config` takes `shorthand` and `domain`). `notifications.py` and `timeouts.py` provide only save/refresh handlers, no temporary server. Completion is signaled by setting `quasarr.providers.web_server.temp_server_success = True` inside a route handler.
- Startup order in `run()`: path → hostnames (must end with ≥ 1 valid hostname) → per-source credentials (skippable, table `skip_login`) → FlareSolverr (skippable) → Radarr/Sonarr (only when a configured source requires them, skippable) → JDownloader (NOT skippable) → notification + timeout init → API key generation.
- `hostnames.py` renders source metadata from `quasarr.search.sources.helpers.get_source_metadata()`: language flags, supported category chips, account/invite/login chips, FlareSolverr chips, and feed-client chips. Windows flag emoji fallback uses SVGs from `providers.html_images`.
- Skip flags live in tables `skip_login`, `skip_flaresolverr`, `skip_radarr`, `skip_sonarr`; they are stored only as the string `'true'` and cleared by deleting the row. Never write `'false'` — readers treat any stored value as skipped via truthiness. (The `'true'`/`'false'` pair convention applies to the notification-settings and timeout-slow-mode tables instead.)
- `timeouts.py` refresh calls `constants.apply_timeout_slow_mode_settings()` — the only sanctioned way timeouts change at runtime.
- Radarr/Sonarr verification resolves fixed IMDb IDs through the respective API client and caches the client in shared_state via `set_client` before `is_*_configured` checks run.

## Work Guidance

- Setup pages render through `providers.html_templates` (`render_form`/`render_success`/`render_fail`); restart UX uses `common.render_reconnect_success`.
- The dashboard in `quasarr/api` replicates hostname-status logic from here — keep them in sync.

## Verification

- Full unit suite: `uv run python -X utf8 -m unittest discover -s tests`; setup flows themselves are exercised manually via `uv run Quasarr.py` first-run

## Child DOX Index

None.
