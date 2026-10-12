"""Unit tests for the keyless NHTSA vPIC vehicle provider."""

from __future__ import annotations

import pytest

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.nhtsa import NhtsaProvider

_VIN = "1HGCM82633A004352"

_VIN_RESPONSE: dict[str, object] = {
    "Count": 1,
    "Message": "Results returned successfully",
    "Results": [
        {
            "VIN": _VIN,
            "Make": "HONDA",
            "Model": "Accord",
            "ModelYear": "2003",
            "Trim": "EX",
            "BodyClass": "Sedan/Saloon",
            "VehicleType": "PASSENGER CAR",
            "DriveType": "FWD/Front-Wheel Drive",
            "EngineCylinders": "6",
            "DisplacementL": "3.0",
            "EngineHP": "240",
            "FuelTypePrimary": "Gasoline",
            "TransmissionStyle": "Automatic",
            "PlantCity": "Marysville",
            "PlantCountry": "United States (USA)",
            "ErrorCode": "0",
            "ErrorText": "0 - VIN decoded clean. Check Digit (9th position) ok.",
        },
    ],
}

_MODELS_RESPONSE: dict[str, object] = {
    "Count": 3,
    "Message": "Results returned successfully",
    "Results": [
        {
            "Make_ID": 474,
            "Make_Name": "HONDA",
            "Model_ID": 1861,
            "Model_Name": "Accord",
        },
        {
            "Make_ID": 474,
            "Make_Name": "HONDA",
            "Model_ID": 1862,
            "Model_Name": "Civic",
        },
        {"Make_ID": 474, "Make_Name": "HONDA", "Model_ID": 1863, "Model_Name": "Fit"},
    ],
}


def _provider() -> NhtsaProvider:
    return NhtsaProvider()


def test_name_tags_and_availability() -> None:
    p = _provider()
    assert p.name == "nhtsa"
    assert p.tags == ["vehicles", "automotive", "reference"]
    assert p.is_available() is True


def test_provider_is_registered() -> None:
    from metasearchmcp.providers.registry import build_registry

    registry = build_registry()
    assert "nhtsa" in registry
    assert registry["nhtsa"].tags == ["vehicles", "automotive", "reference"]


def test_clean_and_int_helpers() -> None:
    from metasearchmcp.providers.nhtsa import _clean, _int

    assert _clean(None) == ""
    assert _clean("  a   b  ") == "a b"
    assert _clean(0) == "0"
    assert _int(5) == 5
    assert _int(5.9) == 5
    assert _int(True) is None
    assert _int("5") is None
    assert _int(None) is None


def test_looks_like_vin() -> None:
    assert _provider()._looks_like_vin(_VIN) is True
    assert _provider()._looks_like_vin(_VIN.lower()) is True
    assert _provider()._looks_like_vin("too-short") is False
    assert _provider()._looks_like_vin("1HGCM82633A00435I") is False  # contains I


def test_make_guesses_narrows_trailing_tokens() -> None:
    guesses = _provider()._make_guesses("honda civic")
    assert guesses == [("honda civic", []), ("honda", ["civic"])]


def test_make_guesses_drops_single_char_filters() -> None:
    # A one-letter trailing token is too broad to be a useful model filter.
    guesses = _provider()._make_guesses("honda e")
    assert guesses == [("honda e", []), ("honda", [])]


def test_parse_vin_builds_full_record() -> None:
    result = _provider()._parse_vin(_VIN_RESPONSE, _VIN)

    assert len(result.results) == 1
    r = result.results[0]
    assert r.title == "2003 HONDA Accord EX"
    assert r.provider == "nhtsa"
    assert r.source == "vpic.nhtsa.dot.gov"
    assert r.rank == 1
    assert r.extra["vin"] == _VIN
    assert r.extra["make"] == "HONDA"
    assert r.extra["model"] == "Accord"
    assert r.extra["model_year"] == "2003"
    assert r.extra["fuel_type"] == "Gasoline"
    assert "Engine: 3.0L 6-cyl 240 hp" in r.snippet
    assert "Body: Sedan/Saloon" in r.snippet
    assert "Fuel: Gasoline" in r.snippet
    assert "decode_error" not in r.extra


def test_parse_vin_handles_junk() -> None:
    assert _provider()._parse_vin("junk", _VIN).results == []
    assert _provider()._parse_vin({}, _VIN).results == []
    assert _provider()._parse_vin({"Results": []}, _VIN).results == []
    assert _provider()._parse_vin({"Results": ["junk"]}, _VIN).results == []


def test_parse_vin_records_decode_error() -> None:
    payload = {
        "Results": [
            {
                "Make": "HONDA",
                "Model": "",
                "ErrorCode": "1",
                "ErrorText": "1 - Check Digit (9th position) not valid.",
            },
        ],
    }
    r = _provider()._parse_vin(payload, _VIN).results[0]
    assert r.extra["decode_error"].startswith("1 - Check Digit")


def test_parse_models_filters_by_trailing_token() -> None:
    result = _provider()._parse_models(_MODELS_RESPONSE, ["civic"], limit=10)

    assert [r.title for r in result.results] == ["HONDA Civic"]
    r = result.results[0]
    assert r.rank == 1
    assert r.provider == "nhtsa"
    assert r.extra["model"] == "Civic"
    assert r.extra["model_id"] == 1862


def test_parse_models_without_filter_keeps_all() -> None:
    result = _provider()._parse_models(_MODELS_RESPONSE, [], limit=10)
    assert [r.title for r in result.results] == [
        "HONDA Accord",
        "HONDA Civic",
        "HONDA Fit",
    ]


def test_parse_models_respects_limit_and_junk() -> None:
    assert _provider()._parse_models("junk", [], limit=5).results == []
    assert _provider()._parse_models({"Results": "junk"}, [], limit=5).results == []
    limited = _provider()._parse_models(_MODELS_RESPONSE, [], limit=2)
    assert len(limited.results) == 2


@pytest.mark.asyncio
async def test_search_decodes_vin(respx_mock) -> None:
    import respx

    route = respx_mock.get(
        url__regex=r".*/DecodeVinValues/.*",
    ).mock(return_value=respx.MockResponse(200, json=_VIN_RESPONSE))

    result = await _provider().search(_VIN, SearchParams(num_results=5))

    assert len(result.results) == 1
    assert result.results[0].title == "2003 HONDA Accord EX"
    assert route.called


@pytest.mark.asyncio
async def test_search_lists_models_for_make(respx_mock) -> None:
    import respx

    # The whole query ("honda civic") returns nothing, so the provider falls
    # back to "honda" with "civic" as a model filter.
    def _handler(request):
        if "honda%20civic" in str(request.url) or "honda civic" in str(request.url):
            return respx.MockResponse(200, json={"Results": []})
        return respx.MockResponse(200, json=_MODELS_RESPONSE)

    respx_mock.get(url__regex=r".*/GetModelsForMake/.*").mock(side_effect=_handler)

    result = await _provider().search("honda civic", SearchParams(num_results=5))

    assert [r.title for r in result.results] == ["HONDA Civic"]


@pytest.mark.asyncio
async def test_search_with_blank_query_returns_empty(respx_mock) -> None:
    import respx

    route = respx_mock.get(url__regex=r".*vpic.*").mock(
        return_value=respx.MockResponse(200, json=_MODELS_RESPONSE),
    )

    result = await _provider().search("   ", SearchParams(num_results=5))

    assert result.results == []
    assert not route.called


@pytest.mark.asyncio
async def test_search_tolerates_non_json_response(respx_mock) -> None:
    import respx

    respx_mock.get(url__regex=r".*/DecodeVinValues/.*").mock(
        return_value=respx.MockResponse(
            200,
            text="<html><body>maintenance</body></html>",
            headers={"Content-Type": "text/html"},
        ),
    )

    result = await _provider().search(_VIN, SearchParams(num_results=5))

    assert result.results == []
