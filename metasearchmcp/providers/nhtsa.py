"""Vehicle make/model lookup and VIN decoding via the keyless NHTSA vPIC API.

The U.S. National Highway Traffic Safety Administration publishes the official
vehicle *make/model* catalog and a free VIN decoder through its *Product
Information Catalog and Vehicle Listing* (vPIC) service.  Both are plain,
keyless JSON endpoints:

* ``GET .../GetModelsForMake/{make}?format=json`` — every model a make has
  fielded (e.g. ``honda`` or ``aston martin``).
* ``GET .../DecodeVinValues/{vin}?format=json`` — the decoded record for a
  17-character VIN: make, model, model year, body class, engine, drive type,
  fuel, assembly plant and more.

A query that follows the VIN character rules is decoded; anything else is
treated as a make name whose models are listed.  No API key is required.
"""

from __future__ import annotations

from typing import Any, ClassVar
from urllib.parse import quote

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_API_BASE = "https://vpic.nhtsa.dot.gov/api/vehicles"
_SOURCE = "vpic.nhtsa.dot.gov"
# Human-facing vPIC VIN decoder, linked from decoded-VIN results.
_DECODER_URL = "https://vpic.nhtsa.dot.gov/decoder/"
# vPIC returns every model a make ever built; cap the page we surface.
_MAX_API_RESULTS = 50
# A VIN is exactly 17 characters and never uses I, O or Q.
_VIN_LENGTH = 17
_VIN_CHARS = frozenset("ABCDEFGHJKLMNPRSTUVWXYZ0123456789")
# Bound the "which leading tokens are the make?" guessing for multi-word queries.
_MAX_MAKE_ATTEMPTS = 4


def _clean(value: object) -> str:
    """Collapse whitespace in a free-text field, returning ``""`` for empties."""
    if value is None:
        return ""
    return " ".join(str(value).split())


def _int(value: object) -> int | None:
    """Return *value* as an int, or ``None`` when it is not a real number."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(value)


class NhtsaProvider(BaseProvider):
    """Decode a VIN, or list a make's models, on the keyless NHTSA vPIC API.

    A 17-character query that satisfies the VIN character rules is decoded into
    the vehicle's full record; any other query is treated as a make name
    (``honda``, ``aston martin``) whose models are returned.  When a query mixes
    a make with a model (``honda civic``), the whole query is tried first and
    then progressively shorter leading runs of tokens are tried as the make,
    with the trailing tokens narrowing the returned models.
    """

    name = "nhtsa"
    description = (
        "Decode a 17-character VIN or list the models a vehicle make builds via "
        "the keyless NHTSA vPIC API — make, model, year, body class, engine, "
        "drive type, fuel and assembly plant, no API key required."
    )
    tags: ClassVar[list[str]] = ["vehicles", "automotive", "reference"]

    @staticmethod
    def _looks_like_vin(value: str) -> bool:
        """Return True when *value* follows the 17-character VIN rules."""
        if len(value) != _VIN_LENGTH:
            return False
        return all(char in _VIN_CHARS for char in value.upper())

    @staticmethod
    def _make_guesses(query: str) -> list[tuple[str, list[str]]]:
        """Return ``(make, model-filters)`` guesses for a free-text query.

        The whole query is tried first, then progressively shorter leading runs
        of tokens (bounded to ``_MAX_MAKE_ATTEMPTS`` attempts) so that
        ``honda civic`` first tries ``honda civic`` and then ``honda`` with
        ``civic`` as a model filter.  Only trailing tokens of two or more
        characters become filters, since one-letter fragments match far too
        broadly.
        """
        tokens = query.split()
        guesses: list[tuple[str, list[str]]] = []
        for end in range(len(tokens), 0, -1):
            if len(guesses) >= _MAX_MAKE_ATTEMPTS:
                break
            make = " ".join(tokens[:end])
            filters = [token.lower() for token in tokens[end:] if len(token) >= 2]
            guesses.append((make, filters))
        return guesses

    @staticmethod
    def _has_results(payload: object) -> bool:
        """Return True when *payload* carries a non-empty ``Results`` list."""
        return (
            isinstance(payload, dict)
            and isinstance(payload.get("Results"), list)
            and bool(payload["Results"])
        )

    @staticmethod
    def _engine_summary(item: dict[str, Any]) -> str:
        """Compose an engine description from the decoded cylinder fields."""
        displacement = _clean(item.get("DisplacementL"))
        cylinders = _clean(item.get("EngineCylinders"))
        horsepower = _clean(item.get("EngineHP"))
        bits: list[str] = []
        if displacement and displacement != "0":
            bits.append(f"{displacement}L")
        if cylinders and cylinders != "0":
            bits.append(f"{cylinders}-cyl")
        if horsepower and horsepower != "0":
            bits.append(f"{horsepower} hp")
        return "Engine: " + " ".join(bits) if bits else ""

    @classmethod
    def _vehicle_title(cls, item: dict[str, Any], vin: str) -> str:
        """Compose a ``YEAR MAKE MODEL TRIM`` title for a decoded VIN."""
        parts = [
            _clean(item.get("ModelYear")),
            _clean(item.get("Make")),
            _clean(item.get("Model")),
        ]
        title = " ".join(part for part in parts if part)
        trim = _clean(item.get("Trim"))
        if trim:
            title = f"{title} {trim}".strip()
        return title or f"VIN {vin}"

    @classmethod
    def _vin_snippet(cls, item: dict[str, Any]) -> str:
        """Compose a one-line summary of a decoded VIN record."""
        parts: list[str] = []
        vehicle_type = _clean(item.get("VehicleType"))
        if vehicle_type:
            parts.append(vehicle_type)
        body_class = _clean(item.get("BodyClass"))
        if body_class:
            parts.append(f"Body: {body_class}")
        drive_type = _clean(item.get("DriveType"))
        if drive_type:
            parts.append(f"Drive: {drive_type}")
        engine = cls._engine_summary(item)
        if engine:
            parts.append(engine)
        fuel = _clean(item.get("FuelTypePrimary"))
        if fuel:
            parts.append(f"Fuel: {fuel}")
        transmission = _clean(item.get("TransmissionStyle"))
        if transmission:
            parts.append(f"Transmission: {transmission}")
        plant_city = _clean(item.get("PlantCity"))
        plant_country = _clean(item.get("PlantCountry"))
        plant = ", ".join(part for part in (plant_city, plant_country) if part)
        if plant:
            parts.append(f"Built: {plant}")
        return " | ".join(parts)[:MAX_SNIPPET_LENGTH]

    @classmethod
    def _build_vin_result(cls, item: dict[str, Any], vin: str) -> SearchResult | None:
        """Build one :class:`SearchResult` from a decoded-VIN record, or ``None``."""
        make = _clean(item.get("Make"))
        model = _clean(item.get("Model"))
        if not make and not model:
            return None

        extra: dict[str, Any] = {
            "vin": _clean(item.get("VIN")) or vin,
            "make": make or None,
            "model": model or None,
            "model_year": _clean(item.get("ModelYear")) or None,
            "trim": _clean(item.get("Trim")) or None,
            "body_class": _clean(item.get("BodyClass")) or None,
            "vehicle_type": _clean(item.get("VehicleType")) or None,
            "drive_type": _clean(item.get("DriveType")) or None,
            "engine_cylinders": _clean(item.get("EngineCylinders")) or None,
            "displacement_l": _clean(item.get("DisplacementL")) or None,
            "engine_hp": _clean(item.get("EngineHP")) or None,
            "fuel_type": _clean(item.get("FuelTypePrimary")) or None,
            "transmission": _clean(item.get("TransmissionStyle")) or None,
            "plant_city": _clean(item.get("PlantCity")) or None,
            "plant_country": _clean(item.get("PlantCountry")) or None,
        }
        error_code = _clean(item.get("ErrorCode"))
        error_text = _clean(item.get("ErrorText"))
        if error_code and error_code != "0" and error_text:
            extra["decode_error"] = error_text

        return SearchResult(
            title=cls._vehicle_title(item, vin),
            url=_DECODER_URL,
            snippet=cls._vin_snippet(item),
            source=_SOURCE,
            rank=1,
            provider=cls.name,
            extra=extra,
        )

    def _parse_vin(self, payload: object, vin: str) -> ProviderResult:
        """Parse a ``DecodeVinValues`` response into a single result."""
        if not self._has_results(payload):
            return ProviderResult(results=[])
        first = payload["Results"][0]  # type: ignore[index]
        if not isinstance(first, dict):
            return ProviderResult(results=[])
        built = self._build_vin_result(first, vin)
        return ProviderResult(results=[built] if built is not None else [])

    @classmethod
    def _build_model_result(
        cls, item: dict[str, Any], rank: int
    ) -> SearchResult | None:
        """Build one :class:`SearchResult` from a make-model record, or ``None``."""
        make = _clean(item.get("Make_Name"))
        model = _clean(item.get("Model_Name"))
        if not model:
            return None

        title = " ".join(part for part in (make, model) if part)
        url = (
            f"{_API_BASE}/GetModelsForMake/{quote(make, safe='')}?format=json"
            if make
            else _API_BASE
        )
        snippet_parts: list[str] = []
        if make:
            snippet_parts.append(f"Model built by {make}")
        make_id = _int(item.get("Make_ID"))
        if make_id is not None:
            snippet_parts.append(f"make id {make_id}")
        model_id = _int(item.get("Model_ID"))
        if model_id is not None:
            snippet_parts.append(f"model id {model_id}")

        return SearchResult(
            title=title,
            url=url,
            snippet=" | ".join(snippet_parts)[:MAX_SNIPPET_LENGTH],
            source=_SOURCE,
            rank=rank,
            provider=cls.name,
            extra={
                "make": make or None,
                "model": model,
                "make_id": make_id,
                "model_id": model_id,
            },
        )

    def _parse_models(
        self, payload: object, filters: list[str], limit: int
    ) -> ProviderResult:
        """Parse a ``GetModelsForMake`` response, keeping models matching *filters*.

        *filters* are lowercase substrings that must all appear in a model name;
        an empty list keeps every model returned.
        """
        results: list[SearchResult] = []
        if not isinstance(payload, dict):
            return ProviderResult(results=results)
        items = payload.get("Results")
        if not isinstance(items, list):
            return ProviderResult(results=results)

        for item in items:
            if len(results) >= limit:
                break
            if not isinstance(item, dict):
                continue
            model = _clean(item.get("Model_Name")).lower()
            if filters and not all(token in model for token in filters):
                continue
            built = self._build_model_result(item, len(results) + 1)
            if built is not None:
                results.append(built)
        return ProviderResult(results=results)

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search NHTSA vPIC for a VIN or a make's models.

        A blank query performs no request.  A VIN-shaped query is decoded into
        its vehicle record; otherwise the query is treated as a make and the
        first guess that yields models is returned.
        """
        cleaned = query.strip()
        if not cleaned:
            return ProviderResult(results=[])

        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)

        if self._looks_like_vin(cleaned):
            url = f"{_API_BASE}/DecodeVinValues/{quote(cleaned, safe='')}"
            async with self._client() as client:
                resp = await client.get(url, params={"format": "json"})
                resp.raise_for_status()
                try:
                    payload = resp.json()
                except ValueError:
                    return ProviderResult(results=[])
            return self._parse_vin(payload, cleaned)

        async with self._client() as client:
            for make, filters in self._make_guesses(cleaned):
                url = f"{_API_BASE}/GetModelsForMake/{quote(make, safe='')}"
                resp = await client.get(url, params={"format": "json"})
                resp.raise_for_status()
                try:
                    payload = resp.json()
                except ValueError:
                    continue
                if self._has_results(payload):
                    return self._parse_models(payload, filters, limit)
        return ProviderResult(results=[])
