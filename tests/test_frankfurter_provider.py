"""Unit tests for the Frankfurter foreign-exchange rate provider."""

from __future__ import annotations

import pytest

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.frankfurter import FrankfurterProvider

_SAMPLE_RATES: dict[str, object] = {
    "amount": 1.0,
    "base": "USD",
    "date": "2026-08-28",
    "rates": {
        "EUR": 0.85889,
        "JPY": 148.52,
        "GBP": 0.7542,
    },
}


def _provider() -> FrankfurterProvider:
    return FrankfurterProvider()


def test_name_and_tags() -> None:
    p = _provider()
    assert p.name == "frankfurter"
    assert p.tags == ["finance", "forex"]


def test_resolve_iso_code() -> None:
    assert _provider()._resolve("USD") == "USD"
    assert _provider()._resolve("usd") == "USD"
    assert _provider()._resolve("jpy") == "JPY"


def test_resolve_aliases() -> None:
    assert _provider()._resolve("euro") == "EUR"
    assert _provider()._resolve("dollar") == "USD"
    assert _provider()._resolve("swiss franc") == "CHF"
    assert _provider()._resolve("yen") == "JPY"
    assert _provider()._resolve("pound") == "GBP"
    assert _provider()._resolve("  Euro  ") == "EUR"


def test_resolve_unknown() -> None:
    assert _provider()._resolve("") == ""
    assert _provider()._resolve("zzzz") == ""
    assert _provider()._resolve("not-a-currency") == ""


def test_parse_basic() -> None:
    result = _provider()._parse(
        _SAMPLE_RATES,
        "USD",
        symbols=["EUR", "JPY", "GBP"],
    )

    assert len(result.results) == 3
    r = result.results[0]
    assert r.title == "EUR - Euro"
    assert r.url == "https://frankfurter.dev/?from=USD&to=EUR"
    assert r.provider == "frankfurter"
    assert r.source == "frankfurter.dev"
    assert r.published_date == "2026-08-28"
    assert "1 USD =" in r.snippet
    assert r.extra["code"] == "EUR"
    assert r.extra["base"] == "USD"
    assert r.extra["rate"] == 0.85889
    assert r.extra["amount"] == 1.0
    assert r.extra["converted_amount"] == 0.85889


def test_parse_amount_conversion() -> None:
    result = _provider()._parse(
        _SAMPLE_RATES,
        "USD",
        symbols=["JPY"],
        amount=100.0,
    )
    r = result.results[0]
    assert r.title == "JPY - Japanese Yen"
    assert "100 USD = 14852 JPY" in r.snippet
    assert r.extra["amount"] == 100.0
    assert r.extra["converted_amount"] == 14852.0


def test_parse_ranks() -> None:
    result = _provider()._parse(_SAMPLE_RATES, "USD", symbols=["EUR", "JPY", "GBP"])
    assert [r.rank for r in result.results] == [1, 2, 3]


def test_parse_skips_unknown_symbols() -> None:
    result = _provider()._parse(_SAMPLE_RATES, "USD", symbols=["EUR", "XXX", "JPY"])
    assert [r.extra["code"] for r in result.results] == ["EUR", "JPY"]


def test_parse_empty_and_malformed() -> None:
    assert _provider()._parse({}, "USD", symbols=["EUR"]).results == []
    assert _provider()._parse({"rates": "junk"}, "USD", symbols=["EUR"]).results == []
    assert _provider()._parse(None, "USD", symbols=["EUR"]).results == []
    malformed = _provider()._parse(
        {"rates": {"EUR": "not-a-number"}},
        "USD",
        symbols=["EUR"],
    )
    assert malformed.results == []


def test_fmt_amount() -> None:
    assert FrankfurterProvider._fmt_amount(0.85889) == "0.8589"
    assert FrankfurterProvider._fmt_amount(14852.0) == "14852"
    assert FrankfurterProvider._fmt_amount(0.0005) == "0.0005"


def test_is_available() -> None:
    """Keyless provider is always available."""
    assert _provider().is_available() is True


@pytest.mark.asyncio
async def test_search_resolved_currency(respx_mock) -> None:
    import respx

    respx_mock.get("https://api.frankfurter.dev/v1/currencies").mock(
        return_value=respx.MockResponse(
            200,
            json={
                "USD": "US Dollar",
                "EUR": "Euro",
                "JPY": "Japanese Yen",
                "GBP": "British Pound",
            },
        ),
    )
    respx_mock.get("https://api.frankfurter.dev/v1/latest").mock(
        return_value=respx.MockResponse(200, json=_SAMPLE_RATES),
    )

    p = _provider()
    result = await p.search("usd", SearchParams(num_results=5))

    assert len(result.results) == 3
    assert [r.extra["code"] for r in result.results] == ["EUR", "GBP", "JPY"]
    assert result.results[0].provider == "frankfurter"
    request = respx_mock.calls.last.request
    assert request.url.params["base"] == "USD"
    assert "EUR" in request.url.params["symbols"]


@pytest.mark.asyncio
async def test_search_unknown_currency_lists_against_eur(respx_mock) -> None:
    import respx

    respx_mock.get("https://api.frankfurter.dev/v1/latest").mock(
        return_value=respx.MockResponse(200, json=_SAMPLE_RATES),
    )

    p = _provider()
    result = await p.search("zzzz", SearchParams(num_results=5))

    assert len(result.results) == 3
    assert all(r.extra["base"] == "EUR" for r in result.results)
    request = respx_mock.calls.last.request
    assert request.url.params["base"] == "EUR"
