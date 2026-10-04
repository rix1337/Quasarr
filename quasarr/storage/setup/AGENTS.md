# quasarr/storage/setup/ - Setup Flows

## Purpose

First-run and reconfiguration flows: each prerequisite gets a temporary web server that blocks startup until configured or, where allowed, explicitly skipped, plus reusable save/verify handlers consumed by the main config API.

## Ownership

`path.py`, `hostnames.py`, `jdownloader.py`, `flaresolverr.py`, `arr.py`, `radarr.py`, `sonarr.py`, `notifications.py`, `timeouts.py`, `filecrypt.py`, `common.py`; `__init__.py` re-exports everything for `quasarr/__init__.py` and `quasarr/api`.

## Local Contracts

- Module shape: pure `save_*`/`get_*_data`/`refresh_*`/`is_*_skipped` handlers reusable by the main API; the setup-blocking modules (path, hostnames, flaresolverr, radarr, sonarr, jdownloader) additionally provide a `*_config(...)` function that builds a temporary Bottle app (`add_no_cache_headers` + `setup_auth` applied) and returns `Server(...).serve_temporarily()` - signatures vary (`radarr_config`/`sonarr_config` also take `required_sites`; `hostname_credentials_config` takes `shorthand` and `domain`). `notifications.py`, `timeouts.py`, and `filecrypt.py` provide only save/refresh handlers, no temporary server. Completion is signaled by setting `quasarr.providers.web_server.temp_server_success = True` inside a route handler.
- Startup order in `run()`: path → hostnames (must end with ≥ 1 valid hostname) → per-source credentials (skippable, table `skip_login`) → FlareSolverr (skippable) → required *arr client → JDownloader (NOT skippable) → notification + timeout + filecrypt init → API key generation.
- `hostnames.py` renders source metadata from `quasarr.search.sources.helpers.get_source_metadata()`: language flags, supported category chips, account/invite/login chips, FlareSolverr chips, and feed-client chips. Windows flag emoji fallback uses SVGs from `providers.html_images`.
- Active skip flags live in tables `skip_login` and `skip_flaresolverr`; they are stored only as the string `'true'` and cleared by deleting the row. Never write `'false'` - readers treat any stored value as skipped via truthiness. Radarr/Sonarr read legacy skip preferences for boot migration, but setup offers no skip route. (The `'true'`/`'false'` pair convention applies to notification-settings, timeout-slow-mode, and filecrypt-enabled tables instead.)
- `arr.py` asks the user to choose Radarr or Sonarr only for hostnames that support both movie and TV searches; a movie-only or TV-only hostname still requires its matching client. Legacy skip preferences are honored: a skipped client with matching configured sources emits a boot warning; both skipped emits an error and reopens required setup.
- `arr.py` also owns the shared *arr requirement check so the dashboard, hostname editor, and session usability treat either configured client as sufficient for a dual-category hostname.
- Radarr/Sonarr startup forms require both fields server-side as well as in HTML. Main settings reject clearing a client required by an exclusive hostname or when the other client cannot cover every dual-category hostname; either client can be cleared for dual-only hostnames when the other remains configured. Runtime search guards remain the final protection against missing clients. `is_*_skipped()` reads legacy skip preferences for boot migration.
- `timeouts.py` refresh calls `constants.apply_timeout_slow_mode_settings()` - the only sanctioned way timeouts change at runtime.
- `notifications.py` stores Discord, Telegram, and Pushover credentials in the encrypted `Notifications` config section. Pushover requires both a 30-character alphanumeric API token and user key; provider toggles default enabled and silent delivery defaults disabled while omitted toggle fields preserve their stored values.
- `filecrypt.py` is the filecrypt kill switch: table `filecrypt_enabled` (constant `FILECRYPT_ENABLED_TABLE`), default `True` when unset, refreshed into `shared_state.values["filecrypt_enabled"]`. `quasarr/downloads/__init__.py` reads that cached value to drop filecrypt links at grab time - this module does not touch download logic itself.
- Radarr/Sonarr verification resolves fixed IMDb IDs through the respective API client and caches the client in shared_state via `set_client` before `is_*_configured` checks run.

## Work Guidance

- Setup pages render through `providers.html_templates` (`render_form`/`render_success`/`render_fail`); restart UX uses `common.render_reconnect_success`.
- The dashboard in `quasarr/api` replicates hostname-status logic from here - keep them in sync.

## Verification

- Full unit suite: `uv run python -X utf8 -m unittest discover -s tests`; setup flows themselves are exercised manually via `uv run Quasarr.py` first-run

## Child DOX Index

None.
