"""Public proteomics dataset search via the keyless PRIDE Archive API.

`PRIDE <https://www.ebi.ac.uk/pride/>`_ (PRoteomics IDEntifications database)
is EMBL-EBI's public archive of mass-spectrometry proteomics data — one of the
largest repositories of its kind, holding raw and processed datasets submitted
alongside published studies.  It complements the genomics, chemistry and drug
providers by indexing *proteomics* experiments.

Its read-only search API is keyless::

    GET https://www.ebi.ac.uk/pride/ws/archive/v2/search/projects?keyword=QUERY

The response is a JSON array of project records, each carrying an ``accession``
(e.g. ``PXD039769``), ``title``, ``projectDescription``, the submission and
publication dates, the ``organisms`` studied, ``instruments`` used, ``keywords``,
principal investigators (``labPIs``) and their ``affiliations``,
``experimentTypes``, ``quantificationMethods`` and a ``downloadCount``.

Each result links to the project's page in the archive and exposes the
structured metadata in ``extra``.  No API key is required.
"""

from __future__ import annotations

from typing import Any, ClassVar
from urllib.parse import quote

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_API_URL = "https://www.ebi.ac.uk/pride/ws/archive/v2/search/projects"
# Canonical landing page for a single project accession.
_PROJECT_URL = "https://www.ebi.ac.uk/pride/archive/projects"
# Upper bound on datasets surfaced for a single query.
_MAX_RESULTS = 15


def _clean(value: object) -> str:
    """Collapse whitespace/control characters in a free-text field."""
    if value is None:
        return ""
    return " ".join(str(value).split())


def _as_int(value: object) -> int | None:
    """Coerce a JSON number/string to ``int``, returning ``None`` on failure."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float, str)):
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
    return None


def _str_list(value: object) -> list[str]:
    """Return a cleaned, de-duplicated list of strings from a JSON array field."""
    if not isinstance(value, list):
        return []
    items = [text for text in (_clean(item) for item in value) if text]
    return list(dict.fromkeys(items))


class PrideProvider(BaseProvider):
    """Search proteomics datasets in the EMBL-EBI PRIDE Archive.

    Keyless.  Uses the public PRIDE ``/ws/archive/v2/search/projects`` endpoint.
    Each result is one dataset (e.g. ``PXD039769``) with its title, description,
    the organisms and instruments involved, contributing laboratories and links
    to the archive page.
    """

    name = "pride"
    description = (
        "Search proteomics datasets (mass-spectrometry experiments) in the "
        "EMBL-EBI PRIDE Archive by keyword, returning the project accession, "
        "title, description, organisms, instruments, principal investigators, "
        "experiment and quantification methods and download counts — no API "
        "key required."
    )
    tags: ClassVar[list[str]] = ["bio", "academic", "science", "data", "datasets"]

    def _project_result(self, item: object, rank: int) -> SearchResult | None:
        """Build one result from a single PRIDE project record."""
        if not isinstance(item, dict):
            return None

        accession = _clean(item.get("accession"))
        title = _clean(item.get("title")) or accession
        if not title:
            return None

        description = _clean(item.get("projectDescription"))
        organisms = _str_list(item.get("organisms"))
        instruments = _str_list(item.get("instruments"))
        keywords = _str_list(item.get("keywords"))
        lab_pis = _str_list(item.get("labPIs"))
        affiliations = _str_list(item.get("affiliations"))
        experiment_types = _str_list(item.get("experimentTypes"))
        quantification = _str_list(item.get("quantificationMethods"))
        diseases = _str_list(item.get("diseases"))
        download_count = _as_int(item.get("downloadCount"))
        publication_date = self._iso_date_prefix(
            _clean(item.get("publicationDate")) or _clean(item.get("submissionDate")),
        )

        snippet_parts: list[str] = []
        if description:
            snippet_parts.append(description)
        if organisms:
            snippet_parts.append("organisms: " + ", ".join(organisms))
        if instruments:
            snippet_parts.append("instruments: " + ", ".join(instruments))
        if experiment_types:
            snippet_parts.append("experiment types: " + ", ".join(experiment_types))
        if keywords:
            snippet_parts.append("keywords: " + ", ".join(keywords))
        if lab_pis:
            snippet_parts.append("PI: " + ", ".join(lab_pis))

        url = (
            f"{_PROJECT_URL}/{quote(accession, safe='')}" if accession else _PROJECT_URL
        )
        return SearchResult(
            title=title,
            url=url,
            snippet=" | ".join(snippet_parts)[:MAX_SNIPPET_LENGTH],
            source="ebi.ac.uk",
            provider=self.name,
            rank=rank,
            published_date=publication_date,
            extra={
                "accession": accession,
                "organisms": organisms,
                "instruments": instruments,
                "keywords": keywords,
                "lab_pis": lab_pis,
                "affiliations": affiliations,
                "experiment_types": experiment_types,
                "quantification_methods": quantification,
                "diseases": diseases,
                "submission_type": _clean(item.get("submissionType")),
                "download_count": download_count,
                "doi": _clean(item.get("doi")),
            },
        )

    def _parse(self, payload: object, limit: int | None = None) -> ProviderResult:
        """Parse a PRIDE ``/search/projects`` response into structured results."""
        if not isinstance(payload, list):
            return ProviderResult(results=[])

        max_results = limit or self._max_results
        results: list[SearchResult] = []
        for item in payload:
            if len(results) >= max_results:
                break
            result = self._project_result(item, rank=len(results) + 1)
            if result is None:
                continue
            results.append(result)

        return ProviderResult(results=results)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search the PRIDE Archive for proteomics datasets matching *query*."""
        cleaned = query.strip()
        if not cleaned:
            return ProviderResult(results=[])

        limit = min(params.num_results, self._max_results, _MAX_RESULTS)
        async with self._client() as client:
            resp = await client.get(
                _API_URL,
                params={"keyword": cleaned, "pageSize": limit, "page": 0},
            )
            resp.raise_for_status()
            payload: Any = resp.json()

        return self._parse(payload, limit=limit)
