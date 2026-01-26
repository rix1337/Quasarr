# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

from quasarr.providers.log import debug
from quasarr.providers.myjd_api import (
    MYJDException,
    RequestTimeoutException,
    TokenExpiredException,
)

# Known archive extensions for fallback detection
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


class JDPackageCache:
    """
    Caches JDownloader package/link queries within a single request.

    IMPORTANT: This cache is ONLY valid for the duration of ONE get_packages()
    or delete_package() call. JDownloader state can be modified at any time by
    the user or third-party tools, so cached data must NEVER persist across
    separate requests.

    This reduces redundant API calls within a single operation where the same
    data (e.g., linkgrabber_links) is needed multiple times.
    """

    def __init__(self, device):
        debug("JDPackageCache: Initializing new cache instance")
        self._device = device
        self._linkgrabber_packages = None
        self._linkgrabber_links = None
        self._downloader_packages = None
        self._downloader_links = None
        self._archive_cache = {}  # package_uuid -> bool (is_archive)
        self._is_collecting = None
        # Stats tracking
        self._api_calls = 0
        self._cache_hits = 0

    def get_stats(self):
        """Return cache statistics string."""
        pkg_count = len(self._downloader_packages or []) + len(
            self._linkgrabber_packages or []
        )
        link_count = len(self._downloader_links or []) + len(
            self._linkgrabber_links or []
        )
        return f"{self._api_calls} API calls | {pkg_count} packages, {link_count} links cached"

    @property
    def linkgrabber_packages(self):
        if self._linkgrabber_packages is None:
            debug("JDPackageCache: Fetching linkgrabber_packages from API")
            self._api_calls += 1
            try:
                self._linkgrabber_packages = self._device.linkgrabber.query_packages()
                debug(
                    f"JDPackageCache: Retrieved {len(self._linkgrabber_packages)} linkgrabber packages"
                )
            except (TokenExpiredException, RequestTimeoutException, MYJDException) as e:
                debug(f"JDPackageCache: Failed to fetch linkgrabber_packages: {e}")
                self._linkgrabber_packages = []
        else:
            self._cache_hits += 1
            debug(
                f"JDPackageCache: Using cached linkgrabber_packages ({len(self._linkgrabber_packages)} packages)"
            )
        return self._linkgrabber_packages

    @property
    def linkgrabber_links(self):
        if self._linkgrabber_links is None:
            debug("JDPackageCache: Fetching linkgrabber_links from API")
            self._api_calls += 1
            try:
                self._linkgrabber_links = self._device.linkgrabber.query_links()
                debug(
                    f"JDPackageCache: Retrieved {len(self._linkgrabber_links)} linkgrabber links"
                )
            except (TokenExpiredException, RequestTimeoutException, MYJDException) as e:
                debug(f"JDPackageCache: Failed to fetch linkgrabber_links: {e}")
                self._linkgrabber_links = []
        else:
            self._cache_hits += 1
            debug(
                f"JDPackageCache: Using cached linkgrabber_links ({len(self._linkgrabber_links)} links)"
            )
        return self._linkgrabber_links

    @property
    def downloader_packages(self):
        if self._downloader_packages is None:
            debug("JDPackageCache: Fetching downloader_packages from API")
            self._api_calls += 1
            try:
                self._downloader_packages = self._device.downloads.query_packages()
                debug(
                    f"JDPackageCache: Retrieved {len(self._downloader_packages)} downloader packages"
                )
            except (TokenExpiredException, RequestTimeoutException, MYJDException) as e:
                debug(f"JDPackageCache: Failed to fetch downloader_packages: {e}")
                self._downloader_packages = []
        else:
            self._cache_hits += 1
            debug(
                f"JDPackageCache: Using cached downloader_packages ({len(self._downloader_packages)} packages)"
            )
        return self._downloader_packages

    @property
    def downloader_links(self):
        if self._downloader_links is None:
            debug("JDPackageCache: Fetching downloader_links from API")
            self._api_calls += 1
            try:
                self._downloader_links = self._device.downloads.query_links()
                debug(
                    f"JDPackageCache: Retrieved {len(self._downloader_links)} downloader links"
                )
            except (TokenExpiredException, RequestTimeoutException, MYJDException) as e:
                debug(f"JDPackageCache: Failed to fetch downloader_links: {e}")
                self._downloader_links = []
        else:
            self._cache_hits += 1
            debug(
                f"JDPackageCache: Using cached downloader_links ({len(self._downloader_links)} links)"
            )
        return self._downloader_links

    @property
    def is_collecting(self):
        if self._is_collecting is None:
            debug("JDPackageCache: Checking is_collecting from API")
            self._api_calls += 1
            try:
                self._is_collecting = self._device.linkgrabber.is_collecting()
                debug(f"JDPackageCache: is_collecting = {self._is_collecting}")
            except (TokenExpiredException, RequestTimeoutException, MYJDException) as e:
                debug(f"JDPackageCache: Failed to check is_collecting: {e}")
                self._is_collecting = False
        else:
            self._cache_hits += 1
            debug(f"JDPackageCache: Using cached is_collecting = {self._is_collecting}")
        return self._is_collecting

    def _has_archive_extension(self, package_uuid, links):
        """Check if any link in the package has an archive file extension."""
        for link in links:
            if link.get("packageUUID") != package_uuid:
                continue
            name = link.get("name", "")
            name_lower = name.lower()
            for ext in ARCHIVE_EXTENSIONS:
                if name_lower.endswith(ext):
                    debug(
                        f"JDPackageCache: Found archive extension '{ext}' in file '{name}' for package {package_uuid}"
                    )
                    return True
        return False

    def _bulk_detect_archives(self, package_uuids):
        """
        Detect archives for multiple packages in ONE API call.

        Returns:
            tuple: (confirmed_archives: set, api_succeeded: bool)
            - confirmed_archives: Package UUIDs confirmed as archives
            - api_succeeded: Whether the API call worked (for fallback decisions)
        """
        confirmed_archives = set()

        if not package_uuids:
            debug(
                "JDPackageCache: _bulk_detect_archives called with empty package_uuids"
            )
            return confirmed_archives, True

        package_list = list(package_uuids)
        debug(
            f"JDPackageCache: Bulk archive detection for {len(package_list)} packages"
        )

        try:
            self._api_calls += 1
            archive_infos = self._device.extraction.get_archive_info([], package_list)
            debug(
                f"JDPackageCache: get_archive_info returned {len(archive_infos) if archive_infos else 0} results"
            )

            if archive_infos:
                for i, archive_info in enumerate(archive_infos):
                    if archive_info:
                        debug(f"JDPackageCache: archive_info[{i}] = {archive_info}")
                        # Try to get packageUUID from response
                        pkg_uuid = archive_info.get("packageUUID")
                        if pkg_uuid:
                            debug(
                                f"JDPackageCache: Confirmed archive via packageUUID: {pkg_uuid}"
                            )
                            confirmed_archives.add(pkg_uuid)
                        else:
                            # Log what fields ARE available for debugging
                            debug(
                                f"JDPackageCache: archive_info has no packageUUID, available keys: {list(archive_info.keys())}"
                            )
                    else:
                        debug(f"JDPackageCache: archive_info[{i}] is empty/None")

            debug(
                f"JDPackageCache: Bulk detection confirmed {len(confirmed_archives)} archives: {confirmed_archives}"
            )
            return confirmed_archives, True

        except Exception as e:
            debug(
                f"JDPackageCache: Bulk archive detection API FAILED: {type(e).__name__}: {e}"
            )
            return confirmed_archives, False

    def detect_all_archives(self, packages, links):
        """
        Detect archives for all packages efficiently.

        Uses ONE bulk API call, then applies safety fallbacks for packages
        where detection was uncertain.

        Args:
            packages: List of downloader packages
            links: List of downloader links (for extension fallback)

        Returns:
            Set of package UUIDs that should be treated as archives
        """
        if not packages:
            debug("JDPackageCache: detect_all_archives called with no packages")
            return set()

        all_package_uuids = {p.get("uuid") for p in packages if p.get("uuid")}
        debug(
            f"JDPackageCache: detect_all_archives for {len(all_package_uuids)} packages"
        )

        # ONE bulk API call for all packages
        confirmed_archives, api_succeeded = self._bulk_detect_archives(
            all_package_uuids
        )
        debug(
            f"JDPackageCache: Bulk API succeeded={api_succeeded}, confirmed={len(confirmed_archives)} archives"
        )

        # For packages NOT confirmed as archives, apply safety fallbacks
        unconfirmed = all_package_uuids - confirmed_archives
        debug(f"JDPackageCache: {len(unconfirmed)} packages need fallback checking")

        for pkg_uuid in unconfirmed:
            # Fallback 1: Check file extensions
            if self._has_archive_extension(pkg_uuid, links):
                debug(
                    f"JDPackageCache: Package {pkg_uuid} confirmed as archive via extension fallback"
                )
                confirmed_archives.add(pkg_uuid)
            # Fallback 2: If bulk API failed completely, assume archive (safe)
            elif not api_succeeded:
                debug(
                    f"JDPackageCache: SAFETY - Bulk API failed, assuming package {pkg_uuid} is archive"
                )
                confirmed_archives.add(pkg_uuid)
            else:
                debug(
                    f"JDPackageCache: Package {pkg_uuid} confirmed as NON-archive (API worked, no extension match)"
                )

        # Cache results for is_package_archive() lookups
        for pkg_uuid in all_package_uuids:
            self._archive_cache[pkg_uuid] = pkg_uuid in confirmed_archives

        debug(
            f"JDPackageCache: Final archive detection: {len(confirmed_archives)}/{len(all_package_uuids)} packages are archives"
        )
        return confirmed_archives

    def is_package_archive(self, package_uuid, links=None):
        """
        Check if a package contains archive files.

        Prefer calling detect_all_archives() first for efficiency.
        This method is for single lookups or cache hits.

        SAFETY: On API error, defaults to True (assume archive) to prevent
        premature "finished" status.
        """
        if package_uuid is None:
            debug("JDPackageCache: is_package_archive called with None UUID")
            return False

        if package_uuid in self._archive_cache:
            self._cache_hits += 1
            cached = self._archive_cache[package_uuid]
            debug(
                f"JDPackageCache: is_package_archive({package_uuid}) = {cached} (cached)"
            )
            return cached

        debug(
            f"JDPackageCache: is_package_archive({package_uuid}) - cache miss, querying API"
        )

        # Single package lookup (fallback if detect_all_archives wasn't called)
        is_archive = None
        api_failed = False

        try:
            self._api_calls += 1
            archive_info = self._device.extraction.get_archive_info([], [package_uuid])
            debug(f"JDPackageCache: Single get_archive_info returned: {archive_info}")
            # Original logic: is_archive = True if archive_info and archive_info[0] else False
            is_archive = True if archive_info and archive_info[0] else False
            debug(f"JDPackageCache: API says is_archive = {is_archive}")
        except Exception as e:
            api_failed = True
            debug(
                f"JDPackageCache: Single archive detection API FAILED for {package_uuid}: {type(e).__name__}: {e}"
            )

        # Fallback: check file extensions if API failed or returned False
        if (api_failed or not is_archive) and links:
            if self._has_archive_extension(package_uuid, links):
                debug(
                    f"JDPackageCache: Package {package_uuid} confirmed as archive via extension fallback"
                )
                is_archive = True

        # SAFETY: If API failed and no extension detected, assume archive (conservative)
        if is_archive is None:
            debug(
                f"JDPackageCache: SAFETY - Detection uncertain for {package_uuid}, assuming archive"
            )
            is_archive = True

        self._archive_cache[package_uuid] = is_archive
        debug(
            f"JDPackageCache: is_package_archive({package_uuid}) = {is_archive} (final)"
        )
        return is_archive
