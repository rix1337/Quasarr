from abc import ABC, abstractmethod

from quasarr.providers import shared_state
from quasarr.search.sources.helpers.search_release import SearchRelease


class AbstractSearchSource(ABC):
    @property
    @abstractmethod
    def initials(self) -> str:
        pass

    @property
    @abstractmethod
    def language(self) -> str:
        """Two-letter content language of the source ("de", "en", "fr")."""
        pass

    @property
    @abstractmethod
    def supports_imdb(self) -> bool:
        pass

    @property
    @abstractmethod
    def supports_phrase(self) -> bool:
        pass

    @property
    def supports_absolute_numbering(self) -> bool:
        return False

    @property
    def supports_date_numbering(self) -> bool:
        return False

    @property
    @abstractmethod
    def supported_categories(self) -> list[int]:
        pass

    @property
    def requires_login(self) -> bool:
        return False

    @property
    def requires_account(self) -> bool:
        """The source needs a registered user account to be usable."""
        return False

    @property
    def invite_only(self) -> bool:
        """Account creation requires an invitation (no open registration)."""
        return False

    @property
    def requires_flaresolverr(self) -> bool:
        """The source needs FlareSolverr to be usable."""
        return False

    @property
    def requires_radarr(self) -> bool:
        return False

    @property
    def requires_sonarr(self) -> bool:
        return False

    @abstractmethod
    def search(
        self,
        shared_state: shared_state,
        start_time: float,
        search_category: str,
        search_string: str = "",
        season: int = None,
        episode: int = None,
    ) -> list[SearchRelease]:
        pass

    @abstractmethod
    def feed(
        self,
        shared_state: shared_state,
        start_time: float,
        search_category: str,
    ) -> list[SearchRelease]:
        pass
