from __future__ import annotations

from collections import OrderedDict

from bs4 import BeautifulSoup

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult
from .base import BaseProvider

_BASE_URL = "https://www.startpage.com"
_SEARCH_URL = "https://www.startpage.com/sp/search"


class StartpageProvider(BaseProvider):
    """Startpage search via HTML scraping.

    Startpage proxies Google results with privacy preservation.
    Heavy anti-bot measures; this provider may be unreliable in automated
    contexts. Use as best-effort.
    Note: HTML structure may change without notice; parser is best-effort.
    """

    name = "startpage"
    description = "Privacy-focused web search via Startpage without tracking."
    tags = ["web", "privacy", "google"]

    @staticmethod
    def _language_code(language: str) -> str:
        normalized = (language or "en").strip().replace("_", "-")
        primary = normalized.split("-", 1)[0].lower()
        return primary or "en"

    @staticmethod
    def _country_code(country: str) -> str:
        normalized = (country or "us").strip().replace("_", "-")
        region = normalized.rsplit("-", 1)[-1].lower()
        return region or "us"

    @classmethod
    def _build_locale_settings(cls, params: SearchParams) -> tuple[str, str]:
        engine_language = cls._language_code(params.language)
        engine_region = f"{cls._country_code(params.country)}-{engine_language}"
        return engine_language, engine_region

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        headers = {
            "Origin": _BASE_URL,
            "Referer": f"{_BASE_URL}/",
        }
        engine_language, engine_region = self._build_locale_settings(params)

        form_data = {
            "query": query,
            "cat": "web",
            "t": "device",
            "language": engine_language,
            "lui": engine_language,
            "abp": "1",
            "abd": "1",
            "abe": "1",
        }
        preferences = OrderedDict(
            [
                ("date_time", "world"),
                ("disable_family_filter", "1" if params.safe_search else "0"),
                ("disable_open_in_new_window", "0"),
                ("enable_post_method", "1"),
                ("enable_proxy_safety_suggest", "1"),
                ("enable_stay_control", "1"),
                ("instant_answers", "1"),
                ("lang_homepage", f"s/device/{engine_language}/"),
                ("num_of_results", str(min(params.num_results, self._max_results, 10))),
                ("suggestions", "1"),
                ("wt_unit", "celsius"),
                ("language", engine_language),
                ("language_ui", engine_language),
                ("search_results_region", engine_region),
            ]
        )
        cookies = {
            "preferences": "N1N".join(
                f"{key}EEE{value}" for key, value in preferences.items()
            )
        }

        async with self._scraper_client() as client:
            home = await client.get(f"{_BASE_URL}/", headers=headers)
            home.raise_for_status()
            sc_code = self._extract_sc_code(home.text)
            form_data["sc"] = sc_code

            resp = await client.post(
                _SEARCH_URL, data=form_data, cookies=cookies, headers=headers
            )
            resp.raise_for_status()

        if (
            "Error 883" in resp.text
            or "ability to connect to Startpage has been suspended" in resp.text
        ):
            raise RuntimeError(
                "Startpage temporarily suspended requests from this network (Error 883)"
            )

        if (
            "/sp/feedback2" in str(resp.url)
            or "prevent possible abuse of our service" in resp.text
        ):
            raise RuntimeError("Startpage rejected the request as automated traffic")

        return self._parse(resp.text)

    @staticmethod
    def _extract_sc_code(html: str) -> str:
        soup = BeautifulSoup(html, "lxml")
        sc_input = soup.select_one('form#search input[name="sc"]') or soup.select_one(
            'input[name="sc"]'
        )
        if not sc_input or not sc_input.get("value"):
            raise RuntimeError("Startpage did not expose an sc token for this session")
        return sc_input["value"]

    def _parse(self, html: str) -> ProviderResult:
        soup = BeautifulSoup(html, "lxml")
        results: list[SearchResult] = []

        # Startpage uses CSS-in-JS class names that change; rely on stable
        # semantic classes: div.result, a.result-title / a.result-link, p.description
        containers = soup.select("div.result")

        for i, block in enumerate(containers, start=1):
            # Title + URL: a.result-title or a.result-link
            a = block.select_one("a.result-title") or block.select_one("a.result-link")
            if not a:
                # Fallback: first external <a> in the block
                a = block.find("a", href=lambda h: h and h.startswith("https://"))
            if not a:
                continue

            title_el = (
                block.select_one("h2.wgl-title")
                or block.select_one("h2")
                or block.select_one("h3")
            )
            title = (
                title_el.get_text(strip=True) if title_el else a.get_text(strip=True)
            )
            url = a.get("href", "")
            if not url.startswith("http"):
                continue

            snippet = ""
            desc = block.select_one("p.description") or block.select_one("p")
            if desc:
                snippet = desc.get_text(strip=True)

            results.append(
                SearchResult(
                    title=title,
                    url=url,
                    snippet=snippet,
                    rank=i,
                    provider=self.name,
                )
            )
            if i >= self._max_results:
                break

        return ProviderResult(results=results)
