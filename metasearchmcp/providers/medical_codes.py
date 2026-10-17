"""Search medical code lookups via the keyless NLM Clinical Tables API.

The U.S. National Library of Medicine's *Clinical Tables* service
(https://clinicaltables.nlm.nih.gov) exposes a keyless REST search over the
coding systems used in clinical records and health applications.  This
provider queries three of them:

* **ICD-10-CM** — the clinical modification of ICD-10 used to record
  diagnoses.
* **ICD-11** — the World Health Organization's latest international
  classification of diseases.
* **HCPCS** — the Healthcare Common Procedure Coding System used for
  procedures, supplies and services.

Every database shares the same request and response shape::

    GET https://clinicaltables.nlm.nih.gov/api/<db>/v3/search
        ?terms=<query>&maxList=<n>

The query matches either the code itself (``E11.9``, ``5A61.5``, ``K0001``)
or the human-readable name (``diabetes``, ``wheelchair``).  ``maxList`` caps
the rows returned (NLM defaults to 7).  The response is a positional JSON
array::

    [<match count>, [<ids...>], null, [[<code>, <name>, ...], ...]]

so each result carries the coding system, the code and its official
description, plus a link to that system's interactive NLM lookup page.  A
blank query performs no request and a query with no matches yields an empty
set.  No API key is required.
"""

from __future__ import annotations

from itertools import zip_longest
from typing import ClassVar
from urllib.parse import quote

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_API_BASE = "https://clinicaltables.nlm.nih.gov/api"
_LOOKUP_URL = "https://clinicaltables.nlm.nih.gov/demo.html"
_SOURCE = "clinicaltables.nlm.nih.gov"
# NLM asks autocomplete-style callers to keep queries small; stay in step
# with the contracts result ceiling.
_MAX_API_RESULTS = 50

# (human-readable system label, Clinical Tables database id, extra query params).
#
# The optional ``sf`` parameter selects the fields NLM matches the query
# against, and its usable value differs per database: ``icd10cm`` matches
# keywords only when the name field is listed, whereas ``icd11_codes`` and
# ``hcpcs`` match their own default field set and return nothing once ``sf``
# is restricted.  Omitting ``sf`` where it is not required keeps both keyword
# and code lookups working for every system.
_CODE_SYSTEMS: tuple[tuple[str, str, dict[str, str]], ...] = (
    ("ICD-10-CM", "icd10cm", {"sf": "code,name"}),
    ("ICD-11", "icd11_codes", {}),
    ("HCPCS", "hcpcs", {}),
)


def _text(value: object) -> str:
    """Return a whitespace-collapsed string for str values, else ``""``."""
    if isinstance(value, str):
        return " ".join(value.split())
    return ""


def _rows(payload: object) -> list[tuple[str, str]]:
    """Extract ``(code, name)`` pairs from a Clinical Tables response.

    The endpoint returns a positional JSON array whose fourth element lists
    the matching records, each a ``[code, name, ...]`` list.  Any other
    payload shape yields an empty list.
    """
    if not isinstance(payload, list) or len(payload) < 4:
        return []
    rows = payload[3]
    if not isinstance(rows, list):
        return []
    pairs: list[tuple[str, str]] = []
    for row in rows:
        if not isinstance(row, list) or len(row) < 2:
            continue
        code = _text(row[0])
        name = _text(row[1])
        if code and name:
            pairs.append((code, name))
    return pairs


class MedicalCodesProvider(BaseProvider):
    """Search medical code sets via the keyless NLM Clinical Tables API.

    Keyless.  The query matches a code (``E11.9``, ``5A61.5``, ``K0001``) or a
    name (``diabetes``, ``wheelchair``); each hit carries the coding system,
    the code and its official description.
    """

    name = "medical_codes"
    description = (
        "Search U.S. NLM Clinical Tables for medical codes: ICD-10-CM and "
        "ICD-11 diagnosis codes plus HCPCS procedure/supply codes, by code "
        "or keyword (e.g. 'diabetes', 'E11.9' or 'wheelchair'). Each result "
        "carries the coding system, the code and its official description, "
        "with a clinicaltables.nlm.nih.gov lookup link. No API key required."
    )
    tags: ClassVar[list[str]] = ["medical", "health", "reference"]

    def _build_result(
        self,
        code: str,
        name: str,
        system: str,
        database: str,
        rank: int,
    ) -> SearchResult:
        """Build one :class:`SearchResult` from a single code record."""
        return SearchResult(
            title=f"{code} — {name}",
            url=f"{_LOOKUP_URL}?db={database}&terms={quote(code)}",
            snippet=f"{system} code {code}: {name}"[:MAX_SNIPPET_LENGTH],
            source=_SOURCE,
            rank=rank,
            provider=self.name,
            extra={
                "code": code,
                "name": name,
                "system": system,
                "database": database,
            },
        )

    @staticmethod
    def _interleave(
        groups: list[list[SearchResult]],
        limit: int,
    ) -> list[SearchResult]:
        """Round-robin merge *groups* so every system appears early.

        A single result from each group is taken before any group is used
        twice; the merged list is truncated to *limit*.
        """
        merged: list[SearchResult] = []
        for row in zip_longest(*groups):
            for result in row:
                if result is None:
                    continue
                merged.append(result)
                if len(merged) >= limit:
                    return merged
        return merged

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search the configured coding systems for *query*.

        A blank query performs no request.  Each coding system is queried once
        and the per-system matches are interleaved so the final page mixes
        diagnoses and procedures rather than favouring a single system.
        """
        cleaned = _text(query)
        if not cleaned:
            return ProviderResult(results=[])

        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)

        groups: list[list[SearchResult]] = []
        async with self._client() as client:
            for system, database, extra_params in _CODE_SYSTEMS:
                resp = await client.get(
                    f"{_API_BASE}/{database}/v3/search",
                    params={"terms": cleaned, "maxList": limit, **extra_params},
                )
                resp.raise_for_status()
                groups.append(
                    [
                        self._build_result(code, name, system, database, 0)
                        for code, name in _rows(resp.json())[:limit]
                    ]
                )

        results = self._interleave(groups, limit)
        for rank, result in enumerate(results, start=1):
            result.rank = rank
        return ProviderResult(results=results)
