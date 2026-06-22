# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import re
import sys

# ==============================================================================
# CRITICAL CONFIGURATION
# ==============================================================================

# User agent for all requests, if not overwritten by Flaresolverr
FALLBACK_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"

# Standard request timeout budgets.
# Slow mode multiplies each base timeout by this factor.
TIMEOUT_SLOW_MODE_MULTIPLIER = 3

# Table storing per-timeout slow mode flags.
TIMEOUT_SLOW_MODE_TABLE = "timeout_slow_mode"

# Timeout settings shown in the Web UI.
TIMEOUT_SLOW_MODE_DEFINITIONS = {
    "search": {"label": "Search Timeout", "base_seconds": 15},
    "feed": {"label": "Feed Timeout", "base_seconds": 30},
    "download": {"label": "Download Timeout", "base_seconds": 30},
    "session": {"label": "Session Timeout", "base_seconds": 30},
}


def _coerce_timeout_bool(value, default=False):
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
    return bool(value)


def _is_timeout_slow_mode_enabled(timeout_key):
    try:
        from quasarr.providers import shared_state

        settings = shared_state.values.get("timeout_slow_mode")
        if isinstance(settings, dict):
            return _coerce_timeout_bool(settings.get(timeout_key), default=False)
    except Exception:
        return False

    return False


_TIMEOUT_RUNTIME_KEY_TO_NAME = {
    "search": "SEARCH_REQUEST_TIMEOUT_SECONDS",
    "feed": "FEED_REQUEST_TIMEOUT_SECONDS",
    "download": "DOWNLOAD_REQUEST_TIMEOUT_SECONDS",
    "session": "SESSION_REQUEST_TIMEOUT_SECONDS",
}


def _calculate_timeout_value(timeout_key, slow_mode_enabled):
    base_seconds = int(TIMEOUT_SLOW_MODE_DEFINITIONS[timeout_key]["base_seconds"])
    if slow_mode_enabled:
        return int(base_seconds * TIMEOUT_SLOW_MODE_MULTIPLIER)
    return base_seconds


def apply_timeout_slow_mode_settings(settings=None):
    if not isinstance(settings, dict):
        settings = {
            timeout_key: _is_timeout_slow_mode_enabled(timeout_key)
            for timeout_key in TIMEOUT_SLOW_MODE_DEFINITIONS
        }

    resolved_timeout_values = {}
    for timeout_key, const_name in _TIMEOUT_RUNTIME_KEY_TO_NAME.items():
        slow_mode_enabled = _coerce_timeout_bool(
            settings.get(timeout_key),
            default=False,
        )
        resolved_timeout_values[const_name] = _calculate_timeout_value(
            timeout_key,
            slow_mode_enabled,
        )

    for const_name, timeout_value in resolved_timeout_values.items():
        globals()[const_name] = timeout_value

    for module_name, module in list(sys.modules.items()):
        if module_name != "quasarr" and not module_name.startswith("quasarr."):
            continue

        module_dict = getattr(module, "__dict__", None)
        if not isinstance(module_dict, dict):
            continue

        for const_name, timeout_value in resolved_timeout_values.items():
            if const_name in module_dict:
                module_dict[const_name] = timeout_value

    return resolved_timeout_values


SEARCH_REQUEST_TIMEOUT_SECONDS = int(
    TIMEOUT_SLOW_MODE_DEFINITIONS["search"]["base_seconds"]
)
FEED_REQUEST_TIMEOUT_SECONDS = int(
    TIMEOUT_SLOW_MODE_DEFINITIONS["feed"]["base_seconds"]
)
DOWNLOAD_REQUEST_TIMEOUT_SECONDS = int(
    TIMEOUT_SLOW_MODE_DEFINITIONS["download"]["base_seconds"]
)
SESSION_REQUEST_TIMEOUT_SECONDS = int(
    TIMEOUT_SLOW_MODE_DEFINITIONS["session"]["base_seconds"]
)

# Notification providers exposed in config/UI.
NOTIFICATION_PROVIDERS = ("discord", "telegram")


# ==============================================================================
# SEARCH AND DOWNLOAD CATEGORIES
# ==============================================================================

# Search category source of truth
SEARCH_CATEGORY_DEFINITIONS = {
    "MOVIES": {"id": 2000, "name": "Movies", "emoji": "🎬"},
    "MOVIES_HD": {"id": 2040, "name": "Movies/HD", "emoji": "🎬"},
    "MOVIES_UHD": {"id": 2045, "name": "Movies/UHD", "emoji": "🎬"},
    "MUSIC": {"id": 3000, "name": "Audio", "emoji": "🎵"},
    "MUSIC_MP3": {"id": 3010, "name": "Audio/MP3", "emoji": "🎵"},
    "MUSIC_FLAC": {"id": 3040, "name": "Audio/FLAC", "emoji": "🎵"},
    "SHOWS": {"id": 5000, "name": "TV", "emoji": "📺"},
    "SHOWS_HD": {"id": 5040, "name": "TV/HD", "emoji": "📺"},
    "SHOWS_UHD": {"id": 5045, "name": "TV/UHD", "emoji": "📺"},
    "SHOWS_ANIME": {"id": 5070, "name": "TV/Anime", "emoji": "⛩️"},
    "SHOWS_DOCUMENTARY": {"id": 5080, "name": "TV/Documentary", "emoji": "🎥"},
    "XXX": {"id": 6000, "name": "XXX", "emoji": "🔞"},
    "BOOKS": {"id": 7000, "name": "Books", "emoji": "📚"},
}

# Importable constants for search categories are generated from the source of truth above to ensure consistency and maintainability.
SEARCH_CAT_MOVIES = SEARCH_CATEGORY_DEFINITIONS["MOVIES"]["id"]
SEARCH_CAT_MOVIES_HD = SEARCH_CATEGORY_DEFINITIONS["MOVIES_HD"]["id"]
SEARCH_CAT_MOVIES_UHD = SEARCH_CATEGORY_DEFINITIONS["MOVIES_UHD"]["id"]
SEARCH_CAT_MUSIC = SEARCH_CATEGORY_DEFINITIONS["MUSIC"]["id"]
SEARCH_CAT_MUSIC_MP3 = SEARCH_CATEGORY_DEFINITIONS["MUSIC_MP3"]["id"]
SEARCH_CAT_MUSIC_FLAC = SEARCH_CATEGORY_DEFINITIONS["MUSIC_FLAC"]["id"]
SEARCH_CAT_SHOWS = SEARCH_CATEGORY_DEFINITIONS["SHOWS"]["id"]
SEARCH_CAT_SHOWS_HD = SEARCH_CATEGORY_DEFINITIONS["SHOWS_HD"]["id"]
SEARCH_CAT_SHOWS_UHD = SEARCH_CATEGORY_DEFINITIONS["SHOWS_UHD"]["id"]
SEARCH_CAT_SHOWS_ANIME = SEARCH_CATEGORY_DEFINITIONS["SHOWS_ANIME"]["id"]
SEARCH_CAT_SHOWS_DOCUMENTARY = SEARCH_CATEGORY_DEFINITIONS["SHOWS_DOCUMENTARY"]["id"]
SEARCH_CAT_XXX = SEARCH_CATEGORY_DEFINITIONS["XXX"]["id"]
SEARCH_CAT_BOOKS = SEARCH_CATEGORY_DEFINITIONS["BOOKS"]["id"]

SEARCH_CATEGORIES = {
    definition["id"]: {"name": definition["name"], "emoji": definition["emoji"]}
    for definition in SEARCH_CATEGORY_DEFINITIONS.values()
}

# Explicit cache-sharing families for search result population.
# The owner key represents the category that should populate cache first whenever possible.
# Categories not listed here are treated as standalone cache groups.
SEARCH_CATEGORY_CACHE_FAMILIES = {
    SEARCH_CAT_MOVIES: (
        SEARCH_CAT_MOVIES,
        SEARCH_CAT_MOVIES_HD,
        SEARCH_CAT_MOVIES_UHD,
    ),
    SEARCH_CAT_MUSIC: (
        SEARCH_CAT_MUSIC,
        SEARCH_CAT_MUSIC_MP3,
        SEARCH_CAT_MUSIC_FLAC,
    ),
    SEARCH_CAT_SHOWS: (
        SEARCH_CAT_SHOWS,
        SEARCH_CAT_SHOWS_HD,
        SEARCH_CAT_SHOWS_UHD,
    ),
    SEARCH_CAT_SHOWS_ANIME: (SEARCH_CAT_SHOWS_ANIME,),
    SEARCH_CAT_SHOWS_DOCUMENTARY: (SEARCH_CAT_SHOWS_DOCUMENTARY,),
    SEARCH_CAT_XXX: (SEARCH_CAT_XXX,),
    SEARCH_CAT_BOOKS: (SEARCH_CAT_BOOKS,),
}

# Default Set of Download Categories
DOWNLOAD_CATEGORIES = {
    "movies": {"emoji": "🎬"},
    "music": {"emoji": "🎵"},
    "tv": {"emoji": "📺"},
    "docs": {"emoji": "📄"},
}

# Fallback category mapping by client type (used when no valid download category is provided)
CLIENT_DOWNLOAD_CATEGORY_FALLBACK_MAP = {
    "magazarr": "docs",
    "lidarr": "music",
    "radarr": "movies",
    "sonarr": "tv",
}

# ==============================================================================
# HOSTERS & MIRRORS
# ==============================================================================

# As of 01.02.2026
# Format: (Name, is_tier1)
HOSTERS = [
    # --- TIER 1: The Standards (Required for most downloaders) ---
    ("Rapidgator", True),  # Global King. Most files are here.
    ("DDownload", True),  # The "Euro Standard". Cheaper alternative to RG.
    # --- TIER 2: Very Popular / High Retention ---
    ("1fichier", False),  # Massive retention, cheap, very popular in France/Global.
    ("Keep2Share", False),  # "Premium" tier. High speeds, expensive, very stable.
    (
        "Nitroflare",
        False,
    ),  # Old guard. Expensive, but essential for some exclusive content.
    # --- TIER 3: Common Mirrors (The "Third Link") ---
    ("Turbobit", False),  # Everywhere, but often disliked by free users.
    ("Hitfile", False),  # Turbobit's sibling site. Often seen together.
    ("Katfile", False),  # Very common secondary mirror for smaller uploaders.
    ("Alfafile", False),  # Stable mid-tier host, often seen on DDL blogs.
    # --- TIER 4: Niche / Backup / User Requested ---
    ("Filer", False),  # Strong in German-speaking areas, niche elsewhere.
    (
        "IronFiles",
        False,
    ),  # Active. Smaller ecosystem, often specific to certain boards.
    ("Fikper", False),  # Newer player (relative to RG), gained traction in 2024-25.
    ("Mega", False),  # Active, but functions differently (cloud drive vs. OCH).
    ("AkiraBox", False),  # Common mirror on anime-focused releases.
    ("BuzzHeavier", False),  # Common mirror on anime-focused releases.
    ("ClickNupload", False),  # Common mirror on RM releases.
    ("GoFile", False),  # Common mirror on anime-focused releases.
    ("KrakenFiles", False),  # Common mirror on anime-focused releases.
    ("MdiaLoad", False),  # Common mirror on anime-focused releases.
    ("MultiUp", False),  # Common mirror on anime-focused releases.
    ("RapidRAR", False),  # Common mirror on RM releases.
    ("frdl", False),  # Rarely used in some forums
    ("Send", False),  # send.cm / send.now — served by MX (French DDL).
]

# Used to identify share hosters (lowercase for comparison)
SHARE_HOSTERS_LOWERCASE = {h[0].lower() for h in HOSTERS}
SHARE_HOSTERS = [h[0] for h in HOSTERS]

# Recommend only these
RECOMMENDED_HOSTERS = [h[0] for h in HOSTERS if h[1]]

# Evidence-backed root-token aliases for final mirror whitelist checks.
# Sources used on 2026-03-02:
# - JDownloader host plugins (mirror/jdownloader)
# - pyLoad host plugins (pyload/pyload)
#
# Matching is performed on the pure mirror/root token derived from the final
# HTTP hostname, ignoring TLDs and subdomains. Keep only root tokens here.
MIRROR_TOKEN_ALIASES = {
    "alterupload": "1fichier",
    "cjoint": "1fichier",
    "clickndownload": "clicknupload",
    "ddl": "ddownload",
    "ddlto": "ddownload",
    "depositfiles": "turbobit",
    "desfichiers": "1fichier",
    "dfichiers": "1fichier",
    "dl4free": "1fichier",
    "dlbit": "turbobit",
    "fayloobmennik": "turbobit",
    "fboom": "keep2share",
    "filedeluxe": "turbobit",
    "fileboom": "keep2share",
    "filemaster": "turbobit",
    "flacmania": "turbobit",
    "filernet": "filer",
    "filhost": "turbobit",
    "hil": "hitfile",
    "hotshare": "turbobit",
    "ifolder": "turbobit",
    "k2s": "keep2share",
    "k2share": "keep2share",
    "keep2": "keep2share",
    "keep2s": "keep2share",
    "megadl": "1fichier",
    "mesfichiers": "1fichier",
    "nitro": "nitroflare",
    "pjointe": "1fichier",
    "piecejointe": "1fichier",
    "publish2": "keep2share",
    "rapidfile": "turbobit",
    "rg": "rapidgator",
    "sibit": "turbobit",
    "tb": "turbobit",
    "tenvoi": "1fichier",
    "tezfiles": "keep2share",
    "tourbobit": "turbobit",
    "trbbt": "turbobit",
    "trubobit": "turbobit",
    "turb": "turbobit",
    "turbo": "turbobit",
    "turbabit": "turbobit",
    "turbobeet": "turbobit",
    "turbobi": "turbobit",
    "turbobbit": "turbobit",
    "turbobif": "turbobit",
    "turbobit5": "turbobit",
    "turbobita": "turbobit",
    "turbobite": "turbobit",
    "turbobith": "turbobit",
    "turbobitn": "turbobit",
    "turbobitt": "turbobit",
    "turbobiyt": "turbobit",
    "turbobyt": "turbobit",
    "turbobyte": "turbobit",
    "turboot": "turbobit",
    "turboobit": "turbobit",
    "turobit": "turbobit",
    "twobit": "turbobit",
    "ucdn": "ddownload",
    "wayupload": "turbobit",
    "xrfiles": "turbobit",
}

# ==============================================================================
# REGEX PATTERNS (CONTENT & PARSING)
# ==============================================================================

# Used to identify release tittles with season or Episode numbers
SEASON_EP_REGEX = re.compile(
    r"(?i)(?:S\d{1,3}(?:E\d{1,3}(?:-\d{1,3})?)?|S\d{1,3}-\d{1,3})"
)

# Used to identify movies
MOVIE_REGEX = re.compile(
    r"^(?!.*(?:S\d{1,3}(?:E\d{1,3}(?:-\d{1,3})?)?|S\d{1,3}-\d{1,3})).*$", re.IGNORECASE
)

# Domain checks
AFFILIATE_REGEX = re.compile(r"af\.php\?v=([a-zA-Z0-9]+)")
FILECRYPT_REGEX = re.compile(
    r"https?://(?:www\.)?filecrypt\.(?:cc|co|to)/[Cc]ontainer/[A-Za-z0-9]+", re.I
)
IMDB_REGEX = re.compile(r"imdb\.com/title/(tt\d+)", re.I)

# Release Title Checks
RESOLUTION_REGEX = re.compile(r"\d{3,4}p", re.I)
CODEC_REGEX = re.compile(r"x264|x265|h264|h265|hevc|avc", re.I)
XXX_REGEX = re.compile(r"\.xxx\.", re.I)

SIZE_REGEX = re.compile(r"Größe[:\s]*(\d+(?:[.,]\d+)?)\s*(MB|GB|TB)", re.I)

DATE_REGEX = re.compile(r"(\d{2}\.\d{2}\.\d{2}),?\s*(\d{1,2}:\d{2})")

# Pattern to extract individual episode release names from text
# Matches: Title.S02E03.Info-GROUP (group name starts after hyphen)
EPISODE_EXTRACT_REGEX = re.compile(
    r"([A-Za-z][A-Za-z0-9.]+\.S\d{2}E\d{2}[A-Za-z0-9.]*-[A-Za-z][A-Za-z0-9]*)", re.I
)

# Pattern to clean trailing common words that may be attached to group names
# e.g., -WAYNEAvg -> -WAYNE, -GROUPBitrate -> -GROUP
TRAILING_GARBAGE_PATTERN = re.compile(
    r"(Avg|Bitrate|Size|Größe|Video|Audio|Duration|Release|Info).*$", re.I
)

# Pattern to extract average bitrate (e.g., "Avg. Bitrate: 10,6 Mb/s" or "6 040 kb/s")
# Note: Numbers may contain spaces as thousand separators (e.g., "6 040")
BITRATE_REGEX = re.compile(
    r"(?:Avg\.?\s*)?Bitrate[:\s]*([\d\s]+(?:[.,]\d+)?)\s*(kb/s|Mb/s|mb/s)", re.I
)

# Pattern to extract episode duration (e.g., "Dauer: 60 Min. pro Folge")
EPISODE_DURATION_REGEX = re.compile(r"Dauer[:\s]*(\d+)\s*Min\.?\s*pro\s*Folge", re.I)


# ==============================================================================
# DECRYPTION & PROTECTION
# ==============================================================================

# Identifies Linkcrypters that never require CAPTCHA
AUTO_DECRYPT_PATTERNS = {
    "hide": re.compile(r"hide\.", re.IGNORECASE),
}

# Identifies Linkcrypters that may require CAPTCHA
PROTECTED_PATTERNS = {
    "filecrypt": re.compile(r"filecrypt\.", re.IGNORECASE),
    "tolink": re.compile(r"tolink\.", re.IGNORECASE),
    "keeplinks": re.compile(r"keeplinks\.", re.IGNORECASE),
}


# ==============================================================================
# QUASARR PACKAGE MANAGEMENT
# ==============================================================================

# Prefix for all Quasarr Packages
PACKAGE_ID_PREFIX = "Quasarr_"

# Regex for strict Quasarr ID validation: Quasarr_{category}_{32_char_hash}
PACKAGE_ID_PATTERN = re.compile(r"^Quasarr_[a-z]+_[a-f0-9]{32}$")


# ==============================================================================
# JDOWNLOADER / EXTRACTION
# ==============================================================================

# Status Strings from JDownloader (add more languages if needed)
EXTRACTION_COMPLETE_MARKERS = (
    "extraction ok",  # English
    "entpacken ok",  # German
)

# Status Strings from JDownloader (add more languages if needed)
NOT_DOWNLOADABLE_MARKERS = (
    "not downloadable",  # English
)

# Used during archive detection
ARCHIVE_EXTENSIONS = frozenset(
    [
        ".rar",
        ".zip",
        ".7z",
        ".tar",
        ".gz",
        ".bz2",
        ".xz",
        ".001",
        ".002",
        ".003",
        ".004",
        ".005",
        ".006",
        ".007",
        ".008",
        ".009",
        ".r00",
        ".r01",
        ".r02",
        ".r03",
        ".r04",
        ".r05",
        ".r06",
        ".r07",
        ".r08",
        ".r09",
        ".part1.rar",
        ".part01.rar",
        ".part001.rar",
        ".part2.rar",
        ".part02.rar",
        ".part002.rar",
    ]
)


# ==============================================================================
# TIME & LOCALIZATION
# ==============================================================================

LANGUAGE_TO_ALPHA2 = {
    "german": "DE",
    "deutsch": "DE",
    "de": "DE",
    "ger": "DE",
    "deu": "DE",
    "english": "EN",
    "englisch": "EN",
    "en": "EN",
    "eng": "EN",
    "japanese": "JP",
    "japanisch": "JP",
    "jp": "JP",
    "jpn": "JP",
}

SUBTITLE_TOKEN_BY_ALPHA2 = {
    "DE": "GerSub",
    "EN": "EngSub",
    "JP": "JapSub",
}

SESSION_MAX_AGE_SECONDS = 24 * 60 * 60  # 24 hours

# Source of truth for month names and mappings
# Format: (Month Number, English Name, German Name, [Additional Synonyms])
_MONTHS_CONFIG = [
    (1, "January", "Januar", ["jan"]),
    (2, "February", "Februar", ["feb"]),
    (3, "March", "März", ["maerz", "mär", "mrz", "mae"]),
    (4, "April", "April", ["apr"]),
    (5, "May", "Mai", ["may"]),
    (6, "June", "Juni", ["jun", "june"]),
    (7, "July", "Juli", ["jul", "july"]),
    (8, "August", "August", ["aug"]),
    (9, "September", "September", ["sep"]),
    (10, "October", "Oktober", ["okt", "october"]),
    (11, "November", "November", ["nov"]),
    (12, "December", "Dezember", ["dez", "december"]),
]

ENGLISH_MONTHS = [m[1] for m in _MONTHS_CONFIG]
GERMAN_MONTHS = [m[2] for m in _MONTHS_CONFIG]

MONTHS_MAP = {
    name.lower(): nr
    for nr, en, de, synonyms in _MONTHS_CONFIG
    for name in [en, de] + synonyms
}


# ==============================================================================
# DISCORD / NOTIFICATIONS
# ==============================================================================

# Shared notification branding/assets
QUASARR_AVATAR = "https://raw.githubusercontent.com/rix1337/Quasarr/main/Quasarr.png"
SPONSORS_HELPER_URL = (
    "https://github.com/rix1337/Quasarr?tab=readme-ov-file#sponsorshelper"
)

# Discord message flag for suppressing notifications
SUPPRESS_NOTIFICATIONS = 1 << 12  # 4096
