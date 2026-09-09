"""TheSportsDB sports search via the keyless public API.

``GET https://www.thesportsdb.com/api/v1/json/3/searchteams.php?t=QUERY``
and ``.../searchplayers.php?p=QUERY`` return matching sports teams and
players from TheSportsDB's community-maintained database as JSON.  No API
key is required (the public demo key ``3`` is used, mirroring the sibling
TheMealDB/TheCocktailDB providers already shipped here).

Team hits carry the team name, short code, sport, league, stadium and
capacity, location, founding year, badge image and official website.
Player hits carry the name, sport, current team, position, nationality,
birth date and status.  ``teams``/``player`` are ``null`` when nothing
matches the query.

Note: coverage is strongest for football/soccer.  The API is community-run
and free, and results are best-effort name matches.
"""

from __future__ import annotations

import asyncio
from typing import Any, ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_API_BASE_URL = "https://www.thesportsdb.com/api/v1/json/3"
_API_TEAMS_URL = f"{_API_BASE_URL}/searchteams.php"
_API_PLAYERS_URL = f"{_API_BASE_URL}/searchplayers.php"
# Search endpoints may return a large batch; cap what we keep per entity.
_MAX_API_RESULTS = 25


def _clean(value: object) -> str:
    """Collapse whitespace/control characters in a free-text field."""
    if value is None:
        return ""
    return " ".join(str(value).split())


def _team_page_url(team_id: object) -> str:
    """Build the canonical TheSportsDB team page URL from *team_id*."""
    return f"https://www.thesportsdb.com/team/{_clean(team_id)}"


def _player_page_url(player_id: object) -> str:
    """Build the canonical TheSportsDB player page URL from *player_id*."""
    return f"https://www.thesportsdb.com/player/{_clean(player_id)}"


class TheSportsDBProvider(BaseProvider):
    """Search sports teams and players on TheSportsDB.

    Keyless. Runs the team and player searches in parallel and merges the
    hits, teams first, so a query like ``\"Arsenal\"`` surfaces both the
    club and its players in one response.  Each hit carries sport, league,
    stadium/position metadata plus badge or photo URLs when available.
    """

    name = "thesportsdb"
    description = (
        "Search sports teams and players — league, stadium, position and "
        "more via the TheSportsDB public API, no API key required."
    )
    tags: ClassVar[list[str]] = ["sports", "media"]

    @staticmethod
    def _snippet(parts: list[str]) -> str:
        """Join non-empty metadata parts into a single truncated snippet."""
        return " | ".join(part for part in parts if part)[:MAX_SNIPPET_LENGTH]

    @staticmethod
    def _labeled(pairs: list[tuple[str, str]]) -> list[str]:
        """Build ``"Label: value"`` parts, skipping empty values."""
        return [f"{label}: {value}" for label, value in pairs if value]

    def _parse_teams(self, data: Any, limit: int | None = None) -> ProviderResult:
        """Parse a ``searchteams.php`` response into team results."""
        results: list[SearchResult] = []
        if not isinstance(data, dict):
            return ProviderResult(results=results)
        teams = data.get("teams")
        if not isinstance(teams, list):
            return ProviderResult(results=results)

        max_results = limit or self._max_results
        for item in teams[:max_results]:
            if not isinstance(item, dict):
                continue
            team_id = _clean(item.get("idTeam"))
            title = _clean(item.get("strTeam"))
            if not team_id or not title:
                continue

            sport = _clean(item.get("strSport"))
            league = _clean(item.get("strLeague"))
            stadium = _clean(item.get("strStadium"))
            capacity = _clean(item.get("intStadiumCapacity"))
            formed = _clean(item.get("intFormedYear"))
            location = _clean(item.get("strLocation")) or _clean(item.get("strCountry"))
            if stadium and capacity:
                stadium = f"{stadium} ({capacity})"

            snippet = self._snippet(
                self._labeled(
                    [
                        ("Sport", sport),
                        ("League", league),
                        ("Stadium", stadium),
                        ("Founded", formed),
                        ("Location", location),
                    ]
                )
            )
            results.append(
                SearchResult(
                    title=title,
                    url=_team_page_url(team_id),
                    snippet=snippet,
                    source="thesportsdb.com",
                    rank=len(results) + 1,
                    provider=self.name,
                    extra={
                        "type": "team",
                        "team_id": team_id,
                        "short_code": _clean(item.get("strTeamShort")),
                        "sport": sport,
                        "league": league,
                        "stadium": _clean(item.get("strStadium")),
                        "stadium_capacity": capacity,
                        "formed_year": formed,
                        "location": location,
                        "badge_url": _clean(item.get("strTeamBadge")),
                        "website": _clean(item.get("strWebsite")),
                    },
                ),
            )

        return ProviderResult(results=results)

    def _parse_players(self, data: Any, limit: int | None = None) -> ProviderResult:
        """Parse a ``searchplayers.php`` response into player results."""
        results: list[SearchResult] = []
        if not isinstance(data, dict):
            return ProviderResult(results=results)
        players = data.get("player")
        if not isinstance(players, list):
            return ProviderResult(results=results)

        max_results = limit or self._max_results
        for item in players[:max_results]:
            if not isinstance(item, dict):
                continue
            player_id = _clean(item.get("idPlayer"))
            title = _clean(item.get("strPlayer"))
            if not player_id or not title:
                continue

            sport = _clean(item.get("strSport"))
            team = _clean(item.get("strTeam"))
            position = _clean(item.get("strPosition"))
            nationality = _clean(item.get("strNationality"))
            born = _clean(item.get("dateBorn"))
            status = _clean(item.get("strStatus"))

            snippet = self._snippet(
                self._labeled(
                    [
                        ("Sport", sport),
                        ("Team", team),
                        ("Position", position),
                        ("Nationality", nationality),
                        ("Born", born),
                        ("Status", status),
                    ]
                )
            )
            photo = _clean(item.get("strThumb")) or _clean(item.get("strCutout"))
            results.append(
                SearchResult(
                    title=title,
                    url=_player_page_url(player_id),
                    snippet=snippet,
                    source="thesportsdb.com",
                    rank=len(results) + 1,
                    provider=self.name,
                    extra={
                        "type": "player",
                        "player_id": player_id,
                        "sport": sport,
                        "team": team,
                        "position": position,
                        "nationality": nationality,
                        "born": born,
                        "status": status,
                        "photo_url": photo,
                    },
                ),
            )

        return ProviderResult(results=results)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search TheSportsDB for teams and players matching *query*.

        Both searches run concurrently; team hits are listed before player
        hits, and the merged list is truncated to the requested limit.
        """
        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)
        async with self._client() as client:
            teams_resp, players_resp = await asyncio.gather(
                client.get(_API_TEAMS_URL, params={"t": query}),
                client.get(_API_PLAYERS_URL, params={"p": query}),
            )
            teams_resp.raise_for_status()
            players_resp.raise_for_status()
            teams_data = teams_resp.json()
            players_data = players_resp.json()

        teams = self._parse_teams(teams_data, limit=limit)
        players = self._parse_players(players_data, limit=limit)
        merged = teams.results + players.results
        for index, hit in enumerate(merged, start=1):
            hit.rank = index
        return ProviderResult(results=merged[:limit])
