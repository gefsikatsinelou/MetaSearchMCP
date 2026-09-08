"""Unit tests for the OpenAIRE scholarly publication search provider."""

from __future__ import annotations

import httpx
import pytest

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.openaire import OpenAIREProvider

# Realistic XML-to-JSON payloads as returned by api.openaire.eu with
# ``format=json``: nested dicts/lists where text lives under ``"$"`` and
# attributes use ``@``-prefixed keys.

_DOI_RECORD: dict[str, object] = {
    "header": {
        "dri:objIdentifier": {"$": "doi_________::4daebb98defb9631deff7bb6a73adbd1"}
    },
    "metadata": {
        "oaf:entity": {
            "oaf:result": {
                "title": {
                    "@classid": "main title",
                    "$": "Quantum Computing Chips: Advances in Superconducting Qubits",
                },
                "creator": [
                    {"@rank": "1", "$": "Murali Krishna Pasupuleti"},
                    {"@rank": "2", "$": "Jane Doe"},
                    {"@rank": "3", "$": "Alice Smith"},
                    {"@rank": "4", "$": "Bob Johnson"},
                ],
                "pid": {
                    "@classid": "doi",
                    "@classname": "Digital Object Identifier",
                    "$": "10.62311/nesx/97877",
                },
                "description": {
                    "$": (
                        "<jats:p>Abstract: Quantum computing is on the brink of "
                        "transforming computation.</jats:p>"
                    )
                },
                "dateofacceptance": {"$": "2025-03-05"},
                "language": {"@classid": "en", "@classname": "English"},
                "bestaccessright": {
                    "@classid": "OPEN",
                    "@classname": "Open Access",
                },
                "publisher": {"$": "Nexus Editions"},
                "source": {"$": "Crossref"},
                "collectedfrom": {
                    "@name": "Crossref",
                    "@id": "openaire____::081b82f96300b6a6e3d282bad31cb6e2",
                },
            }
        }
    },
}

_HANDLE_RECORD: dict[str, object] = {
    "header": {
        "dri:objIdentifier": {"$": "hdl_________::a9f6add813675ec7a021a6e2a9679c7d"}
    },
    "metadata": {
        "oaf:entity": {
            "oaf:result": {
                "title": [
                    {
                        "@classid": "main title",
                        "$": "The Rise of Quantum Internet Computing",
                    },
                    {
                        "@classid": "main title",
                        "$": "The Rise of Quantum Internet Computing.",
                    },
                ],
                "creator": {"@rank": "1", "$": "Seng W. Loke"},
                "pid": [
                    {
                        "@classid": "handle",
                        "@classname": "Handle",
                        "$": "20.500.11815/4432",
                    },
                    {"@classid": "pmid", "@classname": "PubMed", "$": "99999999"},
                ],
                "dateofacceptance": {"$": "2022-01-01T00:00:00Z"},
                "language": {"@classid": "und", "@classname": "Undetermined"},
                "bestaccessright": {
                    "@classid": "CLOSED",
                    "@classname": "Closed Access",
                },
                "journal": {"@vol": "abs/2208.00733", "$": "CoRR"},
                "collectedfrom": [
                    {
                        "@name": "DataCite",
                        "@id": "openaire____::9e3be59865b2c1c335d32dae2fe7b254",
                    },
                    {
                        "@name": "DBLP",
                        "@id": "openaire____::d8b68cc0a53121f6f896883a7d60c1db",
                    },
                ],
            }
        }
    },
}

# Record with only an internal OpenAIRE originalId: no resolvable URL.
_UNRESOLVABLE_RECORD: dict[str, object] = {
    "metadata": {
        "oaf:entity": {
            "oaf:result": {
                "title": {"$": "Untraceable preprint"},
                "originalId": [
                    {"$": "50|datacite____::a9f6add813675ec7a021a6e2a9679c7d"}
                ],
            }
        }
    },
}

# Record with no title at all.
_TITLELESS_RECORD: dict[str, object] = {
    "metadata": {
        "oaf:entity": {
            "oaf:result": {
                "pid": {"@classid": "doi", "$": "10.1000/xyz123"},
            }
        }
    },
}


def _payload(*records: object) -> dict[str, object]:
    return {"response": {"results": {"result": list(records)}}}


def _provider() -> OpenAIREProvider:
    return OpenAIREProvider()


def test_name_and_tags() -> None:
    p = _provider()
    assert p.name == "openaire"
    assert p.tags == ["academic", "web"]
    assert "no API key required" in p.description


def test_parse_basic_hit_fields() -> None:
    p = _provider()
    result = p._parse(_payload(_DOI_RECORD))

    assert len(result.results) == 1
    first = result.results[0]
    assert first.title == "Quantum Computing Chips: Advances in Superconducting Qubits"
    assert first.url == "https://doi.org/10.62311/nesx/97877"
    assert first.source == "openaire.eu"
    assert first.provider == "openaire"
    assert first.rank == 1
    assert first.published_date == "2025-03-05"
    assert "Quantum computing is on the brink" in first.snippet
    assert "<jats:p>" not in first.snippet
    assert "Murali Krishna Pasupuleti, Jane Doe, Alice Smith, et al." in first.snippet
    assert "Access: Open Access" in first.snippet
    assert first.extra["doi"] == "10.62311/nesx/97877"
    assert first.extra["objid"] == "doi_________::4daebb98defb9631deff7bb6a73adbd1"
    assert len(first.extra["authors"]) == 4
    assert first.extra["container_title"] == ""
    assert first.extra["publisher"] == "Nexus Editions"
    assert first.extra["data_source"] == "Crossref"
    assert first.extra["access_right"] == "Open Access"
    assert first.extra["language"] == "en"


def test_parse_handle_fallback_and_title_dedupe() -> None:
    p = _provider()
    result = p._parse(_payload(_HANDLE_RECORD))

    assert len(result.results) == 1
    first = result.results[0]
    # Longest unique title variant wins (the duplicate has a trailing period).
    assert first.title == "The Rise of Quantum Internet Computing."
    assert first.url == "https://hdl.handle.net/20.500.11815/4432"
    assert first.published_date == "2022-01-01"
    assert "CoRR" in first.snippet
    assert "Seng W. Loke" in first.snippet
    assert "Access: Closed Access" in first.snippet
    assert first.extra["doi"] == ""
    assert first.extra["container_title"] == "CoRR"
    # No ``source`` node: falls back to the first collectedfrom name.
    assert first.extra["data_source"] == "DataCite"


def test_parse_skips_unusable_records() -> None:
    p = _provider()
    result = p._parse(_payload(_DOI_RECORD, _UNRESOLVABLE_RECORD, _TITLELESS_RECORD))
    # Only the record with a resolvable URL and a title is kept; the kept
    # record keeps rank 1 (sequential, not positional).
    assert len(result.results) == 1
    assert result.results[0].rank == 1


def test_parse_empty_and_malformed() -> None:
    p = _provider()
    assert p._parse(_payload()).results == []
    assert p._parse({}).results == []
    assert p._parse(None).results == []
    assert p._parse("junk").results == []
    assert p._parse({"response": {"results": "junk"}}).results == []
    assert p._parse(_payload("junk")).results == []
    # Metadata without an ``oaf:entity`` / ``oaf:result`` chain.
    broken = {"metadata": {"oaf:entity": {}}}
    assert p._parse(_payload(broken)).results == []


def test_is_available() -> None:
    """Keyless provider is always available."""
    assert _provider().is_available() is True


@pytest.mark.asyncio
async def test_search_sends_keywords_request(respx_mock) -> None:
    import respx

    respx_mock.get(
        "https://api.openaire.eu/search/publications",
        params={"keywords": "quantum computing", "format": "json", "size": "5"},
    ).mock(return_value=respx.MockResponse(200, json=_payload(_DOI_RECORD)))

    p = _provider()
    result = await p.search("quantum computing", SearchParams(num_results=5))

    assert len(result.results) == 1
    assert result.results[0].extra["doi"] == "10.62311/nesx/97877"
    assert respx_mock.calls[0].request.url.params["keywords"] == "quantum computing"
    assert respx_mock.calls[0].request.url.params["format"] == "json"


@pytest.mark.asyncio
async def test_search_http_error_raises(respx_mock) -> None:
    import respx

    respx_mock.get("https://api.openaire.eu/search/publications").mock(
        return_value=respx.MockResponse(500)
    )

    p = _provider()
    with pytest.raises(httpx.HTTPStatusError):
        await p.search("quantum computing", SearchParams(num_results=5))
