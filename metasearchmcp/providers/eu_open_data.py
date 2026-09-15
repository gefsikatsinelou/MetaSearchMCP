"""Search the European open data portal (data.europa.eu) for datasets.

``data.europa.eu`` is the official portal for European open data.  It harvests
the metadata of well over a million datasets from the national portals of the
EU member states (``data.gouv.fr``, ``govdata.de``, ``data.gov.be``, ...) as
well as from the institutions of the European Union.  Its search endpoint is
public and keyless::

    GET https://data.europa.eu/api/hub/search/search?q=QUERY&limit=N&page=1

The response is ``{"result": {"count": <total matches>, "results": [...]}}``.
Every dataset record carries a multilingual ``title`` and ``description`` (a
mapping of language code to text, including machine translations), the
dataset's identifier, the harvesting ``catalog`` and its ``publisher``, the
``country``, the subject ``categories``, the ``keywords``, the available
distribution formats and licences, and the record's issue/modification dates.

This complements the scholarly, legal and news providers with a catalogue of
public-sector *datasets*: it answers which open government dataset covers a
subject, who publishes it, where it is hosted and in which formats it can be
downloaded.  No API key is required.
"""

from __future__ import annotations

from typing import Any, ClassVar
from urllib.parse import quote

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_SEARCH_URL = "https://data.europa.eu/api/hub/search/search"
# Human-readable dataset page; ``locale`` keeps the page in English.
_DATASET_PAGE_URL = "https://data.europa.eu/data/datasets/"
# The portal pages its result lists; keep pages small for agents.
_MAX_API_RESULTS = 50
# Language used when the requested one is not among a record's translations.
_DEFAULT_LANGUAGE = "en"
# Characters of the dataset description copied into the snippet.
_SNIPPET_DESCRIPTION_LENGTH = 180
# Distribution formats and keywords listed before closing with an ellipsis.
_SNIPPET_FORMAT_LIMIT = 4
_SNIPPET_KEYWORD_LIMIT = 5
_SNIPPET_CATEGORY_LIMIT = 3


def _clean(value: object) -> str:
    """Collapse whitespace in a free-text field."""
    if not value:
        return ""
    return " ".join(str(value).split())


class EuOpenDataProvider(BaseProvider):
    """Search the European open data portal for public-sector datasets.

    Keyless.  Queries the data.europa.eu search API in a single request and
    returns one hit per dataset, carrying the dataset title and description,
    its publisher, harvesting catalogue, country, subject categories,
    keywords, distribution formats and licence, and linking to the dataset
    page on data.europa.eu.
    """

    name = "eu_open_data"
    description = (
        "Search data.europa.eu — the official European open data portal — for "
        "public-sector datasets from EU member states and institutions "
        "(title, description, publisher, catalogue, country, formats, "
        "licence) via the keyless search API, no API key required."
    )
    tags: ClassVar[list[str]] = ["web", "gov", "data", "knowledge"]

    @staticmethod
    def _localized(value: object, language: str) -> str:
        """Return the best text of a multilingual field.

        Fields such as ``title`` and ``description`` arrive either as a plain
        string or as a mapping of language code to text.  For a mapping the
        requested language wins, then English, then whatever translation the
        record happens to carry first.
        """
        if isinstance(value, str):
            return _clean(value)
        if not isinstance(value, dict):
            return ""
        for code in (language, _DEFAULT_LANGUAGE):
            text = value.get(code)
            if isinstance(text, str) and text.strip():
                return _clean(text)
        for text in value.values():
            if isinstance(text, str) and text.strip():
                return _clean(text)
        return ""

    @classmethod
    def _first_resource(cls, value: object) -> str:
        """Return the first URL held in a string, mapping or their list."""
        if isinstance(value, str):
            return _clean(value)
        if isinstance(value, dict):
            return _clean(value.get("resource"))
        if isinstance(value, list):
            for entry in value:
                resource = cls._first_resource(entry)
                if resource:
                    return resource
        return ""

    @classmethod
    def _publisher(cls, item: dict[str, Any]) -> str:
        """Return the dataset publisher, falling back to its first creator."""
        publisher = item.get("publisher")
        if isinstance(publisher, dict):
            name = _clean(publisher.get("name"))
            if name:
                return name
        elif isinstance(publisher, str) and publisher.strip():
            return _clean(publisher)

        creators = item.get("creator")
        if isinstance(creators, list):
            for creator in creators:
                if isinstance(creator, dict):
                    name = _clean(creator.get("name"))
                    if name:
                        return name
        return ""

    def _catalog(self, item: dict[str, Any], language: str) -> str:
        """Return the harvesting catalogue's title."""
        catalog = item.get("catalog")
        if not isinstance(catalog, dict):
            return ""
        return self._localized(catalog.get("title"), language)

    @staticmethod
    def _country(item: dict[str, Any]) -> str:
        """Return the country the dataset belongs to."""
        country = item.get("country")
        if not isinstance(country, dict):
            return ""
        return _clean(country.get("label") or country.get("id"))

    @staticmethod
    def _distributions(item: dict[str, Any]) -> list[dict[str, Any]]:
        """Return the dataset's distribution records."""
        distributions = item.get("distributions")
        if not isinstance(distributions, list):
            return []
        return [dist for dist in distributions if isinstance(dist, dict)]

    @classmethod
    def _formats(cls, item: dict[str, Any]) -> list[str]:
        """Return the distinct distribution formats, e.g. ``csv``, ``json``."""
        formats: list[str] = []
        for distribution in cls._distributions(item):
            raw = distribution.get("format")
            if isinstance(raw, dict):
                label = _clean(raw.get("label") or raw.get("id"))
            else:
                label = _clean(raw)
            if label and label not in formats:
                formats.append(label)
            if len(formats) >= _SNIPPET_FORMAT_LIMIT:
                break
        return formats

    @classmethod
    def _license(cls, item: dict[str, Any]) -> str:
        """Return the licence declared by the first distribution that has one."""
        for distribution in cls._distributions(item):
            raw = distribution.get("license")
            if isinstance(raw, dict):
                label = _clean(raw.get("label") or raw.get("id"))
                if label:
                    return label
            elif isinstance(raw, str) and raw.strip():
                return _clean(raw)
        return ""

    @classmethod
    def _keywords(cls, item: dict[str, Any]) -> list[str]:
        """Return the dataset's keyword labels."""
        keywords = item.get("keywords")
        if not isinstance(keywords, list):
            return []
        labels: list[str] = []
        for keyword in keywords:
            if not isinstance(keyword, dict):
                continue
            label = _clean(keyword.get("label") or keyword.get("id"))
            if label and label not in labels:
                labels.append(label)
            if len(labels) >= _SNIPPET_KEYWORD_LIMIT:
                break
        return labels

    def _categories(self, item: dict[str, Any], language: str) -> list[str]:
        """Return the dataset's subject category labels."""
        categories = item.get("categories")
        if not isinstance(categories, list):
            return []
        labels: list[str] = []
        for category in categories:
            if not isinstance(category, dict):
                continue
            label = self._localized(category.get("label"), language)
            if label and label not in labels:
                labels.append(label)
            if len(labels) >= _SNIPPET_CATEGORY_LIMIT:
                break
        return labels

    @staticmethod
    def _updated(item: dict[str, Any]) -> str:
        """Return the dataset's last modification date as ``YYYY-MM-DD``.

        Records expose the dataset date in ``modified``/``issued`` and the
        harvesting record date in ``catalog_record``; the dataset date wins.
        """
        candidates: list[object] = [item.get("modified"), item.get("issued")]
        record = item.get("catalog_record")
        if isinstance(record, dict):
            candidates.extend((record.get("modified"), record.get("issued")))
        for candidate in candidates:
            if isinstance(candidate, str) and candidate.strip():
                return candidate[:10]
        return ""

    @staticmethod
    def _access_right(item: dict[str, Any]) -> str:
        """Return the declared access right, e.g. ``public``."""
        access = item.get("access_right")
        if not isinstance(access, dict):
            return ""
        return _clean(access.get("label") or access.get("id"))

    @staticmethod
    def _snippet(
        description: str,
        publisher: str,
        catalog: str,
        country: str,
        formats: list[str],
        licence: str,
        distributions: int,
    ) -> str:
        """Compose the snippet for a single dataset."""
        parts: list[str] = []
        if description:
            parts.append(description[:_SNIPPET_DESCRIPTION_LENGTH])
        if publisher:
            parts.append(f"Publisher: {publisher}")
        if catalog:
            parts.append(f"Catalogue: {catalog}")
        if country:
            parts.append(country)
        if formats:
            parts.append(f"Formats: {', '.join(formats)}")
        if licence:
            parts.append(f"License: {licence}")
        if distributions:
            parts.append(f"Distributions: {distributions}")
        return " | ".join(parts)[:MAX_SNIPPET_LENGTH]

    def _build_result(
        self,
        item: dict[str, Any],
        language: str,
        rank: int,
    ) -> SearchResult | None:
        """Build one :class:`SearchResult` from a raw dataset record."""
        title = self._localized(item.get("title"), language)
        if not title:
            return None

        identifier = _clean(item.get("id"))
        landing_page = self._first_resource(item.get("landing_page"))
        raw_resource = self._first_resource(item.get("resource"))
        if not raw_resource:
            raw_resource = self._first_resource(item.get("identifier"))
        if identifier:
            url = f"{_DATASET_PAGE_URL}{quote(identifier)}?locale={_DEFAULT_LANGUAGE}"
        else:
            url = raw_resource or landing_page
        if not url:
            return None

        publisher = self._publisher(item)
        catalog = self._catalog(item, language)
        country = self._country(item)
        formats = self._formats(item)
        licence = self._license(item)
        keywords = self._keywords(item)
        categories = self._categories(item, language)
        distributions = len(self._distributions(item))
        updated = self._updated(item)

        return SearchResult(
            title=title,
            url=url,
            snippet=self._snippet(
                self._localized(item.get("description"), language),
                publisher,
                catalog,
                country,
                formats,
                licence,
                distributions,
            ),
            source="data.europa.eu",
            rank=rank,
            provider=self.name,
            published_date=updated or None,
            extra={
                "id": identifier or None,
                "publisher": publisher or None,
                "catalog": catalog or None,
                "country": country or None,
                "categories": categories,
                "keywords": keywords,
                "formats": formats,
                "license": licence or None,
                "distributions": distributions,
                "updated": updated or None,
                "landing_page": landing_page or None,
                "resource": raw_resource or None,
                "access_right": self._access_right(item) or None,
                "high_value_dataset": bool(item.get("is_hvd")),
            },
        )

    def _parse(
        self,
        data: object,
        language: str,
        limit: int,
    ) -> list[SearchResult]:
        """Parse a portal search response, deduplicating hits by dataset id."""
        if not isinstance(data, dict):
            return []
        result = data.get("result")
        if not isinstance(result, dict):
            return []
        items = result.get("results")
        if not isinstance(items, list):
            return []

        results: list[SearchResult] = []
        seen: set[object] = set()
        for item in items:
            if len(results) >= limit:
                break
            if not isinstance(item, dict):
                continue
            # A dataset is keyed by its portal identifier.
            key = item.get("id")
            if key is not None:
                if key in seen:
                    continue
                seen.add(key)
            built = self._build_result(item, language, len(results) + 1)
            if built is None:
                continue
            results.append(built)
        return results

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search data.europa.eu for datasets matching *query*.

        A blank query performs no request.  The portal ranks matches by its own
        relevance score, which is preserved in the returned order.
        """
        cleaned = query.strip()
        if not cleaned:
            return ProviderResult(results=[])

        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)
        language = self._language_code(params.language)

        async with self._client() as client:
            resp = await client.get(
                _SEARCH_URL,
                params={"q": cleaned, "limit": limit, "page": 1},
            )
            resp.raise_for_status()
            data = resp.json()

        return ProviderResult(results=self._parse(data, language, limit))
