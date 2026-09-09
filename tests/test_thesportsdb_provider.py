"""Unit tests for the TheSportsDB sports search provider."""

from __future__ import annotations

import pytest

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.thesportsdb import TheSportsDBProvider

_TEAMS_RESPONSE: dict[str, object] = {
    "teams": [
        {
            "idTeam": "133604",
            "strTeam": "Arsenal",
            "strTeamShort": "ARS",
            "intFormedYear": "1892",
            "strSport": "Soccer",
            "strLeague": "English Premier League",
            "strStadium": "Emirates Stadium",
            "intStadiumCapacity": "60338",
            "strLocation": "Holloway, London, England",
            "strTeamBadge": "https://r2.thesportsdb.com/images/media/team/badge/arsenal.png",
            "strWebsite": "www.arsenal.com",
        },
        {
            "idTeam": "133609",
            "strTeam": "Arsenal Women",
            "strSport": "Soccer",
            "strLeague": "FA Women's Super League",
        },
        "junk",  # type: ignore[list-item]
        {"strTeam": "No Id"},
        {"idTeam": "7"},
    ]
}

_PLAYERS_RESPONSE: dict[str, object] = {
    "player": [
        {
            "idPlayer": "34146304",
            "strPlayer": "Cristiano Ronaldo",
            "strTeam": "Al-Nassr",
            "strSport": "Soccer",
            "strPosition": "Forward",
            "strNationality": "Portugal",
            "dateBorn": "1985-02-05",
            "strStatus": "Active",
            "strThumb": "https://r2.thesportsdb.com/images/media/player/thumb/cr7.jpg",
        },
        {
            "idPlayer": "34146370",
            "strPlayer": "Ronaldo",
            "strTeam": "",
            "strSport": "Soccer",
            "strPosition": "Attacking Midfielder",
            "strNationality": "Brazil",
            "dateBorn": "1976-09-18",
            "strStatus": "Retired",
        },
    ]
}

_EMPTY_TEAMS_RESPONSE: dict[str, object] = {"teams": None}
_EMPTY_PLAYERS_RESPONSE: dict[str, object] = {"player": None}


def _provider() -> TheSportsDBProvider:
    return TheSportsDBProvider()


def test_name_and_tags() -> None:
    p = _provider()
    assert p.name == "thesportsdb"
    assert p.tags == ["sports", "media"]
    assert "no API key required" in p.description


def test_parse_teams_basic_hit_fields() -> None:
    p = _provider()
    result = p._parse_teams(_TEAMS_RESPONSE)

    assert len(result.results) == 2
    first = result.results[0]
    assert first.title == "Arsenal"
    assert first.url == "https://www.thesportsdb.com/team/133604"
    assert first.source == "thesportsdb.com"
    assert first.provider == "thesportsdb"
    assert first.rank == 1
    assert "Sport: Soccer" in first.snippet
    assert "League: English Premier League" in first.snippet
    assert "Stadium: Emirates Stadium (60338)" in first.snippet
    assert "Founded: 1892" in first.snippet
    assert first.extra["type"] == "team"
    assert first.extra["team_id"] == "133604"
    assert first.extra["short_code"] == "ARS"
    assert first.extra["badge_url"].startswith("https://")
    assert first.extra["website"] == "www.arsenal.com"


def test_parse_teams_skips_entries_without_id_or_title() -> None:
    p = _provider()
    result = p._parse_teams(_TEAMS_RESPONSE)
    # "junk" string, the title-only dict, and the id-only dict are skipped.
    assert len(result.results) == 2


def test_parse_players_basic_hit_fields() -> None:
    p = _provider()
    result = p._parse_players(_PLAYERS_RESPONSE)

    assert len(result.results) == 2
    first = result.results[0]
    assert first.title == "Cristiano Ronaldo"
    assert first.url == "https://www.thesportsdb.com/player/34146304"
    assert first.rank == 1
    assert "Team: Al-Nassr" in first.snippet
    assert "Position: Forward" in first.snippet
    assert "Nationality: Portugal" in first.snippet
    assert "Born: 1985-02-05" in first.snippet
    assert first.extra["type"] == "player"
    assert first.extra["player_id"] == "34146304"
    assert first.extra["status"] == "Active"
    assert first.extra["photo_url"].startswith("https://")


def test_parse_players_omits_empty_metadata() -> None:
    p = _provider()
    second = p._parse_players(_PLAYERS_RESPONSE).results[1]
    assert second.title == "Ronaldo"
    assert second.extra["team"] == ""
    assert "Team:" not in second.snippet
    assert "Born: 1976-09-18" in second.snippet


def test_parse_empty_and_malformed() -> None:
    p = _provider()
    assert p._parse_teams(_EMPTY_TEAMS_RESPONSE).results == []
    assert p._parse_players(_EMPTY_PLAYERS_RESPONSE).results == []
    assert p._parse_teams({}).results == []
    assert p._parse_players({}).results == []
    assert p._parse_teams(None).results == []
    assert p._parse_players("junk").results == []
    assert p._parse_teams({"teams": "junk"}).results == []


def test_parse_respects_limit() -> None:
    p = _provider()
    assert len(p._parse_teams(_TEAMS_RESPONSE, limit=1).results) == 1
    assert len(p._parse_players(_PLAYERS_RESPONSE, limit=1).results) == 1


def test_is_available() -> None:
    """Keyless provider is always available."""
    assert _provider().is_available() is True


@pytest.mark.asyncio
async def test_search_queries_teams_and_players(respx_mock) -> None:
    import respx

    respx_mock.get("https://www.thesportsdb.com/api/v1/json/3/searchteams.php").mock(
        return_value=respx.MockResponse(200, json=_TEAMS_RESPONSE)
    )
    respx_mock.get("https://www.thesportsdb.com/api/v1/json/3/searchplayers.php").mock(
        return_value=respx.MockResponse(200, json=_PLAYERS_RESPONSE)
    )

    p = _provider()
    result = await p.search("ronaldo", SearchParams(num_results=5))

    # Merged: team hits first, then player hits.
    assert [r.extra["type"] for r in result.results] == [
        "team",
        "team",
        "player",
        "player",
    ]
    assert [r.rank for r in result.results] == [1, 2, 3, 4]
    assert result.results[0].title == "Arsenal"
    assert result.results[2].title == "Cristiano Ronaldo"

    team_call = respx_mock.calls[0].request
    assert team_call.url.path.endswith("/searchteams.php")
    assert team_call.url.params["t"] == "ronaldo"
    player_call = respx_mock.calls[1].request
    assert player_call.url.path.endswith("/searchplayers.php")
    assert player_call.url.params["p"] == "ronaldo"


@pytest.mark.asyncio
async def test_search_truncates_merged_results_to_limit(respx_mock) -> None:
    import respx

    respx_mock.get("https://www.thesportsdb.com/api/v1/json/3/searchteams.php").mock(
        return_value=respx.MockResponse(200, json=_TEAMS_RESPONSE)
    )
    respx_mock.get("https://www.thesportsdb.com/api/v1/json/3/searchplayers.php").mock(
        return_value=respx.MockResponse(200, json=_PLAYERS_RESPONSE)
    )

    p = _provider()
    result = await p.search("ronaldo", SearchParams(num_results=3))

    assert len(result.results) == 3
    assert [r.extra["type"] for r in result.results] == ["team", "team", "player"]
    assert [r.rank for r in result.results] == [1, 2, 3]


@pytest.mark.asyncio
async def test_search_no_hits_returns_empty(respx_mock) -> None:
    import respx

    respx_mock.get("https://www.thesportsdb.com/api/v1/json/3/searchteams.php").mock(
        return_value=respx.MockResponse(200, json=_EMPTY_TEAMS_RESPONSE)
    )
    respx_mock.get("https://www.thesportsdb.com/api/v1/json/3/searchplayers.php").mock(
        return_value=respx.MockResponse(200, json=_EMPTY_PLAYERS_RESPONSE)
    )

    p = _provider()
    result = await p.search("zzqqxxyy", SearchParams(num_results=5))

    assert result.results == []
