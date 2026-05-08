"""Tests for the Baidu provider parser."""

from __future__ import annotations


def _baidu_payload() -> dict:
    return {
        "feed": {
            "entry": [
                {
                    "title": "Python asyncio official docs",
                    "url": "https://docs.python.org/3/library/asyncio.html",
                    "abs": "Asynchronous I/O support for Python.",
                },
            ],
        },
    }


def test_baidu_parse_json():
    from metasearchmcp.providers.baidu import BaiduProvider

    provider = BaiduProvider()
    result = provider._parse(_baidu_payload())

    assert len(result.results) == 1
    item = result.results[0]
    assert item.title == "Python asyncio official docs"
    assert item.url == "https://docs.python.org/3/library/asyncio.html"
    assert item.provider == "baidu"

