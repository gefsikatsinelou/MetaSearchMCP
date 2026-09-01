"""RxNorm drug terminology search via the keyless public API.

RxNorm (rxnav.nlm.nih.gov) is the U.S. National Library of Medicine's
standardized nomenclature for clinical drugs and drug packs. Its public
REST API requires no API key:

``GET https://rxnav.nlm.nih.gov/REST/drugs.json?name=QUERY``

returns a ``drugGroup`` object whose ``conceptGroup`` entries group the
matching concepts by term type (SCD = semantic clinical drug, SBD =
branded drug, GPCK/BPCK = generic/brand packs, ...). Each concept carries
its RxCUI identifier, display name, synonym, and UMLS CUI. The provider
is keyless, uses only the shared httpx client, and tags itself
``drugs``/``pharma``/``medical``/``bio`` so it complements the openFDA
and ChEMBL providers in biomedical searches.
"""

from __future__ import annotations

from typing import Any, ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_API_URL = "https://rxnav.nlm.nih.gov/REST/drugs.json"
# RxNorm returns many concepts (branded + semantic) per term; cap it.
_MAX_API_RESULTS = 50

# Preferred term types (order matters): branded drugs first, then plain
# clinical drugs, then ingredient/grouped concepts.
_PREFERRED_TTYS = ("SBD", "SCD", "GPCK", "BPCK", "IN", "PIN", "MIN")


class RxNormProvider(BaseProvider):
    """Search RxNorm clinical drug terminology via the keyless NLM API.

    Keyless. Uses the public ``/REST/drugs.json?name=QUERY`` endpoint to
    find drug concepts. Each hit carries the RxCUI, term type, display
    name, and synonym, with a link to the RxNorm record on the NLM site.
    """

    name = "rxnorm"
    description = (
        "Search RxNorm clinical drug terminology — RxCUI codes, term "
        "types, and drug names via the keyless NLM REST API."
    )
    tags: ClassVar[list[str]] = ["drugs", "pharma", "medical", "bio"]

    @staticmethod
    def _clean(value: object) -> str:
        """Collapse whitespace in a free-text field."""
        if not value:
            return ""
        return " ".join(str(value).split())

    @staticmethod
    def _concept_key(concept: dict[str, Any]) -> tuple[int, int]:
        """Return a sort key for a concept: preferred tty first, then rxcui."""
        tty = RxNormProvider._clean(concept.get("tty")).upper()
        try:
            tty_rank = _PREFERRED_TTYS.index(tty)
        except ValueError:
            tty_rank = len(_PREFERRED_TTYS)
        try:
            rxcui = int(concept.get("rxcui") or 0)
        except (TypeError, ValueError):
            rxcui = 0
        return (tty_rank, rxcui)

    def _parse(self, data: Any, limit: int | None = None) -> ProviderResult:
        """Parse the /REST/drugs.json response into structured results.

        The response is an object with a ``drugGroup.conceptGroup`` list;
        each element is a term-type group holding ``conceptProperties``
        entries. Concepts are flattened, sorted by preferred term type,
        and deduplicated by RxCUI. Non-dict entries and concepts without
        a name or RxCUI are skipped.
        """
        results: list[SearchResult] = []
        max_results = limit or self._max_results
        if not isinstance(data, dict):
            return ProviderResult(results=results)

        drug_group = data.get("drugGroup")
        if not isinstance(drug_group, dict):
            return ProviderResult(results=results)

        concept_groups = drug_group.get("conceptGroup")
        if not isinstance(concept_groups, list):
            return ProviderResult(results=results)

        concepts: list[dict[str, Any]] = []
        for group in concept_groups:
            if not isinstance(group, dict):
                continue
            properties = group.get("conceptProperties")
            if not isinstance(properties, list):
                continue
            for concept in properties:
                if isinstance(concept, dict) and concept.get("rxcui"):
                    concepts.append(concept)

        seen_rxcui: set[int] = set()
        for concept in sorted(concepts, key=self._concept_key):
            if len(results) >= max_results:
                break
            try:
                rxcui = int(concept.get("rxcui") or 0)
            except (TypeError, ValueError):
                continue
            if not rxcui or rxcui in seen_rxcui:
                continue
            seen_rxcui.add(rxcui)

            name = self._clean(concept.get("name"))
            synonym = self._clean(concept.get("synonym"))
            tty = self._clean(concept.get("tty")).upper()
            title = name or synonym
            if not title:
                continue

            snippet_parts: list[str] = []
            if synonym and synonym != title:
                snippet_parts.append(synonym)
            if tty:
                snippet_parts.append(tty)
            snippet_parts.append(f"RxCUI {rxcui}")

            results.append(
                SearchResult(
                    title=title,
                    url=f"https://rxnav.nlm.nih.gov/id/rxnorm/{rxcui}",
                    snippet=" | ".join(snippet_parts)[:MAX_SNIPPET_LENGTH],
                    source="rxnav.nlm.nih.gov",
                    rank=len(results) + 1,
                    provider=self.name,
                    extra={
                        "rxcui": rxcui,
                        "term_type": tty,
                        "synonym": synonym,
                        "umls_cui": concept.get("umlscui") or None,
                        "suppress": concept.get("suppress") or None,
                    },
                ),
            )

        return ProviderResult(results=results)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search RxNorm for drug concepts matching *query*."""
        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)
        async with self._client() as client:
            resp = await client.get(_API_URL, params={"name": query})
            resp.raise_for_status()
            data = resp.json()

        return self._parse(data, limit)
