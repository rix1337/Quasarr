# Documentation Index

Start here before planning or editing code. This file is the overview of the documentation set and tells you which document to read next for a given task.

## Available Documents

### [Development](Development.md)

Read this for local setup, `uv` commands, running Quasarr from source, starting Docker-backed development services, CLI simulation, linting, and the standard maintenance workflow.

### [Project Structure](Project-Structure.md)

Read this when deciding where new code belongs. It summarizes the `quasarr/` package layout, root entrypoints, test location, Docker assets, and the intended placement of feature-specific logic.

### [Coding Style](Coding-Style.md)

Read this before editing Python code. It covers naming, file layout, shared-helper expectations, and the Ruff-based style and linting workflow used by the repository.

### [Testing](Testing.md)

Read this when adding or updating tests. It explains the `unittest` conventions, test naming, mocking expectations, and when to use `cli_tester.py` versus the unit suite.

### [Contributing](Contributing.md)

Read this when preparing commits or pull requests. It documents the preferred commit subject style, PR expectations, and the rule to keep changes focused and easy to review.

### [Security](Security.md)

Read this for rules around `.env` handling, credentials, tokens, runtime configuration, and the strict rule that source hostnames must never be committed to tracked files.

### [Mirror Selection](Mirror-Selection.md)

Read this before changing how a download source picks between multiple mirrors or link sets. It defines the selection priority (crypter online signal, then newest mirror, then first/arbitrary), the hard rule that Quasarr never probes direct-link liveness (that is JDownloader's job), and why the policy is deliberately not changed.

### [Sources](sources/README.md)

Read this when working on a specific source integration. The `sources/` folder contains per-source documentation covering API behavior, supported categories, hostname setup, and source-specific details.

If a change introduces a new workflow or convention, update the relevant file here in the same change.
