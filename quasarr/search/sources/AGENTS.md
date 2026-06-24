# quasarr/search/sources/ — Search Source Plug-ins

## Purpose

Per-source scraper modules implementing search and feed against third-party sites. Twenty-two sibling modules share one strict contract that every new source must replicate.

## Ownership

Two-letter lowercase source modules plus `helpers/`: `search_source.py` (`AbstractSearchSource` ABC), `search_release.py` (`SearchRelease` shape), `__init__.py` (hostname/capability getters consumed by the config UI).

## Local Contracts

- Registration is by file existence alone: drop `<xy>.py` into this folder exposing `class Source(AbstractSearchSource)`. The module filename, `Source.initials`, and the `Config("Hostnames")` key all use the same two-letter key; a same-key download twin exists only when release links need source-specific extraction (FX has none). Adding/renaming a module file changes the Hostnames config key space automatically.
- Signatures: `search(shared_state, start_time, search_category, search_string="", season=None, episode=None)` and `feed(shared_state, start_time, search_category)`, both returning `list[SearchRelease]` — empty list on failure, never raise to the caller.
- `SearchRelease`: `{"details": {"title", "hostname" (= initials), "imdb_id" (str or None), "link", "size" (bytes), "date" (RFC822 preferred), "source" (original page URL)}, "type": "protected"}` — every emit site uses type `"protected"`.
- `details.link` must come from `quasarr.providers.utils.generate_download_link(...)`; the payload is pipe-delimited (`title|url|size_mb|password|imdb_id|source_key`), so field values must not contain `|`.
- Capabilities are plain class attributes: `initials`, `language` (`"de"`, `"en"`, or `"fr"`), `supports_imdb`, `supports_phrase`, `supported_categories` (constants `SEARCH_CAT_*`), plus optional `supports_absolute_numbering` / `requires_login` / `requires_account` / `invite_only` / `requires_flaresolverr` / `requires_radarr` / `requires_sonarr`. `language`, category, account, invite, login, FlareSolverr, and *arr-client metadata is surfaced in the hostname editor through `helpers.get_source_metadata()`.
- `is_valid_release(...)` is the default validation for each candidate title in `search()` (not `feed()`); AT and AL intentionally deviate with bespoke matching suited to absolute-numbered anime. IMDb convention: if the searched ID and a release-page ID both exist and differ → skip; if the release lacks one → inherit the searched ID.
- Call `mark_hostname_issue(self.initials, "feed"|"search", msg)` on fetch/parse errors and `clear_hostname_issue(self.initials)` when releases were produced.
- `Source.__init__` must be cheap and never fail — a failure is logged as an error and the source is dropped from the registry.

## Work Guidance

- Hostnames only via `shared_state.values["config"]("Hostnames").get(self.initials)`; URLs built as `f"https://{host}/..."` — never hardcode source hostnames.
- Archive password is conventionally derived from the hostname (varies per source: whole host, first label, upper-cased, or www-prefixed).
- Timeouts from `constants.FEED_/SEARCH_REQUEST_TIMEOUT_SECONDS`; User-Agent from shared state. Sources without native IMDb search resolve a localized title via `get_localized_title(shared_state, imdb_id, language)` — pass `"de"`, `"en"`, or `"fr"` matching the source site's content language.
- Module-private parsing helpers are underscore-prefixed at the module bottom; `size` flows as MB int into `generate_download_link` and as bytes in `details.size`; size 0 is the accepted fallback.
- Do not infer payloads or response shapes — the root `Third-Party Source Work` rules require real traffic captures or direct curl confirmation first.
- A new source adds its entry to the Per-Source Notes below and, when it has a download module, to the notes in `quasarr/downloads/sources/AGENTS.md` — in the same change.

### Per-Source Notes (search side)

Capability flags (`supports_*`, `requires_*`) and categories are class attributes readable in each module; these notes carry only what is not obvious from the code. Download-side notes live in `quasarr/downloads/sources/AGENTS.md`.

- **AL** — login (`providers/sessions/al`, FlareSolverr required). Anime: absolute numbering resolved via XEM season names, titles built with `downloads/sources/helpers/anime_title.guess_release_title`. A single-hit search redirect is treated as the result (redirects followed before parsing); per-release HTML briefly cached via `get_recently_searched`; multi-episode packs split per requested episode with size divided proportionally. Sets the release id as the payload `password` for its download twin.
- **AT** — no login. Listing and attachment pages fetched in parallel (`ThreadPoolExecutor`); anime titles via `guess_release_title` with subtitle-language tokens injected from attachment names; German season names via XEM; validates titles with `match_in_title` instead of `is_valid_release` (absolute-numbering matching).
- **BY** — no login. Book/magazine titles run through Magazarr-compatible date/issue normalization; search drops releases without valid resolution/codec (feed keeps the original metadata); per-category fetches use category-ID constants inside the module.
- **DD** — login (`providers/sessions/dd`, which applies a fixed quality-profile filter to API responses — new resolutions must be added there). IMDb mismatch between request and API response discards the result; a suspected fake release (the API's `fake` flag) invalidates the cached session.
- **DJ** — login (shares the `JUNKIES` credentials section with SJ). IMDb-only; series discovered by HTML scrape to locate a media id, releases then fetched via JSON and aggregated per season block.
- **DL** — login (`providers/sessions/dl`); umlauts normalized when building queries. Paginated search is sequential, bounded by a wall-clock budget, and stops on an empty page; yearly magazine threads ("Jahresthema") expand into per-issue entries (requires the current year in the thread); magazine titles use a token-normalized matcher to align month/issue variants.
- **DT** — no login. Article date parsing assumes a fixed timezone offset; IMDb id parsed from article HTML and propagated; search drops candidates not matching requested resolution/codec (feed keeps them).
- **DW** — no login. German month names mapped in a local table (new variants go there); IMDb id read from article HTML validates the result still matches the request.
- **FF** — no login, movie-only. Search uses the public title lookup, then opens each movie page to extract IMDb id and the movie-token release API; releases are emitted from API `div.entry` blocks and use the release page URL as the download payload source. Feed reads recent update rows, then cross-references each movie page/API to fill size and IMDb data for the release anchors; cross-reference stops when the source's global feed budget reaches `FEED_REQUEST_TIMEOUT_SECONDS`.
- **FX** — no login, search-only (no download module): articles expose multiple filecrypt-protected link blocks iterated by index; default password derived from a fixed portion of the configured hostname; size read from a tagged inline element near the article body. The IMDb link is read from each entry's own `<td>` context (`find_parent("td")`) first, falling back to the whole article only when that `<td>` has none — so one entry's wrong IMDb link only skips that entry instead of discarding every result in the article.
- **HE** — no login, IMDb-only; the feed is the empty-query case of search (one shared code path); relative timestamps ("X minutes ago" incl. German variants) normalized to RFC dates.
- **HS** — no login, IMDb-only RSS feed parsed with BeautifulSoup `html.parser` (lxml deliberately avoided); per-episode size = season-pack bitrate × parsed episode duration, falling back to the pack size; episode metadata extracted with a regex constant inside the module.
- **MB** — no login, IMDb-only: the IMDb id is submitted directly as the site search query; German month parsing via a local `MONTHS_MAP`; search drops candidates not matching requested resolution/codec (feed keeps them as posted).
- **MX** — no login, IMDb-only JSON API (French DDL). API base is `api.<configured-host>`; `Referer`/`Origin` set to the configured host. `search` resolves a French title via `get_localized_title(..., "fr")`, queries the title endpoint, and matches the entry whose `imdb_id` equals the request (the first result is not reliably correct; never take `[0]`). The matched entry's internal `id` drives the download endpoint; the API also returns a `tmdb_id` but the download endpoint ignores it, so no external TMDB/Radarr/Sonarr resolution is used for searches. Series require `season`+`episode` per request (an API hard requirement). Each link is decoded via the decode endpoint (real URL under `embed_url.lien` for object responses) during search, so the payload already holds the final hoster URL. `feed` has no native discovery endpoint and instead seeds from the *arr wanted lists (missing + cutoff-unmet, missing first): movies via `radarr_api.get_wanted_imdb_ids` (released-to-cinema only — announced titles skipped), and episodes — carrying the required season+episode — via `sonarr_api.get_wanted_episodes` (aired only — unaired episodes skipped); both capped by `FEED_LIBRARY_LIMIT`. `requires_radarr` + `requires_sonarr` are set so the setup wizard can prompt for both clients; ID search needs neither, and `feed` logs a warning and returns empty (rather than failing) when its category's client is missing — so movie-only / TV-only setups work. Quality strings are normalized to scene tokens in `_normalize_quality`; titles tagged `.MX.<host>.<lang>`.
- **NK** — no login. Form-encoded POST search; IMDb input first converted to a localized German title; default passwords read from a labelled element in the mirrors paragraph when present; season-pack size is unknown and reported as 0 so consumers estimate per episode; the local date parser accepts several formats — add new ones there.
- **NX** — login required for downloads (`providers/sessions/nx` is used by the download twin only — search and feed run on plain unauthenticated requests). Internal type tokens (ebook/movie/episode/audio) map to Quasarr categories and must stay in lockstep with the API; book titles normalized via the Magazarr helper; an IMDb mismatch on the API response drops the result.
- **RM** — no login, but requests only succeed on a bootstrapped session (`_bootstrap_session`, defined in the downloads twin and imported here). Production-centred model: find productions, then fetch each production's releases; search tries multiple match variants (full name, leading words, trailing words, year-stripped); titles normalized by stripping leading tags and replacing spaces with dots; the feed walks a bounded number of production pages.
- **SF** — no login. Feed covers only a rolling two-day window; search is a two-call flow (series lookup, then season HTML from an epoch-suffixed API); mirror short host codes are mapped to full hoster names via a local `host_map` in the module — new codes go there (unknown codes pass through raw); search HTML briefly cached via `get_recently_searched`; season-pack size divided evenly across episodes when emitting per-episode releases.
- **SJ** — login (shares `JUNKIES` with DJ). IMDb-only; the feed walks recent date-window pages and stops at the first that returns results; releases aggregated per season block; ISO-8601 timestamps normalized to RFC dates.
- **SL** — no login. Every fetch requires Cloudflare clearance via the shared `ensure_session_cf_bypassed` wrapper, so `requires_flaresolverr` is set; feed parsed with `xml.etree`, search scrapes sections in parallel; results deduplicated by source link (shows surface in multiple sections); size and IMDb id extracted from the RSS description text, not a structured field.
- **WD** — no login, FlareSolverr required for Cloudflare security verification. Adult-tagged entries excluded unless the query explicitly targets them; video categories enforce resolution/codec checks on search results (feed keeps listing data); special characters percent-encoded before query submission.
- **WX** — no login. Feed parser auto-detects RSS vs Atom; the feed's default password is the configured hostname upper-cased, while search emits a `www.`-prefixed hostname as the password; search filters API results by internal type token (movie/series/anime); releases deduplicated by full title; IMDb mismatches dropped, and the release's own IMDb id is preferred when the query supplied none.

## Verification

- Full unit suite: `uv run python -X utf8 -m unittest discover -s tests`
- Live searches/feeds against configured sources: `uv run cli_tester.py`

## Child DOX Index

None.
