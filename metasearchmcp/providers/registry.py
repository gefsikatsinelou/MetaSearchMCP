from __future__ import annotations

from metasearchmcp.config import get_settings
from .base import BaseProvider

# Google providers
from .google_serpbase import GoogleSerpbaseProvider
from .google_serper import GoogleSerperProvider

# Web search — HTML scraping
from .duckduckgo import DuckDuckGoProvider
from .bing import BingProvider
from .yahoo import YahooProvider
from .ecosia import EcosiaProvider
from .mojeek import MojeekProvider
from .startpage import StartpageProvider
from .qwant import QwantProvider
from .yandex import YandexProvider
from .baidu import BaiduProvider

# Web search — API
from .brave import BraveProvider
from .tavily import TavilyProvider

# Knowledge / reference
from .wikipedia import WikipediaProvider
from .wikidata import WikidataProvider
from .internet_archive import InternetArchiveProvider

# Developer
from .github import GitHubProvider
from .stackoverflow import StackOverflowProvider
from .hackernews import HackerNewsProvider
from .reddit import RedditProvider
from .npm import NpmProvider
from .pypi import PyPIProvider
from .rubygems import RubyGemsProvider
from .crates import CratesIoProvider
from .dockerhub import DockerHubProvider

# Academic
from .arxiv import ArxivProvider
from .pubmed import PubMedProvider
from .semanticscholar import SemanticScholarProvider
from .crossref import CrossrefProvider
from .openlibrary import OpenLibraryProvider


# Ordered list of all provider classes.
# Order matters: within a tag group, earlier providers take priority in dedup.
_ALL_PROVIDER_CLASSES: list[type[BaseProvider]] = [
    # Google
    GoogleSerpbaseProvider,
    GoogleSerperProvider,
    # General web search
    DuckDuckGoProvider,
    BingProvider,
    YahooProvider,
    BraveProvider,
    TavilyProvider,
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
    StackOverflowProvider,
    HackerNewsProvider,
    RedditProvider,
    NpmProvider,
    PyPIProvider,
    RubyGemsProvider,
    CratesIoProvider,
    DockerHubProvider,
    # Academic
    ArxivProvider,
    PubMedProvider,
    SemanticScholarProvider,
    CrossrefProvider,
    OpenLibraryProvider,
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
    return {n: p for n, p in registry.items() if tag in p.tags}
