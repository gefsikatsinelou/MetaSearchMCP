r"""Ahmia search — Tor hidden services (.onion) search engine.

Ahmia indexes services on the Tor network and is itself reachable over
clearnet at ``ahmia.fi``. No API key is required, but the site uses a
rotating anti-bot token: the search form on the homepage carries a hidden
input whose name and value change on every page load, and the token must
be submitted together with the query.

Flow (two requests per search):

``GET https://ahmia.fi/``                     -> extract hidden token
``GET https://ahmia.fi/search/?q=QUERY&TOKEN`` -> server-rendered results

Results are ``<li class=\"result\">`` blocks whose heading anchor points
at an Ahmia redirect URL; the real onion address lives in the
``redirect_url`` query parameter of that href.
"""

from __future__ import annotations

from typing import ClassVar
from urllib.parse import parse_qs, urlparse

from bs4 import BeautifulSoup

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import BaseProvider

_HOME_URL = "https://ahmia.fi/"
_SEARCH_URL = "https://ahmia.fi/search/"


class AhmiaProvider(BaseProvider):
    r"""Search Tor hidden services (.onion) via Ahmia's clearnet index.

    Keyless. Fetches the homepage once per search to obtain the rotating
    anti-bot token, then queries the search endpoint. Result URLs are the
    real onion addresses recovered from Ahmia's redirect links; the onion
    domain is also exposed via ``extra[\"domain\"]``.
    """

    name = "ahmia"
    description = (
        "Tor hidden services (.onion) search via Ahmia's clearnet index, "
        "no API key required."
    )
    tags: ClassVar[list[str]] = ["web", "tor", "onion"]

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search Ahmia for *query* and return onion-service results."""
        limit = min(params.num_results, self._max_results)
        async with self._scraper_client() as client:
            home = await client.get(_HOME_URL)
            home.raise_for_status()
            token = self._extract_token(home.text)
            if token is None:
                return ProviderResult(results=[])
            resp = await client.get(
                _SEARCH_URL,
                params={"q": query, token[0]: token[1]},
            )
            resp.raise_for_status()

        return self._parse(resp.text, max_results=limit)

    @staticmethod
    def _extract_token(html: str) -> tuple[str, str] | None:
        """Return the (name, value) anti-bot token from the homepage form.

        The token is the hidden input inside the ``#searchForm`` form; its
        name and value rotate on every page load. Returns ``None`` when the
        form or the hidden input cannot be found.
        """
        soup = BeautifulSoup(html, "lxml")
        form = soup.find("form", id="searchForm")
        if form is None:
            return None
        hidden = form.find("input", {"type": "hidden"})
        if hidden is None:
            return None
        name = hidden.get("name")
        value = hidden.get("value")
        if not name or not value:
            return None
        return name, value

    def _parse(self, html: str, max_results: int | None = None) -> ProviderResult:
        """Parse the HTML response into structured search results."""
        soup = BeautifulSoup(html, "lxml")
        results: list[SearchResult] = []
        limit = max_results or self._max_results

        for li in soup.select("li.result"):
            heading = li.find("h4")
            if heading is None:
                continue
            anchor = heading.find("a")
            if anchor is None:
                continue
            title = anchor.get_text(" ", strip=True)
            url = self._real_url(anchor.get("href", ""))
            if not title or not url:
                continue

            snippet_el = li.find("p")
            cite_el = li.find("cite")
            extra = {}
            if cite_el is not None:
                extra["domain"] = cite_el.get_text(" ", strip=True)

            results.append(
                SearchResult(
                    title=title,
                    url=url,
                    snippet=snippet_el.get_text(" ", strip=True)
                    if snippet_el is not None
                    else "",
                    source="ahmia.fi",
                    rank=len(results) + 1,
                    provider=self.name,
                    extra=extra,
                ),
            )
            if len(results) >= limit:
                break

        return ProviderResult(results=results)

    @staticmethod
    def _real_url(redirect_href: str) -> str:
        """Recover the actual onion URL from Ahmia's redirect link.

        Ahmia wraps result links as ``/search/redirect?search_term=...&
        redirect_url=...``; the real address is the ``redirect_url`` value.
        Non-redirect hrefs (e.g. direct links) are returned unchanged, and
        redirect links without a ``redirect_url`` param yield an empty
        string so the caller can skip them.
        """
        parsed = urlparse(redirect_href)
        if parsed.path != "/search/redirect":
            return redirect_href
        values = parse_qs(parsed.query)
        redirects = values.get("redirect_url", [])
        return redirects[0] if redirects else ""
