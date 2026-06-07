"""Registry of search providers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from metasearchmcp.config import get_settings

# Google providers
from .google import GoogleProvider
from .google_serpbase import GoogleSerpbaseProvider
from .google_serper import GoogleSerperProvider

# General web search
from .baidu import BaiduProvider
from .bing import BingProvider
from .brave import BraveProvider
from .duckduckgo import DuckDuckGoProvider
from .ecosia import EcosiaProvider
from .mojeek import MojeekProvider
from .mwmbl import MwmblProvider
from .qwant import QwantProvider
from .startpage import StartpageProvider
from .yahoo import YahooProvider
from .yandex import YandexProvider

# Knowledge / reference
from .internet_archive import InternetArchiveProvider
from .openlibrary import OpenLibraryProvider
from .wikipedia import WikipediaProvider
from .wikidata import WikidataProvider

# Developer
from .crates import CratesIoProvider
from .dockerhub import DockerHubProvider
from .github import GitHubProvider
from .gitlab import GitLabProvider
from .hackernews import HackerNewsProvider
from .lib_rs import LibRsProvider
from .metacpan import MetaCPANProvider
from .npm import NpmProvider
from .pkg_go_dev import PkgGoDevProvider
from .pypi import PyPIProvider
from .reddit import RedditProvider
from .rubygems import RubyGemsProvider
from .stackoverflow import StackOverflowProvider

# Academic
from .arxiv import ArxivProvider
from .crossref import CrossrefProvider
from .pubmed import PubMedProvider
from .semanticscholar import SemanticScholarProvider

# Finance
from .alpha_vantage import AlphaVantageProvider
from .finnhub import FinnhubProvider
from .yahoo_finance import YahooFinanceProvider

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
