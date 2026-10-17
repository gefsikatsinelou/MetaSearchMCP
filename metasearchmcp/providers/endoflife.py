"""Software release lifecycle and end-of-life search via the keyless
endoflife.date API.

`endoflife.date <https://endoflife.date>`_ tracks the support lifecycle of
hundreds of software products — languages, runtimes, frameworks, databases,
operating systems, hardware and SaaS offerings.  Its public JSON API is
keyless:

``GET https://endoflife.date/api/all.json``
    Returns a flat list of all product slugs (``["python", "nodejs", ...]``).

``GET https://endoflife.date/api/{product}.json``
    Returns the release cycles for one product, newest first.  Each cycle
    carries the cycle label, release date, latest patch release, the
    active-support end date and the end-of-life (EOL) date — any of which may
    be a boolean when the date is unknown or "not yet reached".

A search matches the free-text query against the product slugs, then fetches
the release cycles for the best matching products.  Each result represents one
product and summarises its newest cycle, with the full cycle table embedded in
the result's ``extra`` payload.  This complements the package-registry
providers (``pypi``, ``npm``, ``crates``, ...), which index *what* a package
is but not *until when* a release line is supported.
"""

from __future__ import annotations

import asyncio
from typing import Any, ClassVar
from urllib.parse import quote

import httpx

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_ALL_URL = "https://endoflife.date/api/all.json"
_PRODUCT_URL = "https://endoflife.date/api/{product}.json"
# Number of matched products to resolve into results.
_MAX_PRODUCTS = 8
# Maximum number of release cycles embedded in a result's ``extra`` payload.
_MAX_CYCLES_IN_EXTRA = 20


class EndOfLifeProvider(BaseProvider):
    """Search software release lifecycles and end-of-life dates.

    Keyless.  Uses the public endoflife.date JSON API.  Each result is one
    product (e.g. ``python``, ``nodejs``, ``ubuntu``) with the newest cycle's
    latest release, active-support end and EOL date, plus the full cycle table
    in the result's ``extra`` payload.
    """

    name = "endoflife"
    description = (
        "Search software release lifecycles and end-of-life dates (latest "
        "release, active-support end, EOL, LTS status) for languages, "
        "runtimes, frameworks, databases and operating systems via the "
        "keyless endoflife.date API — no API key required."
    )
    tags: ClassVar[list[str]] = ["web", "developer", "reference", "lifecycle"]

    @staticmethod
    def _clean_text(value: object) -> str:
        """Collapse whitespace in a free-text field."""
        if value is None:
            return ""
        return " ".join(str(value).split())

    @classmethod
    def _date_value(cls, value: object) -> str | None:
        """Return a ``YYYY-MM-DD`` date string when *value* is one, else ``None``."""
        if not isinstance(value, str):
            return None
        candidate = value.strip()[:10]
        parts = candidate.split("-")
        if len(parts) == 3 and all(part.isdigit() for part in parts):
            return candidate
        return None

    @classmethod
    def _flag_or_date(cls, value: object) -> str | bool | None:
        """Normalize a lifecycle field that may be a date, a flag or absent.

        Returns an ISO date string, a boolean flag, or ``None`` when the value
        carries no usable information.
        """
        date = cls._date_value(value)
        if date:
            return date
        if isinstance(value, bool):
            return value
        return None

    @staticmethod
    def _eol_label(value: str | bool | None) -> str:
        """Render an end-of-life value as a short human-readable label."""
        if isinstance(value, str):
            return f"EOL {value}"
        if value is True:
            return "end-of-life reached"
        return ""

    @staticmethod
    def _support_label(value: str | bool | None) -> str:
        """Render an active-support value as a short label."""
        if isinstance(value, str):
            return f"support ends {value}"
        if value is True:
            return "in active support"
        return ""

    @staticmethod
    def _lts_label(value: str | bool | None) -> str:
        """Render a long-term-support value as a short label."""
        if isinstance(value, str):
            return f"LTS since {value}"
        if value is True:
            return "LTS"
        return ""

    @classmethod
    def _normalize(cls, value: str) -> str:
        """Reduce a string to lowercase alphanumeric characters for matching."""
        return "".join(ch for ch in value.lower() if ch.isalnum())

    @classmethod
    def _match_products(
        cls,
        products: object,
        query: str,
        limit: int,
    ) -> list[str]:
        """Rank product slugs from ``all.json`` against the query tokens.

        Exact slug matches rank first, then slugs containing every query token,
        then slugs containing the leading token (so ``"ubuntu 22.04"`` still
        matches ``ubuntu``).
        """
        if not isinstance(products, list):
            return []
        tokens = [cls._normalize(token) for token in query.split()]
        tokens = [token for token in tokens if token]
        if not tokens or limit <= 0:
            return []

        joined = "".join(tokens)
        scored: list[tuple[int, int, str]] = []
        for slug in products:
            if not isinstance(slug, str) or not slug:
                continue
            key = cls._normalize(slug)
            if not key:
                continue
            if key == joined:
                score = 0
            elif all(token in key for token in tokens):
                score = 1
            elif tokens[0] in key:
                score = 2
            else:
                continue
            scored.append((score, len(slug), slug))

        scored.sort()
        matched: list[str] = []
        for _, _, slug in scored:
            if slug in matched:
                continue
            matched.append(slug)
            if len(matched) >= limit:
                break
        return matched

    @classmethod
    def _cycle_entry(cls, item: dict[str, Any]) -> dict[str, Any]:
        """Normalize a single release cycle into a JSON-serializable dict."""
        raw_cycle = cls._clean_text(item.get("cycle"))
        cycle = raw_cycle or cls._clean_text(item.get("releaseLabel"))
        return {
            "cycle": cycle,
            "codename": cls._clean_text(item.get("codename")),
            "release_date": cls._date_value(item.get("releaseDate")),
            "latest": cls._clean_text(item.get("latest")),
            "latest_release_date": cls._date_value(item.get("latestReleaseDate")),
            "support": cls._flag_or_date(item.get("support")),
            "eol": cls._flag_or_date(item.get("eol")),
            "lts": cls._flag_or_date(item.get("lts")),
        }

    def _product_result(self, product: str, data: object) -> SearchResult | None:
        """Build one search result for *product* from its release-cycle list.

        Returns ``None`` when the payload carries no usable cycles.
        """
        if not isinstance(data, list):
            return None
        entries = [self._cycle_entry(item) for item in data if isinstance(item, dict)]
        entries = [entry for entry in entries if entry["cycle"]]
        if not entries:
            return None

        # The API lists the newest cycle first.
        newest = entries[0]
        latest = newest["latest"]
        latest_release_date = newest["latest_release_date"]
        eol = newest["eol"]
        support = newest["support"]
        lts = newest["lts"]

        snippet_parts: list[str] = []
        if latest:
            latest_note = f"Latest {latest}"
            if latest_release_date:
                latest_note = f"{latest_note} ({latest_release_date})"
            snippet_parts.append(latest_note)
        snippet_parts.append(f"current cycle {newest['cycle']}")
        if newest["codename"]:
            snippet_parts.append(f"“{newest['codename']}”")
        lts_label = self._lts_label(lts)
        if lts_label:
            snippet_parts.append(lts_label)
        support_label = self._support_label(support)
        if support_label:
            snippet_parts.append(support_label)
        eol_label = self._eol_label(eol)
        if eol_label:
            snippet_parts.append(eol_label)
        snippet_parts.append(f"{len(entries)} cycles tracked")

        return SearchResult(
            title=product.replace("-", " "),
            url=f"https://endoflife.date/{quote(product)}",
            snippet=" | ".join(snippet_parts)[:MAX_SNIPPET_LENGTH],
            source="endoflife.date",
            provider=self.name,
            published_date=latest_release_date,
            extra={
                "product": product,
                "latest_cycle": newest["cycle"],
                "latest": latest,
                "latest_release_date": latest_release_date,
                "support": support,
                "eol": eol,
                "lts": lts,
                "product_url": f"https://endoflife.date/{quote(product)}",
                "cycles": entries[:_MAX_CYCLES_IN_EXTRA],
            },
        )

    async def _fetch_cycles(
        self,
        client: httpx.AsyncClient,
        product: str,
    ) -> object | None:
        """Fetch one product's release cycles, or ``None`` on any failure."""
        url = _PRODUCT_URL.format(product=quote(product, safe=""))
        try:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.json()
        except (httpx.HTTPError, ValueError):
            return None

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search endoflife.date for software lifecycles matching *query*."""
        limit = min(params.num_results, self._max_results, _MAX_PRODUCTS)
        async with self._client() as client:
            resp = await client.get(_ALL_URL)
            resp.raise_for_status()
            products = resp.json()

            matched = self._match_products(products, query, limit)
            if not matched:
                return ProviderResult(results=[])

            payloads = await asyncio.gather(
                *(self._fetch_cycles(client, product) for product in matched),
            )

        results: list[SearchResult] = []
        for product, payload in zip(matched, payloads, strict=True):
            if payload is None:
                continue
            result = self._product_result(product, payload)
            if result is None:
                continue
            result.rank = len(results) + 1
            results.append(result)

        return ProviderResult(results=results)
