# Repository Guidelines

## Project Overview

Quasarr connects JDownloader2 with Radarr, Sonarr, Lidarr, and LazyLibrarian. It also decrypts links protected by CAPTCHAs. The primary audience is users who want to run the *arr stack with JDownloader2 instead of a traditional usenet downloader while automating as much of the flow as possible.

Quasarr acts as the bridge between the *arr apps and JDownloader2 by exposing itself as both a `Newznab Indexer` and a `SABnzbd client`. It is not a real usenet indexer, does not know what NZB files are, and should not be treated as one.

## Documentation First

Before formulating a plan or implementing a change, start with `docs/README.md`. It is the index for the documentation set and explains which documents exist and what each one covers.

The root `README.md` is meant to introduce the Quasarr project to users. It is not the primary working reference for agents and should be ignored for planning and implementation unless the task explicitly asks for changes to `README.md` or asks about its content.

After checking `docs/README.md`, open the file in `docs/` that matches the task and use it as the source of truth. If the task spans multiple areas, read each relevant document first.

Any major change to Quasarr must include the corresponding documentation updates described in this section. If the change affects behavior, workflows, conventions, architecture, or contributor expectations, update the matching file in `docs/`. If no document matches the topic, create or update one as part of the change before finalizing the work.

## Core Capabilities

Treat these as the first-class product goals:

- Connecting the *arr stack with JDownloader2
- Autonomously controlling JDownloader2 to support that integration
- Handling protected-link and anti-CAPTCHA mechanics so the workflow is as automated as possible
- Supporting related filtering, categorization, and notifications only when they strengthen the core automation flow

`SponsorsHelper` is an optional premium companion for enhanced anti-CAPTCHA automation. It is not the main product and should not be actively advertised beyond a mention in `README.md`.

## Product Boundaries

The project focus is improving and maintaining the existing feature set. Automation for third-party tools and sources is effectively endless, so features outside the core capabilities are usually feature creep or bloat that steal time from maintaining compatibility with those third parties.

Do not propose or implement broad new abstractions, adjacent product ideas, or convenience features unless they directly support the core Quasarr workflow.

## Change Discipline

Keep changes aligned with the existing `quasarr/` package layout, prefer `uv` for local commands, and run the documented checks before submitting work. Keep commit subjects short and imperative, keep pull requests focused, and avoid bundling unrelated edits.

Do not change more code than necessary. Refactors should be proposed and explicitly requested, not performed opportunistically. Keep commit deltas low and avoid creating refactor overhead such as rewriting unrelated tests.

Unit tests should usually change only when the intended behavior in the covered area changed, or when the existing test is incorrect. Do not rewrite tests just because nearby code changed shape.

## Skill Execution

When a repo-local skill defines an explicit command, execute that command exactly as written unless the skill itself explicitly allows an alternative invocation.

Do not substitute a different shell, interpreter, wrapper, or platform-specific entrypoint just because it appears equivalent. If a local alias or shim is useful for one machine, keep that in user-specific agent configuration outside the repository.

If a skill command fails, inspect why it failed and discuss the best next step with the user before retrying with a different invocation, unless the skill itself defines a fallback.

## Security And Content Rules

Do not commit real credentials, `.env` files, API keys, or actual source hostnames. Start from `.env.example`, keep `INTERNAL_ADDRESS` valid for local runs, and use persistent config volumes for Docker-based services.

Never, at any point, add the hostnames of any sources Quasarr supports to any file that is not gitignored.

## Terminology

When referring to integrations such as `NK` or `DW`, always call them `sources`.

Always abbreviate sources as two-letter uppercase identifiers, for example `NK`, `DW`, `DD`, or `SJ`.
