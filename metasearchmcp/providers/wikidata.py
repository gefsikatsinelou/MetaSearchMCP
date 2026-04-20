from __future__ import annotations

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult
from .base import BOT_USER_AGENT, BaseProvider

_API_URL = "https://www.wikidata.org/w/api.php"


class WikidataProvider(BaseProvider):
    """Wikidata entity search via the MediaWiki API.

    Returns structured knowledge entities (people, places, concepts, etc.)
    with their descriptions. No authentication required.
    """

    name = "wikidata"
    description = "Search structured knowledge base entities on Wikidata."
    tags = ["web", "academic", "knowledge"]

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        qp = {
            "action": "wbsearchentities",
            "search": query,
            "language": params.language,
            "limit": min(params.num_results, self._max_results, 20),
            "format": "json",
            "type": "item",
        }

        # Wikimedia requires a descriptive UA with contact info to avoid 403
        headers = {
            "User-Agent": BOT_USER_AGENT
        }
        async with self._client() as client:
            resp = await client.get(_API_URL, params=qp, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        return self._parse(data, params.language)

    def _parse(self, data: dict, language: str) -> ProviderResult:
        results: list[SearchResult] = []

        for i, item in enumerate(data.get("search", []), start=1):
            entity_id = item.get("id", "")
            label = item.get("label", "")
            description = item.get("description", "")
            aliases = item.get("aliases", [])
            url = item.get("url", f"https://www.wikidata.org/wiki/{entity_id}")
            if not url.startswith("http"):
                url = f"https:{url}"

            snippet_parts = [description]
            if aliases:
                snippet_parts.append(f"Also known as: {', '.join(aliases[:3])}")

            results.append(
                SearchResult(
                    title=label or entity_id,
                    url=url,
                    snippet=" | ".join(p for p in snippet_parts if p),
                    source="wikidata.org",
                    rank=i,
                    provider=self.name,
                    extra={
                        "entity_id": entity_id,
                        "aliases": aliases,
                    },
                )
            )

        return ProviderResult(results=results)
