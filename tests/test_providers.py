"""Provider parse/adapter unit tests using mocked HTTP responses."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from metasearchmcp.contracts import SearchParams

# ---------------------------------------------------------------------------
# Wikipedia
# ---------------------------------------------------------------------------


def _wikipedia_response() -> dict:
    return {
        "query": {
            "search": [
                {
                    "title": "Python (programming language)",
                    "snippet": "<span>Python</span> is a high-level language.",
                    "timestamp": "2024-01-15T10:00:00Z",
                },
                {
                    "title": "Monty Python",
                    "snippet": "British <span>comedy</span> group.",
                    "timestamp": "2023-06-01T00:00:00Z",
                },
            ],
        },
    }


def test_wikipedia_parse():
    from metasearchmcp.providers.wikipedia import WikipediaProvider

    provider = WikipediaProvider()
    result = provider._parse(_wikipedia_response())

    assert len(result.results) == 2
    r = result.results[0]
    assert r.title == "Python (programming language)"
    assert r.url == "https://en.wikipedia.org/wiki/Python_(programming_language)"
    assert r.provider == "wikipedia"
    assert r.published_date == "2024-01-15"
    # HTML tags should be stripped from snippet
    assert "<span>" not in r.snippet


# ---------------------------------------------------------------------------
# arXiv
# ---------------------------------------------------------------------------


def _arxiv_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>https://arxiv.org/abs/2301.00001</id>
    <title>Attention Is All You Need</title>
    <summary>We propose a new simple network architecture, the Transformer.</summary>
    <published>2023-01-01T00:00:00Z</published>
    <author><name>Vaswani et al.</name></author>
  </entry>
  <entry>
    <id>https://arxiv.org/abs/2301.00002</id>
    <title>BERT: Pre-training of Deep Bidirectional Transformers</title>
    <summary>We introduce BERT for language representation.</summary>
    <published>2023-01-02T00:00:00Z</published>
    <author><name>Devlin et al.</name></author>
  </entry>
</feed>"""


def test_arxiv_parse():
    from metasearchmcp.providers.arxiv import ArxivProvider

    provider = ArxivProvider()
    result = provider._parse(_arxiv_xml())

    assert len(result.results) == 2
    r = result.results[0]
    assert r.title == "Attention Is All You Need"
    assert r.url == "https://arxiv.org/abs/2301.00001"
    assert r.provider == "arxiv"
    assert r.published_date == "2023-01-01"
    assert "Vaswani" in r.extra["authors"][0]


def test_arxiv_parse_malformed_xml():
    from metasearchmcp.providers.arxiv import ArxivProvider

    provider = ArxivProvider()
    result = provider._parse("this is not xml")
    assert result.results == []


# ---------------------------------------------------------------------------
# GitHub
# ---------------------------------------------------------------------------


def _github_response() -> dict:
    return {
        "total_count": 1,
        "items": [
            {
                "full_name": "psf/requests",
                "html_url": "https://github.com/psf/requests",
                "description": "A simple HTTP library for Python",
                "stargazers_count": 51000,
                "language": "Python",
                "forks_count": 9000,
                "topics": ["http", "python"],
                "pushed_at": "2024-03-01T00:00:00Z",
            },
        ],
    }


def test_github_parse():
    from metasearchmcp.providers.github import GitHubProvider

    provider = GitHubProvider()
    result = provider._parse(_github_response())

    assert len(result.results) == 1
    r = result.results[0]
    assert r.title == "psf/requests"
    assert r.url == "https://github.com/psf/requests"
    assert r.provider == "github"
    assert r.extra["stars"] == 51000
    assert "Python" in r.snippet
    assert r.published_date == "2024-03-01"


# ---------------------------------------------------------------------------
# Google
# ---------------------------------------------------------------------------


def _google_html() -> str:
    return """
    <html>
      <body>
        <div class="kno-rdesc">FastAPI is a modern Python web framework.</div>
        <div class="g">
          <a href="/url?q=https%3A%2F%2Ffastapi.tiangolo.com&sa=U&ved=123">
            <h3>FastAPI</h3>
          </a>
          <div class="VwiC3b">FastAPI framework, high performance</div>
        </div>
        <div class="gGQDvd iIWm4b">
          <a href="/search?q=fastapi+tutorial">fastapi tutorial</a>
          <a href="/preferences?hl=en">Settings</a>
        </div>
      </body>
    </html>
    """


def test_google_parse():
    from metasearchmcp.providers.google import GoogleProvider

    provider = GoogleProvider()
    result = provider._parse(_google_html())

    assert len(result.results) == 1
    r = result.results[0]
    assert r.title == "FastAPI"
    assert r.url == "https://fastapi.tiangolo.com"
    assert r.provider == "google"
    assert result.related_searches == ["fastapi tutorial"]
    assert result.answer_box == {"text": "FastAPI is a modern Python web framework."}


def test_google_parse_filters_invalid_result_links_and_deduplicates():
    from metasearchmcp.providers.google import GoogleProvider

    provider = GoogleProvider()
    result = provider._parse(
        """
        <html>
          <body>
            <div class="g">
              <a href="/search?q=internal+nav"><h3>Internal Nav</h3></a>
              <div class="VwiC3b">Ignore me</div>
            </div>
            <div class="g">
              <a href="/url?q=https%3A%2F%2Fexample.com%2Fguide&sa=U"><h3>Guide</h3></a>
              <div class="VwiC3b">Primary result</div>
            </div>
            <div class="g">
              <a href="https://example.com/guide"><h3>Guide duplicate</h3></a>
              <div class="VwiC3b">Duplicate result</div>
            </div>
          </body>
        </html>
        """,
    )

    assert len(result.results) == 1
    assert result.results[0].url == "https://example.com/guide"
    assert result.results[0].snippet == "Primary result"


def test_google_rejects_sorry_page():
    from metasearchmcp.providers.google import GoogleProvider

    provider = GoogleProvider()

    with pytest.raises(RuntimeError, match="automated traffic"):
        provider._raise_on_blocked_response(
            "Our systems have detected unusual traffic from your computer network",
            "https://www.google.com/sorry/index",
        )


@pytest.mark.asyncio
async def test_google_search_normalizes_language_for_request(monkeypatch):
    from metasearchmcp.providers.google import GoogleProvider

    captured: dict[str, object] = {}

    class FakeResponse:
        text = "<html></html>"
        url = "https://www.google.com/search?q=fastapi"

        def raise_for_status(self) -> None:
            return None

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, url, params=None, cookies=None, headers=None):
            captured["url"] = url
            captured["params"] = params
            captured["cookies"] = cookies
            captured["headers"] = headers
            return FakeResponse()

    provider = GoogleProvider()
    monkeypatch.setattr(provider, "_scraper_client", lambda: FakeClient())
    monkeypatch.setattr(provider, "_parse", lambda html: SimpleNamespace(results=[]))

    result = await provider.search(
        "fastapi",
        SearchParams(language="pt-BR", country="br", safe_search=True),
    )

    assert result.results == []
    assert captured["params"]["hl"] == "pt-BR"
    assert captured["params"]["lr"] == "lang_pt"
    assert "SM-G900P Build/LRX21T" in captured["headers"]["User-Agent"]
    assert "Mobile Safari/537.36 NSTNWV" in captured["headers"]["User-Agent"]
    assert captured["headers"]["User-Agent"].endswith("pt-BR")


@pytest.mark.asyncio
async def test_google_search_normalizes_country_for_request(monkeypatch):
    from metasearchmcp.providers.google import GoogleProvider

    captured: dict[str, object] = {}

    class FakeResponse:
        text = "<html></html>"
        url = "https://www.google.com/search?q=fastapi"

        def raise_for_status(self) -> None:
            return None

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, url, params=None, cookies=None, headers=None):
            captured["params"] = params
            return FakeResponse()

    provider = GoogleProvider()
    monkeypatch.setattr(provider, "_scraper_client", lambda: FakeClient())
    monkeypatch.setattr(provider, "_parse", lambda html: SimpleNamespace(results=[]))

    await provider.search(
        "fastapi",
        SearchParams(language="en", country=" pt-BR ", safe_search=True),
    )

    assert captured["params"]["hl"] == "en-BR"
    assert captured["params"]["gl"] == "br"


def test_google_build_user_agent_applies_stable_variant_suffix():
    from metasearchmcp.providers.google import GoogleProvider

    ua = GoogleProvider._build_user_agent("en", "us")

    assert ua.startswith("Mozilla/5.0 (Linux; Android 5.0; SM-G900P Build/LRX21T)")
    assert "Chrome/39.0.2374." in ua
    assert ua.endswith("NSTNWV en-US")


# ---------------------------------------------------------------------------
# Google Serper
# ---------------------------------------------------------------------------


def _serper_response() -> dict:
    return {
        "organic": [
            {
                "title": "FastAPI",
                "link": "https://fastapi.tiangolo.com",
                "snippet": "FastAPI framework, high performance",
                "date": "2024-01-01",
            },
        ],
        "relatedSearches": [
            {"query": "fastapi tutorial"},
            {"query": " fastapi tutorial "},
            {"query": ""},
            {},
        ],
        "answerBox": {"answer": "FastAPI is a web framework"},
    }


def test_serper_parse():
    from metasearchmcp.providers.google_serper import GoogleSerperProvider

    provider = GoogleSerperProvider()
    result = provider._parse(_serper_response())

    assert len(result.results) == 1
    r = result.results[0]
    assert r.title == "FastAPI"
    assert r.url == "https://fastapi.tiangolo.com"
    assert r.provider == "google_serper"
    assert result.related_searches == ["fastapi tutorial"]
    assert result.answer_box == {"answer": "FastAPI is a web framework"}


@pytest.mark.asyncio
async def test_serper_search_normalizes_locale_for_request(monkeypatch):
    from metasearchmcp.providers.google_serper import GoogleSerperProvider

    captured: dict[str, object] = {}

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"organic": []}

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, json=None, headers=None):
            captured["url"] = url
            captured["json"] = json
            captured["headers"] = headers
            return FakeResponse()

    provider = GoogleSerperProvider()
    monkeypatch.setattr(provider, "_api_key", "test-key")
    monkeypatch.setattr(provider, "_client", lambda: FakeClient())

    result = await provider.search(
        "fastapi",
        SearchParams(language="pt-BR", country=" pt-BR ", safe_search=True),
    )

    assert result.results == []
    assert captured["json"]["hl"] == "pt"
    assert captured["json"]["gl"] == "br"


def test_serpbase_parse_cleans_related_searches():
    from metasearchmcp.providers.google_serpbase import GoogleSerpbaseProvider

    provider = GoogleSerpbaseProvider()
    result = provider._parse(
        {
            "status": 0,
            "organic": [
                {
                    "title": "FastAPI",
                    "link": "https://fastapi.tiangolo.com",
                    "snippet": "FastAPI framework, high performance",
                    "date": "2024-01-01",
                },
            ],
            "related_searches": ["fastapi tutorial", " fastapi tutorial ", "", None],
            "knowledge_graph": {"title": "FastAPI"},
        },
        "fastapi",
    )

    assert len(result.results) == 1
    assert result.related_searches == ["fastapi tutorial"]
    assert result.answer_box == {"title": "FastAPI"}


@pytest.mark.asyncio
async def test_serpbase_search_normalizes_locale_for_request(monkeypatch):
    from metasearchmcp.providers.google_serpbase import GoogleSerpbaseProvider

    captured: dict[str, object] = {}

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"status": 0, "organic": []}

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, json=None, headers=None):
            captured["url"] = url
            captured["json"] = json
            captured["headers"] = headers
            return FakeResponse()

    provider = GoogleSerpbaseProvider()
    monkeypatch.setattr(provider, "_api_key", "test-key")
    monkeypatch.setattr(provider, "_client", lambda: FakeClient())

    result = await provider.search(
        "fastapi",
        SearchParams(language="pt-BR", country=" pt-BR ", safe_search=True),
    )

    assert result.results == []
    assert captured["json"]["hl"] == "pt"
    assert captured["json"]["gl"] == "br"


@pytest.mark.asyncio
async def test_brave_search_normalizes_locale_for_request(monkeypatch):
    from metasearchmcp.providers.brave import BraveProvider

    captured: dict[str, object] = {}

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"web": {"results": []}}

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, url, params=None, headers=None):
            captured["url"] = url
            captured["params"] = params
            captured["headers"] = headers
            return FakeResponse()

    provider = BraveProvider()
    monkeypatch.setattr(provider, "_api_key", "test-key")
    monkeypatch.setattr(provider, "_client", lambda: FakeClient())

    result = await provider.search(
        "fastapi",
        SearchParams(language="pt-BR", country=" pt-BR ", safe_search=True),
    )

    assert result.results == []
    assert captured["params"]["search_lang"] == "pt"
    assert captured["params"]["country"] == "BR"


@pytest.mark.asyncio
async def test_duckduckgo_search_normalizes_locale_for_request(monkeypatch):
    from metasearchmcp.providers.duckduckgo import DuckDuckGoProvider

    captured: dict[str, object] = {}

    class FakeResponse:
        text = "<html></html>"

        def raise_for_status(self) -> None:
            return None

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, url, params=None):
            captured["url"] = url
            captured["params"] = params
            return FakeResponse()

    provider = DuckDuckGoProvider()
    monkeypatch.setattr(provider, "_scraper_client", lambda: FakeClient())
    monkeypatch.setattr(provider, "_parse", lambda html: SimpleNamespace(results=[]))

    result = await provider.search(
        "fastapi",
        SearchParams(language="pt-BR", country=" pt-BR ", safe_search=True),
    )

    assert result.results == []
    assert captured["params"]["kl"] == "pt-BR"
    assert captured["params"]["kp"] == "1"


@pytest.mark.asyncio
async def test_bing_search_normalizes_locale_for_request(monkeypatch):
    from metasearchmcp.providers.bing import BingProvider

    captured: dict[str, object] = {}

    class FakeResponse:
        text = "<rss></rss>"

        def raise_for_status(self) -> None:
            return None

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, url, params=None):
            captured["url"] = url
            captured["params"] = params
            return FakeResponse()

    provider = BingProvider()
    monkeypatch.setattr(provider, "_client", lambda: FakeClient())
    monkeypatch.setattr(
        provider,
        "_parse",
        lambda xml_text: SimpleNamespace(results=[]),
    )

    result = await provider.search(
        "fastapi",
        SearchParams(language="pt-BR", country=" pt-BR ", safe_search=True),
    )

    assert result.results == []
    assert captured["params"]["setlang"] == "pt-BR"
    assert captured["params"]["mkt"] == "pt-BR"
    assert captured["params"]["adlt"] == "strict"


@pytest.mark.asyncio
async def test_qwant_search_normalizes_locale_for_request(monkeypatch):
    from metasearchmcp.providers.qwant import QwantProvider

    calls: list[dict[str, object]] = []

    class FakeResponse:
        def __init__(self, *, status_code, text="", json_data=None):
            self.status_code = status_code
            self.text = text
            self._json_data = json_data or {}

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return self._json_data

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, url, params=None, headers=None):
            calls.append({"url": url, "params": params, "headers": headers})
            if "api.qwant.com" in url:
                return FakeResponse(status_code=403)
            return FakeResponse(status_code=200, text="<html></html>")

    provider = QwantProvider()
    monkeypatch.setattr(provider, "_scraper_client", lambda: FakeClient())
    monkeypatch.setattr(
        provider,
        "_parse_lite",
        lambda html: SimpleNamespace(results=[]),
    )

    result = await provider.search(
        "fastapi",
        SearchParams(language="pt-BR", country=" pt-BR ", safe_search=True),
    )

    assert result.results == []
    assert calls[0]["params"]["locale"] == "pt_BR"
    assert calls[1]["params"]["locale"] == "pt_br"
    assert calls[1]["params"]["l"] == "pt"
    assert calls[1]["params"]["s"] == 1


# ---------------------------------------------------------------------------
# Provider availability
# ---------------------------------------------------------------------------


def test_yandex_normalizes_language_code():
    from metasearchmcp.providers.yandex import YandexProvider

    assert YandexProvider._language_code("pt-BR") == "pt"
    assert YandexProvider._language_code(" pt-BR ") == "pt"
    assert YandexProvider._language_code("en") == "en"
    assert YandexProvider._language_code("") == "en"


def test_google_unavailable_without_unstable_flag(monkeypatch):
    monkeypatch.setenv("ALLOW_UNSTABLE_PROVIDERS", "false")
    import metasearchmcp.config as cfg

    cfg._settings = None
    from metasearchmcp.providers.google import GoogleProvider

    p = GoogleProvider()
    assert p.is_available() is False
    cfg._settings = None


def test_google_serpbase_unavailable_without_key(monkeypatch):
    monkeypatch.setenv("SERPBASE_API_KEY", "")
    # Reset settings singleton
    import metasearchmcp.config as cfg

    cfg._settings = None
    from metasearchmcp.providers.google_serpbase import GoogleSerpbaseProvider

    p = GoogleSerpbaseProvider()
    assert p.is_available() is False
    cfg._settings = None  # clean up


def test_brave_unavailable_without_key(monkeypatch):
    monkeypatch.setenv("BRAVE_API_KEY", "")
    import metasearchmcp.config as cfg

    cfg._settings = None
    from metasearchmcp.providers.brave import BraveProvider

    p = BraveProvider()
    assert p.is_available() is False
    cfg._settings = None


def test_duckduckgo_always_available():
    from metasearchmcp.providers.duckduckgo import DuckDuckGoProvider

    p = DuckDuckGoProvider()
    assert p.is_available() is True
