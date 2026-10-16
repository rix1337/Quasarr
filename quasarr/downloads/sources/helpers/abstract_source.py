# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

from abc import ABC, abstractmethod

from quasarr.downloads.sources.helpers.download_release import DownloadRelease


class AbstractDownloadSource(ABC):
    @property
    @abstractmethod
    def initials(self) -> str:
        pass

    @abstractmethod
    def get_download_links(
        self,
        shared_state,
        url: str,
        mirrors: list[str],
        title: str,
        password: str,
    ) -> DownloadRelease:
        pass

    def get_package_identity(self, url: str) -> str | None:
        """Return an optional stable identity for deterministic package IDs."""
        return None
