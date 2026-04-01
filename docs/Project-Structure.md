# Project Structure

The main application code lives in `quasarr/`.

- `quasarr/api/`: HTTP endpoints consumed by Quasarr clients and the web UI
- `quasarr/downloads/`: download submission, package handling, and mirror filtering
- `quasarr/search/`: search behavior and hostname integrations
- `quasarr/providers/`: shared services such as logging, notifications, sessions, metadata, and the web server
- `quasarr/storage/`: configuration, setup flows, categories, and SQLite-backed state
- `tests/`: targeted `unittest` coverage
- `docker/`: Dockerfile plus runtime and development compose files

Root entrypoints:

- `Quasarr.py`: launches Quasarr from source
- `cli_tester.py`: simulates Radarr, Sonarr, and LazyLibrarian flows
- `pre-commit.py`: repository maintenance and formatting workflow

When adding code, keep it near the feature boundary that already exists. Hostname-specific logic belongs with the existing source modules and helpers rather than in shared glue code.

When adding a new source integration, use the same two-letter module key under both `quasarr/search/sources/` and `quasarr/downloads/sources/` whenever release links need source-specific extraction.

