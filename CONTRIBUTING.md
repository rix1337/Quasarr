# Development Setup for Pull Requests

To test your changes before submitting a pull request:

**1. Prepare your Environment with `uv`**

Ensure you have the development tools (like `ruff`) installed and your environment synced:

Use the uv version specified by `required-version` in `pyproject.toml` (currently `0.11.3`). CI uses the same version to keep lockfile output consistent.

```bash
uv sync --group dev
```

Install the pre-commit hook that ensures linting, formatting and version upgrades through pre-commit.py

```bash
uv run pre-commit install
```

**2. Run Quasarr**

```bash
uv run Quasarr.py
```

**3. Start the required services using the `dev-services-compose.yml` file**

```bash
CONFIG_VOLUMES=/path/to/config docker-compose -f docker/dev-services-compose.yml up
```

Replace `/path/to/config` with your desired configuration location.
The `CONFIG_VOLUMES` environment variable is **mandatory**.

By default, only JDownloader and flaresolverr-next are enabled. See next step how to emulate supported *arr services.

**4. Validate your changes**

Use the `cli_tester.py` script to simulate Radarr, Sonarr, and Magazarr interactions.

```bash
uv run cli_tester.py
```

This tool allows you to test searches, feeds, and downloads without needing the full stack of services running.

---

### Code Quality & Maintenance

The CI pipeline enforces strict code styling and import optimization. Please run this commands before pushing your
changes. Alternatively, set up the pre-commit hook as described above.

**Format code, upgrade dependencies, run tests and bump the version:**

```bash
uv run pre-commit.py
```

Dependencies are upgraded automatically on every run.

After CI pushes auto-fixes, it dispatches a read-only follow-up to validate and build that commit without repeating the dependency upgrade.
