# tests/ — Unit Test Suite

## Purpose

Hermetic unit tests for Quasarr, built exclusively on the standard-library `unittest` framework. Covers download-link extraction, search-source behavior, the filecrypt CAPTCHA/PoW flows, mirror filtering, download orchestration, notifications, SponsorsHelper helpers, release matching, and the SQLite layer.

## Ownership

`test_*.py` files in this folder. `cli_tester.py` at the repo root is NOT part of this suite — it is a separate interactive/scriptable end-to-end client that exercises a RUNNING Quasarr instance over real HTTP against real configured sources; never confuse the two.

## Local Contracts

- Framework: stdlib `unittest` only — no pytest, no conftest, no coverage tooling, no test config in `pyproject.toml`. Classes are `<Subject>Tests(unittest.TestCase)`, files `test_*.py`, methods `test_*`, each file ends with an `if __name__ == "__main__": unittest.main()` block.
- Full-suite command: `uv run python -X utf8 -m unittest discover -s tests` (the `-X utf8` flag avoids Windows console encoding noise in log output).
- Tests must not perform network I/O or touch JDownloader. Patch in the consuming module's namespace (e.g. `quasarr.downloads.sources.<xx>.requests.Session`), not the `requests` library globally. Only `test_sqlite_database.py` touches disk, via `tempfile.TemporaryDirectory`.
- Synthetic-data rule (security-critical): source hostnames in tests are fake domains on the reserved `.invalid` TLD; use synthetic release titles (never paste real ones). Real public hoster/crypter domains are permitted only where the production matching logic keys on those literal domains — they are hoster/crypter services, not protected sources.
- Date-numbering regression tests may name a motivating real series to prove title-alias compatibility, but every complete release string, date, quality/group suffix, hostname, and URL remains synthetic.
- `shared_state` is always faked (MagicMock with a `.values` dict, SimpleNamespace, or a small local class whose `values["config"]` is a callable returning dicts) — except `test_sqlite_database.py`, which mutates the real module in `setUp`.
- There is no fixtures directory and no shared test-helpers module: each file defines its own `FakeResponse`/`FakeSession`/fake shared_state inline.
- Run the full suite after touching shared providers, download flow, search behavior, or notification logic. Per root change discipline, tests change only when the intended behavior in the covered area changed or the existing test is incorrect.

## Work Guidance

- Parameterized cases use `self.subTest(...)`; many simultaneous patches use `contextlib.ExitStack` or the parenthesized multi-context `with` form.
- Tests may reach into private underscore-prefixed helpers freely.
- Document behavioral intent with comments inside tests — explain WHY a rule/ordering exists (see `test_wx_direct_links.py`).
- Prefer exact-equality assertions on whole result shapes and on recorded request sequences.

## Verification

- `uv run python -X utf8 -m unittest discover -s tests`

## Child DOX Index

None.
