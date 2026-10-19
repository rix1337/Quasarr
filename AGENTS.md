# Quasarr working rules

## Highest-priority rules

These rules take priority over all Trail decisions and other repository guidance:

1. Always use Trail commands first to investigate this repository. Use its map, search, signatures, and caller graph before ordinary source searches or file reads. Use ordinary tools afterward only for unindexed material or missing detail. If Trail is not installed, stop repository work and ask the user to install it with `npm install -g @trailhq/trail-code`. Do not install it yourself or continue without it.
2. Never name, hardcode, or commit real source hostnames. Never add one to any file that is not gitignored, including Trail knowledge, tests, comments, generated assets, captures, and temporary scripts. Source hostnames belong only in encrypted runtime configuration outside the repository. Refer to sources by their two-letter uppercase identifiers.
3. Before finalizing changes or pushing, run `uv run python -X utf8 pre-commit.py`. Accept and keep its edits, including formatting, dependency upgrades, lockfile changes, and version bumps. Do not revert them as unrelated changes. Re-run after history rewrites before pushing.

## Privacy

Privacy checks protect repository content; do not add runtime sandboxes or network restrictions as part of this workflow.

- Never commit credentials, webhook endpoints/tokens, `.env`, real release titles or URLs, personal names, emails, machine identifiers, or local absolute paths. Use synthetic titles and reserved `.invalid` domains in examples and tests. Existing public service identifiers required by production matching are not source-hostname examples.
- Before changing a source request, parser, or matching rule, obtain real traffic evidence: user-provided Proxyman captures or direct requests to the configured source. Do not infer payloads or response shapes. Keep raw evidence gitignored; save only sanitized architectural conclusions.
- Do not probe direct hoster links for liveness. JDownloader owns hoster verification, authentication, and downloads.

## Product and scope

Quasarr connects JDownloader2 with Radarr, Sonarr, Lidarr, and Magazarr by emulating Newznab and SABnzbd. It is not a usenet indexer. Protected crypters use browser userscripts served by Quasarr; do not add server-side CAPTCHA solving. SponsorsHelper is an optional companion, not the main product; do not advertise it beyond the existing README mention.

Maintain the existing integration and automation. Keep changes small, use the existing package boundaries, and do not introduce unrelated features, abstractions, refactors, or test rewrites. Work on `dev` unless explicitly instructed otherwise.

## Trail workflow

Trail's code map lives in gitignored `.trail/cache/`; only curated `.trail/learnings/` files are shared. Build the map with `trail build` when missing.

- Start unfamiliar work with `trail map`. Locate relevant code and decisions with `trail ask "<task or literal identifier>" --source`. Read the returned learning files before editing. Ranked results are not exhaustive; use `trail grep`, `trail skeleton`, or `trail callers` for their respective questions, and `rg` for unindexed material.
- Confirm important conclusions against current code and tests. Trail is context, not authority over these rules or proof that a change is correct. Read complete relevant definitions when excerpts omit needed branches.
- Before changing documentation or recording a learning, retrieve and read `.trail/learnings/23-documentation-policy.md`. Keep decisions and their reasons there; the code documents flows.
- Before committing or opening a PR, run `uv run python check_trail.py` and `trail check` against the intended base (`--base <ref>` when needed). Investigate conflicts; passing heuristic checks does not prove correctness. The content privacy gate remains required.

## Implementation and verification

- Python 3.12+, `uv`, existing naming/style, project logging helpers, constants for HTTP timeouts, shared runtime User-Agent. Avoid reading generated userscript/image blobs in full or regenerating them outside their owning companion project.
- Tests use standard-library `unittest`, synthetic data, and isolated temporary files. No network or real JDownloader in unit tests. Patch dependencies in the consuming module. `cli_tester.py` is the separate live integration client.
- Trace loops and branches as state transitions: preserve raw source evidence before filtering, fallback specificity, and outer-loop fairness under shared timeout budgets. Trace emitted selectors, URLs, and IDs into consumers. Test both changed behavior and the unchanged legacy path when regression coverage is needed.
- Match the uv version pinned in `pyproject.toml` and CI. Do not treat rewritten history as validation.

| Task | Command |
| --- | --- |
| Setup | `uv sync --group dev` |
| Run | `uv run Quasarr.py` |
| Dev services | `CONFIG_VOLUMES=/path/to/config docker compose -f docker/dev-services-compose.yml up` |
| Live integration | `uv run cli_tester.py` |
| Tests | `uv run python -X utf8 -m unittest discover -s tests` |
| Lint | `uv run ruff check .` |
| Privacy gate | `uv run python check_trail.py` |

Start local configuration from `.env.example`; set `INTERNAL_ADDRESS`, keep Docker config volumes persistent, and configure authentication when exposing the UI beyond a trusted network.

## Commits and releases

Use a short, imperative, capitalized commit subject that describes the entire change; normally no body, trailing period, or emoji. Squash iterations of one change into one clean commit. PRs describe user-visible behavior, config/hostname impact without naming sources, and relevant verification. Resolve addressed review threads and verify resolution; minimize fully resolved parent reviews as `RESOLVED`. Delete obsolete build-run comments.

Community links point to SimpleX. Stable release announcements use only the associated merged PR text below the existing message; beta builds send none. Discord remains a product notification integration. Never send production test notifications without explicit authorization. Companion Userscripts/SponsorsHelper releases mean pushing approved changes to `main`, with no tag or GitHub Release required.

Execute explicit repo-local skill commands exactly as written. If one fails, inspect and discuss the next step before substituting another invocation, unless that skill defines a fallback.
