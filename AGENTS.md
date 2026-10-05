# Repository Guidelines

## Project Overview

Quasarr connects JDownloader2 with Radarr, Sonarr, Lidarr, and Magazarr. It also handles links protected by CAPTCHAs: protected crypters are solved in the user's browser via Tampermonkey userscripts served by the Quasarr Web UI - Quasarr performs no server-side CAPTCHA solving. The primary audience is users who want to run the *arr stack with JDownloader2 instead of a traditional usenet downloader while automating as much of the flow as possible.

Quasarr acts as the bridge between the *arr apps and JDownloader2 by exposing itself as both a `Newznab Indexer` and a `SABnzbd client`. It is not a real usenet indexer, does not know what NZB files are, and should not be treated as one.

## Instruction File: AGENTS.md Is Canonical

The AGENTS.md hierarchy - this root file plus the child AGENTS.md files indexed under `# DOX framework` below - is the single source of truth for agent instructions and documentation in this repository. `CLAUDE.md` exists only as a pointer file containing the literal text `@AGENTS.md`, which lets Claude-based toolchains load these instructions through their normal discovery mechanism.

The root `README.md` is meant to introduce the Quasarr project to users. It is not a working reference for agents and should be ignored for planning and implementation unless the task explicitly asks for changes to `README.md` or asks about its content. The root `CONTRIBUTING.md` is the GitHub-facing contributor setup guide; keep it in sync when commands in the Development Workflow section change.

Under no circumstances modify `CLAUDE.md`. Do not add content to it, do not duplicate `AGENTS.md` into it, and do not "fix" it back to byte-parity with `AGENTS.md`. Any change to agent instructions goes into `AGENTS.md` only. If `CLAUDE.md` ever contains anything other than the single line `@AGENTS.md`, restore it to that single line.

## Core Capabilities

Treat these as the first-class product goals:

- Connecting the *arr stack with JDownloader2
- Autonomously controlling JDownloader2 to support that integration
- Handling protected links via the standardized userscript CAPTCHA flow so the workflow is as automated as possible
- Supporting related filtering, categorization, and notifications only when they strengthen the core automation flow

`SponsorsHelper` is an optional premium companion for enhanced anti-CAPTCHA automation. It is not the main product and should not be actively advertised beyond a mention in `README.md`.

## Product Boundaries

The project focus is improving and maintaining the existing feature set. Automation for third-party tools and sources is effectively endless, so features outside the core capabilities are usually feature creep or bloat that steal time from maintaining compatibility with those third parties.

Do not propose or implement broad new abstractions, adjacent product ideas, or convenience features unless they directly support the core Quasarr workflow.

## Change Discipline

Keep changes aligned with the existing `quasarr/` package layout, prefer `uv` for local commands, and run the documented checks before submitting work. Keep commit subjects short and imperative, keep pull requests focused, and avoid bundling unrelated edits.

Work on the `dev` branch for repository changes unless the user explicitly requests another branch.

Do not change more code than necessary. Refactors should be proposed and explicitly requested, not performed opportunistically. Keep commit deltas low and avoid creating refactor overhead such as rewriting unrelated tests.

Unit tests should usually change only when the intended behavior in the covered area changed, or when the existing test is incorrect. Do not rewrite tests just because nearby code changed shape.

## Development Workflow

Develop from a source checkout; `uv tool install quasarr` is for end users only.

- Setup: `uv sync --group dev` (add `--group build` only when build artifacts are needed)
- Create a local `.env` from `.env.example`; set at least `INTERNAL_ADDRESS` (`EXTERNAL_ADDRESS`, `USER`, `PASS`, `AUTH`, and `TZ` are optional but commonly used locally). On first start Quasarr writes `Quasarr.conf` to store the config path.
- Run from source: `uv run Quasarr.py`
- Dev services (JDownloader + flaresolverr-next): `CONFIG_VOLUMES=/path/to/config docker compose -f docker/dev-services-compose.yml up` - `CONFIG_VOLUMES` is mandatory; legacy installations can use `docker-compose -f ...` instead
- Simulate Radarr/Sonarr/Lidarr/Magazarr against a running instance: `uv run cli_tester.py` (preferred over standing up a full *arr stack)
- Unit tests: `uv run python -X utf8 -m unittest discover -s tests`
- Lint: `uv run ruff check .`
- Before a PR: `uv run python -X utf8 pre-commit.py` (lint + format + dependency upgrade + tests + version bump); install the git hook with `uv run pre-commit install`. Dependencies are upgraded automatically on every run.

CI enforces the same gate via `uv run pre-commit.py --ci` in `PullRequests.yml`; `Release.yml` runs no lint or test step.

## Commits And Pull Requests

Match the dominant history pattern: a single-line, imperative, capitalized subject with no body - short enough to scan, broad enough to summarize the whole change (do not undersell a multi-file change by naming one small part). No trailing period, no contributor emoji (automated tooling may add one); a trailing `(#123)` reference is fine. Optional prefixes seen in history: `chore:` for maintenance (still describe the main work after the prefix), `chore(deps):` for dependency-only updates, `fix:` (plain `Fix ...` is equally fine - pick one style and keep the subject specific), `refactor:` only for genuine no-behavior-change refactors.

Add a body only when the subject genuinely cannot carry the change: list only the defining changes in short concrete bullets, and explain why only when it is not obvious from the diff. The PR description, not the commit body, carries the user-visible summary and test plan.

Pull requests must describe the user-visible change, call out any config or hostname impact, and avoid mixing unrelated cleanup with functional work. Include proof of behavior (screenshots, logs, or a brief reproduction) for UI or integration changes. Coordinate on [SimpleX](https://smp14.simplex.im/c#huQ65mF5BdP6HJ7wCfByVkwy6w2zghW3WF-YLK8O5wc) before starting large new features.

After addressing PR review feedback, resolve the corresponding GitHub review parent thread and verify that it reads back as resolved so addressed comments no longer remain visible as unresolved.

Before requesting automated PR review, inspect changed loops and branches as state transitions, especially where parsing or filtering can erase raw source state or where nested loops share timeout budgets. Verify outer-loop fairness as well as inner-loop stopping behavior; do not truncate fallback-candidate lists without evidence that later candidates are redundant. Trace emitted URLs, selectors, and identifiers into their downstream consumers so missing specificity cannot widen the consumer's scope. Read test assertions as behavior contracts rather than trusting test names. Add paired regression coverage for both the new behavior and the unchanged legacy path.

## Skill Execution

When a repo-local skill defines an explicit command, execute that command exactly as written unless the skill itself explicitly allows an alternative invocation.

Do not substitute a different shell, interpreter, wrapper, or platform-specific entrypoint just because it appears equivalent. If a local alias or shim is useful for one machine, keep that in user-specific agent configuration outside the repository.

If a skill command fails, inspect why it failed and discuss the best next step with the user before retrying with a different invocation, unless the skill itself defines a fallback.

## Security And Content Rules

Do not commit real credentials, `.env` files, API keys, or actual source hostnames. Never, at any point, add the hostnames of any sources Quasarr supports to any file that is not gitignored.

Runtime configuration rules:

- Treat configuration as sensitive - webhook URLs and tokens count as credentials; start local setup from `.env.example`.
- Source hostnames are always configured by the user at runtime (web UI or hostname import) and live AES-encrypted in the runtime config outside the repository.
- `INTERNAL_ADDRESS` must be valid for local development and Docker runs. Set `EXTERNAL_ADDRESS`, `USER`, `PASS`, and `AUTH` when exposing the UI beyond a trusted local network.
- Keep Docker config volumes persistent so generated state survives restarts.

## Third-Party Source Work

Do not infer payloads, URLs, titles, or response shapes when working on a third-party source. Before changing how a source is requested, parsed, or matched, ask the user for clear Proxyman (or similar) captures of real traffic. Curling the source directly to confirm the actual shape of a request or response is a valid alternative when the user has not already supplied a capture.

When a source's code is not available locally, any examples used in AGENTS.md files, code comments, or tests must use synthetic names and invalid URLs. Never paste real release titles, hostnames, or release URLs into the repository to illustrate behavior. The only exceptions are sources that are themselves open-source projects with code available locally; those may be referenced using their actual identifiers.

## Terminology

When referring to integrations such as `NK` or `DW`, always call them `sources`.

Always abbreviate sources as two-letter uppercase identifiers, for example `NK`, `DW`, `DD`, or `SJ`.

# DOX framework

- DOX is highly performant AGENTS.md hierarchy installed here
- Agent must follow DOX instructions across any edits

## Core Contract

- AGENTS.md files are binding work contracts for their subtrees
- Work products, source materials, instructions, records, assets, and durable docs must stay understandable from the nearest applicable AGENTS.md plus every parent AGENTS.md above it

## Read Before Editing

1. Read the root AGENTS.md
2. Identify every file or folder you expect to touch
3. Walk from the repository root to each target path
4. Read every AGENTS.md found along each route
5. If a parent AGENTS.md lists a child AGENTS.md whose scope contains the path, read that child and continue from there
6. Use the nearest AGENTS.md as the local contract and parent docs for repo-wide rules
7. If docs conflict, the closer doc controls local work details, but no child doc may weaken DOX

Do not rely on memory. Re-read the applicable DOX chain in the current session before editing.

## Update After Editing

Every meaningful change requires a DOX pass before the task is done.

Update the closest owning AGENTS.md when a change affects:

- purpose, scope, ownership, or responsibilities
- durable structure, contracts, workflows, or operating rules
- required inputs, outputs, permissions, constraints, side effects, or artifacts
- user preferences about behavior, communication, process, organization, or quality
- AGENTS.md creation, deletion, move, rename, or index contents

Update parent docs when parent-level structure, ownership, workflow, or child index changes. Update child docs when parent changes alter local rules. Remove stale or contradictory text immediately. Small edits that do not change behavior or contracts may leave docs unchanged, but the DOX pass still must happen.

## Hierarchy

- Root AGENTS.md is the DOX rail: project-wide instructions, global preferences, durable workflow rules, and the top-level Child DOX Index
- Child AGENTS.md files own domain-specific instructions and their own Child DOX Index
- Each parent explains what its direct children cover and what stays owned by the parent
- The closer a doc is to the work, the more specific and practical it must be

## Child Doc Shape

- Create a child AGENTS.md when a folder becomes a durable boundary with its own purpose, rules, responsibilities, workflow, materials, or quality standards
- Work Guidance must reflect the current standards of the project or user instructions; if there are no specific standards or instructions yet, leave it empty
- Verification must reflect an existing check; if no verification framework exists yet, leave it empty and update it when one exists

Default section order:
- Purpose
- Ownership
- Local Contracts
- Work Guidance
- Verification
- Child DOX Index

## Style

- Keep docs concise, current, and operational
- Document stable contracts, not diary entries
- Put broad rules in parent docs and concrete details in child docs
- Prefer direct bullets with explicit names
- Do not duplicate rules across many files unless each scope needs a local version
- Delete stale notes instead of explaining history
- Trim obvious statements, repeated rules, misplaced detail, and warnings for risks that no longer exist

## Closeout

1. Re-check changed paths against the DOX chain
2. Update nearest owning docs and any affected parents or children
3. Refresh every affected Child DOX Index
4. Remove stale or contradictory text
5. Run existing verification when relevant
6. Report any docs intentionally left unchanged and why

## User Preferences

When the user requests a durable behavior change, record it here or in the relevant child AGENTS.md

- Community links point to SimpleX; release workflows do not post to Discord. Discord webhook notifications remain a supported integration.

## Child DOX Index

- `quasarr/AGENTS.md` - application package: layout, entrypoint and constants contracts, cross-cutting Python conventions; indexes the five subsystem docs (`api/`, `downloads/`, `search/`, `providers/`, `storage/`)
- `tests/AGENTS.md` - unit-test suite: unittest-only contract, hermetic mocking rules, synthetic-hostname rules, exact run command
- `docker/AGENTS.md` - container build and compose assets: restart-loop ENTRYPOINT contract, end-user and dev compose files
