"""Registry of search providers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from metasearchmcp.config import get_settings

# Tor / onion services
from .ahmia import AhmiaProvider

# Finance
from .alpha_vantage import AlphaVantageProvider

# Academic
from .arxiv import ArxivProvider

# General web search
from .baidu import BaiduProvider
from .bing import BingProvider
from .bluesky import BlueskyProvider
from .brave import BraveProvider
from .codeberg import CodebergProvider
from .courtlistener import CourtListenerProvider
from .crates import CratesIoProvider
from .crossref import CrossrefProvider
from .dockerhub import DockerHubProvider
from .duckduckgo import DuckDuckGoProvider
from .ecosia import EcosiaProvider
from .finnhub import FinnhubProvider
from .flickr import FlickrProvider
from .github import GitHubProvider
from .gitlab import GitLabProvider

# Google providers
from .google import GoogleProvider
from .google_news import GoogleNewsProvider
from .google_patents import GooglePatentsProvider
from .google_serpbase import GoogleSerpbaseProvider
from .google_serper import GoogleSerperProvider
from .hackernews import HackerNewsProvider
from .huggingface import HuggingFaceProvider

# Knowledge / reference
from .internet_archive import InternetArchiveProvider
from .itunes import ITunesProvider
from .lemmy import LemmyProvider
from .lib_rs import LibRsProvider
from .lobsters import LobstersProvider
from .marginalia import MarginaliaProvider
from .mastodon import MastodonProvider
from .maven import MavenProvider
from .metacpan import MetaCPANProvider
from .mojeek import MojeekProvider
from .musicbrainz import MusicBrainzProvider
from .mwmbl import MwmblProvider
from .npm import NpmProvider
from .openalex import OpenAlexProvider
from .openlibrary import OpenLibraryProvider
from .openmeteo import OpenMeteoProvider
from .openverse import OpenverseProvider
from .orcid import OrcidProvider
from .peertube import PeerTubeProvider
from .pkg_go_dev import PkgGoDevProvider
from .pubmed import PubMedProvider
from .pypi import PyPIProvider
from .qwant import QwantProvider
from .radio_browser import RadioBrowserProvider
from .reddit import RedditProvider
from .rubygems import RubyGemsProvider
from .semanticscholar import SemanticScholarProvider
from .seznam import SeznamProvider
from .sourcegraph import SourcegraphProvider
from .stackoverflow import StackOverflowProvider
from .startpage import StartpageProvider
from .tvmaze import TVMazeProvider
from .unsplash import UnsplashProvider
from .wikibooks import WikibooksProvider
from .wikidata import WikidataProvider
from .wikimedia_commons import WikimediaCommonsProvider
from .wikinews import WikinewsProvider
from .wikipedia import WikipediaProvider
from .wikiquote import WikiquoteProvider
from .wikisource import WikisourceProvider
from .wikiversity import WikiversityProvider
from .wikivoyage import WikivoyageProvider
from .wiktionary import WiktionaryProvider
from .yahoo import YahooProvider
from .yahoo_finance import YahooFinanceProvider
from .yandex import YandexProvider
from .youcom import YouComProvider
from .zenodo import ZenodoProvider

if TYPE_CHECKING:
    from .base import BaseProvider

# Ordered list of all provider classes.
# Order matters: within a tag group, earlier providers take priority in dedup.
_ALL_PROVIDER_CLASSES: list[type[BaseProvider]] = [
    # Google
    GoogleProvider,
    GoogleSerpbaseProvider,
    GoogleSerperProvider,
    # General web search
    DuckDuckGoProvider,
    BingProvider,
    YahooProvider,
    BraveProvider,
    YouComProvider,
    MwmblProvider,
    EcosiaProvider,
    MojeekProvider,
    StartpageProvider,
    QwantProvider,
    YandexProvider,
    BaiduProvider,
    MarginaliaProvider,
    SeznamProvider,
    AhmiaProvider,
    # Knowledge base
    WikipediaProvider,
    WikidataProvider,
    WikiquoteProvider,
    WikibooksProvider,
    WikisourceProvider,
    WiktionaryProvider,
    WikivoyageProvider,
    WikiversityProvider,
    InternetArchiveProvider,
    # Places / geocoding
    OpenMeteoProvider,
    # Legal
    CourtListenerProvider,
    # Patents
    GooglePatentsProvider,
    # News
    GoogleNewsProvider,
    WikinewsProvider,
    # Media / image search
    WikimediaCommonsProvider,
    OpenverseProvider,
    FlickrProvider,
    UnsplashProvider,
    # Media / video search
    PeerTubeProvider,
    TVMazeProvider,
    # Media / radio
    RadioBrowserProvider,
    # Media / music
    MusicBrainzProvider,
    # Media / podcasts
    ITunesProvider,
    # Developer
    GitHubProvider,
    GitLabProvider,
    CodebergProvider,
    StackOverflowProvider,
    SourcegraphProvider,
    HackerNewsProvider,
    HuggingFaceProvider,
    RedditProvider,
    LemmyProvider,
    LobstersProvider,
    MastodonProvider,
    BlueskyProvider,
    NpmProvider,
    PyPIProvider,
    RubyGemsProvider,
    CratesIoProvider,
    LibRsProvider,
    DockerHubProvider,
    PkgGoDevProvider,
    MetaCPANProvider,
    MavenProvider,
    # Academic
    ArxivProvider,
    PubMedProvider,
    SemanticScholarProvider,
    CrossrefProvider,
    OpenAlexProvider,
    OpenLibraryProvider,
    ZenodoProvider,
    OrcidProvider,
    # Finance
    YahooFinanceProvider,
    AlphaVantageProvider,
    FinnhubProvider,
]


def build_registry() -> dict[str, BaseProvider]:
    """Instantiate all providers and return a name -> instance mapping.

    Providers whose ``is_available()`` returns ``False`` are always excluded
    (unavailable providers are never force-enabled).  When ``ENABLED_PROVIDERS``
    is set, only the explicitly listed providers are kept — all others are excluded.
    """
    settings = get_settings()
    explicit = set(settings.enabled_provider_list())

    registry: dict[str, BaseProvider] = {}
    for cls in _ALL_PROVIDER_CLASSES:
        instance = cls()
        if not instance.is_available():
            continue
        if explicit and instance.name not in explicit:
            continue
        registry[instance.name] = instance

    return registry
