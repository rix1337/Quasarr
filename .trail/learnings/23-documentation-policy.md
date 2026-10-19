---
title: Documentation rules preserve architectural reasons without duplicating code
date: 2026-10-19
author: Quasarr
touches:
  - AGENTS.md
  - CLAUDE.md
  - README.md
  - CONTRIBUTING.md
  - check_trail.py
---

## Decided

Keep one root AGENTS.md for priority rules and the Trail workflow. Do not create child instruction files or restore a documentation hierarchy. Keep CLAUDE.md as the single-line pointer `@AGENTS.md`; never duplicate instructions into it.

Record durable architectural choices, their reasons, tested alternatives, and invariants as focused Trail learnings. Do not document code flows, inventories, signatures, transcripts, task diaries, or token-saving estimates. Never invent historical rationale or rejected alternatives. Use `## Decided` for the choice and reason, `## Watch out` for invariants, and `## Tried and ruled out` only when alternatives were actually investigated.

Why: The previous documentation hierarchy consumed context and duplicated information agents can retrieve from code. Focused decisions preserve the reasoning code cannot explain, while native headings let Trail summarize and classify that knowledge.

## Watch out

Read related learnings before adding one. Create notes only for useful decisions or corrected architectural assumptions, not ordinary code changes. Once committed, preserve existing learnings; changed decisions get new notes naming what they supersede and why. Verify historical guidance against dates and current code.

Write curated Markdown directly with generic author `Quasarr` and exact repository-relative `touches` paths. Never commit source hostnames, personal metadata, absolute local paths, credentials, captures, or generated maps. Automatic author, branch, or transcript metadata must not enter shared notes. Never force-add ignored files or commit machine-specific agent settings.

The root README introduces the project to users; ignore it for implementation unless the task concerns it. Keep CONTRIBUTING synchronized with development commands, without pinning the Trail version. Explain release-webhook secret setup in chat, not CONTRIBUTING. Keep SponsorsHelper promotion limited to the existing README mention.
