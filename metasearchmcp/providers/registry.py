"""Registry search provider."""

from __future__ import annotations

from metasearchmcp.config import get_settings

from .alpha_vantage import AlphaVantageProvider

# Academic
from .arxiv import ArxivProvider
from .baidu import BaiduProvider
from .base import BaseProvider
from .bing import BingProvider

# Web search — API
from .brave import BraveProvider
from .crates import CratesIoProvider
from .crossref import CrossrefProvider
from .dockerhub import DockerHubProvider

# Web search — HTML scraping
from .duckduckgo import DuckDuckGoProvider
from .ecosia import EcosiaProvider
from .finnhub import FinnhubProvider

# Developer
from .github import GitHubProvider
from .gitlab import GitLabProvider

# Google providers
from .google import GoogleProvider
from .google_serpbase import GoogleSerpbaseProvider
from .google_serper import GoogleSerperProvider
from .hackernews import HackerNewsProvider
from .internet_archive import InternetArchiveProvider
from .lib_rs import LibRsProvider
from .metacpan import MetaCPANProvider
from .mojeek import MojeekProvider
from .mwmbl import MwmblProvider
from .npm import NpmProvider
from .openlibrary import OpenLibraryProvider
from .pkg_go_dev import PkgGoDevProvider
from .pubmed import PubMedProvider
from .pypi import PyPIProvider
from .qwant import QwantProvider
from .reddit import RedditProvider
from .rubygems import RubyGemsProvider
from .semanticscholar import SemanticScholarProvider
from .stackoverflow import StackOverflowProvider
from .startpage import StartpageProvider
from .wikidata import WikidataProvider

# Knowledge / reference
from .wikipedia import WikipediaProvider
from .yahoo import YahooProvider

# Finance
from .yahoo_finance import YahooFinanceProvider
from .yandex import YandexProvider

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
    MwmblProvider,
    EcosiaProvider,
    MojeekProvider,
    StartpageProvider,
    QwantProvider,
    YandexProvider,
    BaiduProvider,
    # Knowledge base
    WikipediaProvider,
    WikidataProvider,
    InternetArchiveProvider,
    # Developer
    GitHubProvider,
    GitLabProvider,
    StackOverflowProvider,
    HackerNewsProvider,
    RedditProvider,
    NpmProvider,
    PyPIProvider,
    RubyGemsProvider,
    CratesIoProvider,
    LibRsProvider,
    DockerHubProvider,
    PkgGoDevProvider,
    MetaCPANProvider,
    # Academic
    ArxivProvider,
    PubMedProvider,
    SemanticScholarProvider,
    CrossrefProvider,
    OpenLibraryProvider,
    # Finance
    YahooFinanceProvider,
    AlphaVantageProvider,
    FinnhubProvider,
]


def build_registry() -> dict[str, BaseProvider]:
    """Instantiate all providers and return a name -> instance mapping.

    Providers whose is_available() returns False are excluded unless they
    appear in the explicit ENABLED_PROVIDERS list (in which case they are
    still excluded — ENABLED_PROVIDERS restricts, it does not force-enable
    unavailable providers).
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


def filter_by_names(
    registry: dict[str, BaseProvider],
    names: list[str],
) -> dict[str, BaseProvider]:
    """Return subset of registry matching the given names, preserving order."""
    if not names:
        return registry
    return {n: registry[n] for n in names if n in registry}


def filter_by_tag(
    registry: dict[str, BaseProvider],
    tag: str,
) -> dict[str, BaseProvider]:
    """Return providers in *registry* that have *tag* in their tags."""
    return {n: p for n, p in registry.items() if tag in p.tags}
