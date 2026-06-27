# quasarr/search/ — Search Side

## Purpose

The Newznab-facing search layer: `get_search_results()` fans a single *arr request (IMDb-ID search, phrase search, or feed pull) out in parallel across all discovered source modules, caches per-source results, merges/sorts/filters/paginates them, and returns releases whose `link` points back at Quasarr's own `/download/` endpoint with a base64 payload.

## Ownership

- `__init__.py` — orchestrator: the three search branches, `SearchExecutor` (thread-pool fan-out + per-source status badges), `SearchCache` (TTL cache)
- `sources/` — see Child DOX Index

## Local Contracts

- Per-source gating before dispatch: hostname configured, category in `supported_categories`, category whitelist from `get_search_category_sources`, `supports_imdb` for the imdb branch, `supports_phrase` for the phrase branch, `supports_absolute_numbering` when an episode is given without a season, and `supports_date_numbering` for Sonarr's year + `MM/DD` episode shape. The feed branch checks only hostname/category/whitelist.
- Date-numbered requests are parsed once into a validated `datetime.date` and passed to sources as `episode_date`; invalid calendar dates stay on the normal numbering path.
- The method names `search` and `feed` are load-bearing — dispatch is `getattr(source, action)`.
- Cache TTL is 300s for search, 60s for feed; the key nulls `start_time` and uses the cache-owner category. Cached entries skip execution entirely, so source methods must be safe to skip.
- Per-source results are merged, date-sorted descending, title-filtered by `release_matches_search_category`, then offset/limit-sliced; feed responses are never paginated.
- Search sources normally have a same-key download twin (FX is the search-only exception); the `source_key` embedded in the search payload routes the later `download()` call to the same-key twin first when one exists.

## Work Guidance

(none beyond the contracts above — see `sources/AGENTS.md` for source-module rules)

## Verification

- Full unit suite: `uv run python -X utf8 -m unittest discover -s tests`
- Live searches/feeds: `uv run cli_tester.py`

## Child DOX Index

- `quasarr/search/sources/AGENTS.md` — search source plug-in contract (`Source` class, `SearchRelease` shape, payload format, conventions)
