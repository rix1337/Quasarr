---
title: Keep AL metadata selectors compatible with strict SoupSieve
author: Quasarr
date: 2026-10-24
touches:
  - quasarr/downloads/sources/al.py
  - quasarr/search/sources/al.py
  - tests/test_al_metadata_parsing.py
---

## Decided

Use a header selector with a simple relative icon match and select its sibling data cell for AL metadata. Keep the header relationship explicit so icons in unrelated cells cannot select a row.

Why: Strict SoupSieve rejects the complex selector inside the previous row-level `:has()`. This fails before inspecting HTML and affects both search and shared download metadata parsing. Live AL markup confirmed the replacement selects the same metadata cells and language flags.

## Tried and ruled out

Adding whitespace or a leading child combinator to the old complex argument still raises `SelectorSyntaxError`. The legacy selectors with SoupSieve's permissive flag matched the same live elements as the replacement; permissive mode was used only for comparison.

## Watch out

Metadata includes release notes, resolution, audio and subtitle languages, group, date, and size. Exercise the production search path as well as the shared parser, including absent metadata rows. Keep live captures gitignored and regression fixtures synthetic.
