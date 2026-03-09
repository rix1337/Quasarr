# Testing

Quasarr uses the standard library `unittest` framework for automated tests.

## Test Layout

- Put tests in `tests/`.
- Name files `test_*.py`.
- Name test methods `test_*`.
- Prefer focused unit tests with mocks around network calls, JDownloader interactions, and external integrations.

## Commands

Run the full test suite with:

```bash
uv run python -X utf8 -m unittest discover -s tests
```

The `-X utf8` flag avoids noisy Windows console encoding issues in log output.

For broader behavior checks without standing up Radarr, Sonarr, or LazyLibrarian, use:

```bash
uv run cli_tester.py
```

Run the full unit suite after touching shared providers, download flow, search behavior, or notification logic.
