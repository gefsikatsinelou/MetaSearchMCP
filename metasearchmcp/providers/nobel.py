"""Nobel Prize award search via the keyless Nobel Prize API v2.

The Nobel Prize API (api.nobelprize.org, v2.1) is an official, keyless
JSON endpoint that describes every Nobel Prize awarded since 1901 and
every laureate:

``GET https://api.nobelprize.org/2.1/nobelPrizes?...``
``GET https://api.nobelprize.org/2.1/laureates?name=...``

No API key, registration, or rate-limit token is required (the official
API is offered free for non-commercial and educational use).

This provider searches the prizes themselves: the query is resolved to
an optional year (the first four-digit number, e.g. ``2024``) and an
optional prize category (chemistry/physics/medicine/literature/peace/
economics or their common prefixes like ``che``/``lit``). When both
resolve, the exact prize for that year and category is returned; when
only a category matches, that category's most recent prizes are returned
sorted newest-first; otherwise the most recent prizes across all
categories are returned, which still lets a caller discover what was
recently awarded.

Each hit carries the full category name, award year, the official award
date, and the laureates with their motivation text. ``published_date``
is set to the award year, and URLs link to the official nobelprize.org
prize pages.
"""

from __future__ import annotations

from typing import Any, ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_API_URL = "https://api.nobelprize.org/2.1/nobelPrizes"
# The v2 API caps page size at 100 records per request.
_MAX_API_RESULTS = 100

# Nobel category slug -> query used on the official nobelprize.org site.
_CATEGORY_URLS: dict[str, str] = {
    "physics": "https://www.nobelprize.org/prizes/physics/",
    "chemistry": "https://www.nobelprize.org/prizes/chemistry/",
    "medicine": "https://www.nobelprize.org/prizes/medicine/",
    "literature": "https://www.nobelprize.org/prizes/literature/",
    "peace": "https://www.nobelprize.org/prizes/peace/",
    "economics": "https://www.nobelprize.org/prizes/economic-sciences/",
}

# Canonical English category names -> official API category id.
_CATEGORY_IDS: dict[str, str] = {
    "physics": "phy",
    "chemistry": "che",
    "medicine": "med",
    "literature": "lit",
    "peace": "pea",
    "economics": "eco",
}

# Official API category id -> slug used in nobelprize.org prize URLs.
_CATEGORY_SLUGS: dict[str, str] = {
    "phy": "physics",
    "che": "chemistry",
    "med": "medicine",
    "lit": "literature",
    "pea": "peace",
    "eco": "economic-sciences",
}

# Accepted alias prefixes for a category word, mapping to the canonical id.
_CATEGORY_ALIASES: dict[str, str] = {
    "phys": "phy",
    "physical": "phy",
    "chem": "che",
    "med": "med",
    "medical": "med",
    "physiology": "med",
    "lit": "lit",
    "literary": "lit",
    "pea": "pea",
    "nobel peace": "pea",
    "eco": "eco",
    "economic": "eco",
    "economy": "eco",
    "memorial": "eco",
    "sveriges riksbank": "eco",
}


def _category_id(word: str) -> str | None:
    """Resolve one category word to its official API id, or ``None``."""
    token = word.strip().lower()
    if token in _CATEGORY_IDS:
        return _CATEGORY_IDS[token]
    if token in _CATEGORY_ALIASES:
        return _CATEGORY_ALIASES[token]
    # Strip a trailing plural "s" and retry (physics -> physic -> phy).
    singular = token.rstrip("s")
    if singular in _CATEGORY_IDS:
        return _CATEGORY_IDS[singular]
    return _CATEGORY_ALIASES.get(singular)


class NobelPrizeProvider(BaseProvider):
    """Search Nobel Prizes and laureates via the keyless official API.

    The query may include an optional four-digit year (``2024``,
    ``"einstein 1921"``) and/or an optional category word (``chemistry``,
    ``"physics"``, ...). Year and category are resolved independently;
    a match on either narrows the prize list, and anything else falls
    back to the most recently awarded prizes.
    """

    name = "nobel"
    description = (
        "Search Nobel Prizes and laureates — award year, category, and "
        "motivation via the keyless official Nobel Prize API."
    )
    tags: ClassVar[list[str]] = ["reference", "awards", "history"]

    @staticmethod
    def _clean(value: object) -> str:
        """Collapse whitespace in a free-text field."""
        if not value:
            return ""
        return " ".join(str(value).split())

    @staticmethod
    def _year_of(query: str) -> str | None:
        """Return the first plausible 4-digit year (1901-2026) in *query*.

        ``None`` when the query carries no usable year token.
        """
        for token in query.split():
            if len(token) == 4 and token.isdigit() and 1901 <= int(token) <= 2026:
                return token
        return None

    def _resolve_category(self, query: str) -> str | None:
        """Resolve the first category word in *query* to an API category id."""
        lowered = self._clean(query).lower()
        if "economics" in lowered or "economic sciences" in lowered:
            return "eco"
        for word in lowered.split():
            resolved = _category_id(word)
            if resolved:
                return resolved
        return None

    @classmethod
    def _category_label(cls, category_id: str) -> str:
        """Return the canonical English label for an API category id."""
        for label, cid in _CATEGORY_IDS.items():
            if cid == category_id:
                return label
        return category_id

    @classmethod
    def _category_url(cls, category_id: str) -> str:
        """Return the nobelprize.org URL for an API category id."""
        for label, cid in _CATEGORY_IDS.items():
            if cid == category_id:
                return _CATEGORY_URLS[label]
        return "https://www.nobelprize.org/prizes/"

    def _parse(self, data: Any, limit: int | None = None) -> ProviderResult:
        """Parse a /nobelPrizes response into structured search results.

        Only the ``en`` fields are used for titles and snippets; the raw
        response payloads for the first hit are kept under ``extra`` so
        callers can inspect the full (English) record without another
        request. Prizes lacking a usable award year are skipped.
        """
        results: list[SearchResult] = []
        if not isinstance(data, dict):
            return ProviderResult(results=results)
        prizes = data.get("nobelPrizes")
        if not isinstance(prizes, list):
            return ProviderResult(results=results)

        max_results = limit or self._max_results
        for prize in prizes:
            if len(results) >= max_results:
                break
            if not isinstance(prize, dict):
                continue
            year = self._clean(prize.get("awardYear"))
            if not year:
                continue
            category = prize.get("category")
            category_id = category.get("id") if isinstance(category, dict) else None
            category_full = prize.get("categoryFullName")
            full_label = (
                category_full.get("en") if isinstance(category_full, dict) else ""
            )
            full_label = self._clean(full_label)
            label = full_label or self._category_label(str(category_id or ""))
            short_label = self._category_label(str(category_id or ""))

            laureates: list[str] = []
            for laureate in prize.get("laureates") or []:
                if not isinstance(laureate, dict):
                    continue
                known = laureate.get("knownName")
                full = laureate.get("fullName")
                if isinstance(known, dict):
                    name = self._clean(known.get("en"))
                elif isinstance(full, dict):
                    name = self._clean(full.get("en"))
                else:
                    name = ""
                if name:
                    laureates.append(name)

            snippet_parts: list[str] = []
            if laureates:
                snippet_parts.append(f"Laureates: {', '.join(laureates)}")
            motivations: list[str] = []
            for laureate in prize.get("laureates") or []:
                if not isinstance(laureate, dict):
                    continue
                motivation = laureate.get("motivation")
                if isinstance(motivation, dict):
                    text = self._clean(motivation.get("en"))
                    if text:
                        motivations.append(text)
            if motivations:
                snippet_parts.append(f"Motivation: {' '.join(motivations)}")
            date_awarded = self._clean(prize.get("dateAwarded"))

            # Keep the English payload compact so callers can inspect it.
            english_payload: dict[str, Any] = {}
            for key in ("awardYear", "dateAwarded"):
                if prize.get(key) is not None:
                    english_payload[key] = prize.get(key)
            if category_id:
                english_payload["category"] = category_id
            if full_label:
                english_payload["categoryFullName"] = full_label
            english_payload["laureates"] = laureates

            title = f"{label} {year}"
            results.append(
                SearchResult(
                    title=title,
                    url=self._category_url(str(category_id or ""))
                    if category_id
                    else "https://www.nobelprize.org/prizes/",
                    snippet=" | ".join(snippet_parts)[:MAX_SNIPPET_LENGTH],
                    source="nobelprize.org",
                    rank=len(results) + 1,
                    provider=self.name,
                    published_date=date_awarded[:10] or year,
                    extra={
                        "category": short_label,
                        "category_id": category_id,
                        "year": year,
                        "laureates": laureates,
                        "motivations": motivations,
                        "payload": english_payload,
                    },
                ),
            )

        return ProviderResult(results=results)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search Nobel Prizes matching *query* and return structured results.

        The query is resolved to an optional award year (a four-digit
        number like ``1921``) and an optional category (``chemistry``,
        ``physics``, ...). Matching prizes are returned newest-first; an
        unresolvable query falls back to the most recently awarded prizes
        so a caller can still discover what was awarded.
        """
        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)
        query_params: dict[str, str] = {
            "limit": str(limit),
            "sort": "desc",
        }
        year = self._year_of(query)
        category_id = self._resolve_category(query)
        if year:
            query_params["nobelPrizeYear"] = year
        if category_id:
            query_params["nobelPrizeCategory"] = category_id

        async with self._client() as client:
            resp = await client.get(_API_URL, params=query_params)
            resp.raise_for_status()
            data = resp.json()

        return self._parse(data, limit)
