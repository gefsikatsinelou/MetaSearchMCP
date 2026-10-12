"""Paleobiology Database (PBDB) fossil-taxon search via the keyless public API.

PBDB (paleobiodb.org) is an open, community-curated database of the fossil
record: every known prehistoric taxon together with its taxonomy, stratigraphic
age range, and counts of fossil occurrences.  Its data service requires no API
key:

* ``GET https://paleobiodb.org/data1.2/taxa/list.json?base_name=QUERY&show=...``
  — returns the named taxon together with the taxa it contains (species,
  synonyms and included subtaxa), which is the primary search mode.
* ``GET .../taxa/list.json?name=QUERY%`` — a name-prefix wildcard lookup used as
  a fallback so partial names (``tyranno``) still resolve to a taxon.

Each hit carries the scientific name, its rank, the naming authority, the
higher classification (phylum down to genus), the first/last appearance ages in
millions of years and the corresponding geological intervals, whether the taxon
is extinct or extant, a fossil-occurrence count and, where relevant, the
accepted name or taxonomic flag (e.g. a synonym or *nomen nudum*).  The provider
is keyless and complements the existing GBIF and iNaturalist providers with a
deep-time (paleontological) counterpart.
"""

from __future__ import annotations

from typing import Any, ClassVar

import httpx

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_API_URL = "https://paleobiodb.org/data1.2/taxa/list.json"
# Request the attribute, age-range, classification and common-name blocks.
_SHOW = "attr,app,class,common"
# PBDB caps a single response; keep pages small for agents.
_MAX_API_RESULTS = 50
# PBDB treats "%" as a name wildcard; strip it from user input before we append
# our own single trailing wildcard for the prefix fallback.
_WILDCARD = "%"
# PBDB uses "NO_*_SPECIFIED" sentinels (e.g. NO_ORDER_SPECIFIED,
# NO_FAMILY_SPECIFIED) for "no value" in the classification block.
_NO_VALUE = "NO_ORDER_SPECIFIED"

# PBDB numeric rank codes -> human-readable rank labels.
_RANK_CODES: dict[int, str] = {
    2: "subspecies",
    3: "species",
    4: "subgenus",
    5: "genus",
    6: "subtribe",
    7: "tribe",
    8: "subfamily",
    9: "family",
    10: "superfamily",
    11: "infraorder",
    12: "suborder",
    13: "order",
    14: "superorder",
    15: "infraclass",
    16: "subclass",
    17: "class",
    18: "superclass",
    19: "subphylum",
    20: "phylum",
    21: "superphylum",
    22: "subkingdom",
    23: "kingdom",
    25: "unranked clade",
    26: "informal",
}

# Classification fields, from the broadest to the most specific.
_CLASS_KEYS = ("phl", "cll", "odl", "fml", "gnl")


class PbdbProvider(BaseProvider):
    """Search fossil taxa in the Paleobiology Database.

    Keyless. Uses the public ``data1.2/taxa/list.json`` endpoint to find
    prehistoric taxa, first by base name (returning a clade and the taxa it
    contains) and then, when that yields nothing, by name-prefix wildcard.
    Each hit carries the scientific name, rank, author, higher classification,
    first/last appearance ages, the geological intervals, a fossil-occurrence
    count and any accepted-name/taxonomic-flag annotation.
    """

    name = "pbdb"
    description = (
        "Search the Paleobiology Database for fossil taxa — dinosaurs, extinct "
        "mammals and other prehistoric life — with taxonomy, age ranges and "
        "fossil-occurrence counts via the keyless public API."
    )
    tags: ClassVar[list[str]] = ["science", "nature", "reference", "paleontology"]

    @staticmethod
    def _clean(value: object) -> str:
        """Collapse whitespace in a free-text field, treating sentinels as empty."""
        if not value:
            return ""
        text = " ".join(str(value).split())
        if text == _NO_VALUE or (text.startswith("NO_") and text.endswith("SPECIFIED")):
            return ""
        return text

    @classmethod
    def _rank_label(cls, raw: object) -> str:
        """Resolve a PBDB rank code (int) or rank name (str) to a label."""
        if isinstance(raw, bool) or raw is None:
            return ""
        if isinstance(raw, int):
            return _RANK_CODES.get(raw, "")
        text = cls._clean(raw)
        if text.isdigit():
            return _RANK_CODES.get(int(text), "")
        return text

    @classmethod
    def _classification(cls, item: dict[str, Any]) -> str:
        """Compose the higher-classification chain, e.g. ``Chordata > Reptilia``."""
        chain = [cls._clean(item.get(key)) for key in _CLASS_KEYS]
        return " > ".join(level for level in chain if level)

    @classmethod
    def _interval(cls, item: dict[str, Any]) -> str:
        """Compose the geological-interval range, e.g. ``Campanian-Maastrichtian``."""
        early = cls._clean(item.get("tei"))
        late = cls._clean(item.get("tli"))
        if early and late and early != late:
            return f"{early}-{late}"
        return early or late

    @classmethod
    def _age_range(cls, item: dict[str, Any]) -> str:
        """Compose the numeric age range in millions of years, e.g. ``83.6-66 Ma``."""
        first = item.get("fea")
        last = item.get("lla")
        if isinstance(first, (int, float)) and isinstance(last, (int, float)):
            return f"{first}-{last} Ma"
        return ""

    def _build_result(self, item: dict[str, Any], rank: int) -> SearchResult | None:
        """Build one :class:`SearchResult` from a raw taxon record."""
        if not isinstance(item, dict):
            return None
        name = self._clean(item.get("nam"))
        if not name:
            return None

        oid = self._clean(item.get("oid"))
        taxon_id = oid.rsplit(":", 1)[-1] if ":" in oid else oid
        authority = self._clean(item.get("att"))
        common = self._clean(item.get("nm2"))
        rank_label = self._rank_label(item.get("rnk"))
        classification = self._classification(item)
        interval = self._interval(item)
        ages = self._age_range(item)

        outward = self._clean(item.get("ext"))
        status = {"0": "extinct", "1": "extant"}.get(outward, "")

        # PBDB flags some records as synonyms, nomen nudum, etc. ("tdf") and
        # points at the accepted name ("acn").
        taxon_flag = self._clean(item.get("tdf"))
        accepted_name = self._clean(item.get("acn"))
        if accepted_name == name:
            accepted_name = ""

        occurrences = item.get("noc")
        if isinstance(occurrences, bool) or not isinstance(occurrences, int):
            occurrences = None

        snippet_parts: list[str] = []
        if authority:
            snippet_parts.append(authority)
        if rank_label:
            snippet_parts.append(f"Rank: {rank_label}")
        if status:
            snippet_parts.append(status)
        if taxon_flag:
            snippet_parts.append(taxon_flag)
        if accepted_name:
            snippet_parts.append(f"Synonym of {accepted_name}")
        if classification:
            snippet_parts.append(classification)
        if interval:
            snippet_parts.append(f"Age: {interval}{f' ({ages})' if ages else ''}")
        elif ages:
            snippet_parts.append(f"Age: {ages}")
        if common:
            snippet_parts.append(f"Common name: {common}")
        if occurrences:
            snippet_parts.append(f"{occurrences} fossil occurrences")

        url = (
            f"https://paleobiodb.org/classic/checkTaxonInfo?taxon_no={taxon_id}"
            if taxon_id
            else "https://paleobiodb.org/"
        )
        return SearchResult(
            title=name,
            url=url,
            snippet=" | ".join(snippet_parts)[:MAX_SNIPPET_LENGTH],
            source="paleobiodb.org",
            rank=rank,
            provider=self.name,
            extra={
                "taxon_id": taxon_id or None,
                "rank": rank_label,
                "authority": authority or None,
                "common_name": common or None,
                "classification": classification,
                "first_appearance_ma": item.get("fea"),
                "last_appearance_ma": item.get("lla"),
                "early_interval": self._clean(item.get("tei")) or None,
                "late_interval": self._clean(item.get("tli")) or None,
                "extinct": outward == "0",
                "taxon_status": taxon_flag or None,
                "accepted_name": accepted_name or None,
                "occurrences": occurrences,
            },
        )

    def _parse(self, data: object, limit: int) -> ProviderResult:
        """Parse a PBDB taxa response into structured results.

        The response is an object with a ``records`` list; each element is one
        taxon record.  Non-dict entries and records without a scientific name
        are skipped, and the page is cut to *limit* results.
        """
        results: list[SearchResult] = []
        if not isinstance(data, dict):
            return ProviderResult(results=results)
        records = data.get("records")
        if not isinstance(records, list):
            return ProviderResult(results=results)

        for item in records:
            if len(results) >= limit:
                break
            result = self._build_result(item, rank=len(results) + 1)
            if result is not None:
                results.append(result)
        return ProviderResult(results=results)

    async def _fetch(
        self,
        client: httpx.AsyncClient,
        query_param: dict[str, Any],
        limit: int,
    ) -> ProviderResult:
        """Run one PBDB taxa request and parse it, tolerating non-JSON replies."""
        resp = await client.get(_API_URL, params=query_param)
        resp.raise_for_status()
        try:
            data = resp.json()
        except ValueError:
            # PBDB occasionally answers with a non-JSON error page.
            return ProviderResult(results=[])
        return self._parse(data, limit)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search PBDB for fossil taxa matching *query*."""
        cleaned = query.strip().replace(_WILDCARD, "").strip()
        if not cleaned:
            return ProviderResult(results=[])

        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)
        async with self._client() as client:
            # Primary: the base-name search returns a clade and the taxa it
            # contains.  Fall back to a name-prefix wildcard so partial names
            # still resolve to a single best match.
            result = await self._fetch(
                client,
                {"base_name": cleaned, "show": _SHOW, "limit": limit},
                limit,
            )
            if result.results:
                return result
            return await self._fetch(
                client,
                {"name": f"{cleaned}{_WILDCARD}", "show": _SHOW, "limit": limit},
                limit,
            )
