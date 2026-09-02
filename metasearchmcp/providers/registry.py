"""Registry of search providers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from metasearchmcp.config import get_settings

# Tor / onion services
from .ahmia import AhmiaProvider

# Finance
from .alpha_vantage import AlphaVantageProvider
from .artic import ArticProvider

# Academic
from .arxiv import ArxivProvider

# General web search
from .baidu import BaiduProvider
from .bing import BingProvider
from .bing_news import BingNewsProvider
from .bluesky import BlueskyProvider
from .brave import BraveProvider
from .chembl import ChEMBLProvider
from .clevelandart import ClevelandArtProvider
from .clinicaltrials import ClinicalTrialsProvider
from .cocktaildb import CocktailDBProvider
from .codeberg import CodebergProvider
from .coingecko import CoinGeckoProvider
from .courtlistener import CourtListenerProvider
from .crates import CratesIoProvider
from .crossref import CrossrefProvider
from .dailymotion import DailymotionProvider
from .datacite import DataCiteProvider
from .datamuse import DatamuseProvider
from .dblp import DBLPProvider
from .discogs import DiscogsProvider
from .doaj import DoajProvider
from .dockerhub import DockerHubProvider
from .duckduckgo import DuckDuckGoProvider
from .ecosia import EcosiaProvider
from .europepmc import EuropePmcProvider
from .finnhub import FinnhubProvider
from .flickr import FlickrProvider
from .frankfurter import FrankfurterProvider
from .gbif import GBIFSpeciesProvider
from .gdelt import GDELTProvider
from .github import GitHubProvider
from .gitlab import GitLabProvider

# Google providers
from .google import GoogleProvider
from .google_books import GoogleBooksProvider
from .google_news import GoogleNewsProvider
from .google_patents import GooglePatentsProvider
from .google_serpbase import GoogleSerpbaseProvider
from .google_serper import GoogleSerperProvider
from .gutendex import GutendexProvider
from .hackernews import HackerNewsProvider
from .huggingface import HuggingFaceProvider

# Knowledge / reference
from .inaturalist import INaturalistProvider
from .internet_archive import InternetArchiveProvider
from .itunes import ITunesProvider
from .kitsu import KitsuProvider
from .lemmy import LemmyProvider
from .lib_rs import LibRsProvider
from .lobsters import LobstersProvider
from .loc_gov import LocGovProvider
from .marginalia import MarginaliaProvider
from .mastodon import MastodonProvider
from .maven import MavenProvider
from .metacpan import MetaCPANProvider
from .metmuseum import MetMuseumProvider
from .mojeek import MojeekProvider
from .musicbrainz import MusicBrainzProvider
from .mwmbl import MwmblProvider
from .nasa import NasaProvider
from .naver import NaverProvider
from .nominatim import NominatimProvider
from .npm import NpmProvider
from .nvd import NvdProvider
from .openalex import OpenAlexProvider
from .openfda import OpenFDADrugProvider
from .openfoodfacts import OpenFoodFactsProvider
from .openlibrary import OpenLibraryProvider
from .openmeteo import OpenMeteoProvider
from .openverse import OpenverseProvider
from .orcid import OrcidProvider
from .osf_preprints import OSFPreprintsProvider
from .peertube import PeerTubeProvider
from .pkg_go_dev import PkgGoDevProvider
from .pubmed import PubMedProvider
from .pypi import PyPIProvider
from .qwant import QwantProvider
from .radio_browser import RadioBrowserProvider
from .reddit import RedditProvider
from .remoteok import RemoteOKProvider
from .rubygems import RubyGemsProvider
from .rxnorm import RxNormProvider
from .sec_edgar import SecEdgarProvider
from .semanticscholar import SemanticScholarProvider
from .seznam import SeznamProvider
from .sourcegraph import SourcegraphProvider
from .spaceflight_news import SpaceflightNewsProvider
from .stackoverflow import StackOverflowProvider
from .startpage import StartpageProvider
from .steam import SteamProvider
from .themealdb import TheMealDBProvider
from .tvmaze import TVMazeProvider
from .uniprot import UniProtProvider
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
    NaverProvider,
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
    LocGovProvider,
    # Knowledge / reference
    DatamuseProvider,
    # Places / geocoding
    OpenMeteoProvider,
    NominatimProvider,
    # Nature / biodiversity
    INaturalistProvider,
    GBIFSpeciesProvider,
    # Legal
    CourtListenerProvider,
    # Patents
    GooglePatentsProvider,
    # News
    GoogleNewsProvider,
    GDELTProvider,
    WikinewsProvider,
    BingNewsProvider,
    SpaceflightNewsProvider,
    # Media / image search
    WikimediaCommonsProvider,
    OpenverseProvider,
    FlickrProvider,
    UnsplashProvider,
    MetMuseumProvider,
    ArticProvider,
    ClevelandArtProvider,
    NasaProvider,
    # Media / video search
    PeerTubeProvider,
    DailymotionProvider,
    TVMazeProvider,
    # Media / radio
    RadioBrowserProvider,
    # Media / music
    MusicBrainzProvider,
    DiscogsProvider,
    # Media / anime & manga
    KitsuProvider,
    # Media / podcasts
    ITunesProvider,
    # Media / games
    SteamProvider,
    # Media / food & recipes
    TheMealDBProvider,
    CocktailDBProvider,
    OpenFoodFactsProvider,
    # Media / jobs & careers
    RemoteOKProvider,
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
    # Security / vulnerabilities
    NvdProvider,
    # Drugs / pharma
    ChEMBLProvider,
    OpenFDADrugProvider,
    RxNormProvider,
    # Academic
    ArxivProvider,
    PubMedProvider,
    EuropePmcProvider,
    ClinicalTrialsProvider,
    SemanticScholarProvider,
    CrossrefProvider,
    OpenAlexProvider,
    DoajProvider,
    DBLPProvider,
    OpenLibraryProvider,
    GoogleBooksProvider,
    GutendexProvider,
    DataCiteProvider,
    ZenodoProvider,
    OSFPreprintsProvider,
    OrcidProvider,
    UniProtProvider,
    # Finance
    YahooFinanceProvider,
    AlphaVantageProvider,
    FinnhubProvider,
    CoinGeckoProvider,
    FrankfurterProvider,
    SecEdgarProvider,
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
