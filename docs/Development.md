# Development

Work from a source checkout for local development; `uv tool install quasarr` is for end users.

## Setup

Install the application and developer tooling:

```bash
uv sync --group dev
```

Install packaging tools as well when you need build artifacts:

```bash
uv sync --group dev --group build
```

Create a local `.env` from `.env.example` and set at least `INTERNAL_ADDRESS`. `EXTERNAL_ADDRESS`, `USER`, `PASS`, `AUTH`, and `TZ` are optional but commonly used during local runs. On first start, Quasarr also writes `Quasarr.conf` to store the config path.

## Run From Source

```bash
uv run Quasarr.py
```

The first run guides you through hostname, JDownloader, and optional FlareSolverr setup.

## Development Services

Start the supporting services with:

```bash
CONFIG_VOLUMES=/path/to/config docker compose -f docker/dev-services-compose.yml up
```

`docker-compose -f docker/dev-services-compose.yml up` also works on legacy Docker installations. `CONFIG_VOLUMES` is required. The compose file enables JDownloader and FlareSolverr by default; the `radarr`, `sonarr`, `lidarr`, `lazylibrarian`, and `sponsorshelper` services are provided as commented examples.

For most integration checks, use the CLI simulator instead of a full *arr stack:

```bash
uv run cli_tester.py
```

## Validation

Run the unit tests:

```bash
uv run python -X utf8 -m unittest discover -s tests
```

Run linting:

```bash
uv run ruff check .
```

Run the repository maintenance workflow:

```bash
uv run python -X utf8 pre-commit.py
uv run pre-commit install
```

Use `uv run python -X utf8 pre-commit.py --upgrade` when intentionally refreshing pinned dependencies.
