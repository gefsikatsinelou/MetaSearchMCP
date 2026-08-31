"""Frankfurter currency exchange-rate search via the keyless public API.

Frankfurter (frankfurter.dev) is an open-source API that tracks foreign
exchange reference rates published daily by the European Central Bank.
It requires no API key:

``GET https://api.frankfurter.dev/v1/latest?base=USD&symbols=EUR&amount=100``

Each hit carries the ISO currency code, the human-readable currency name
(available from the companion ``/v1/currencies`` endpoint), the exchange
rate against the requested base currency, and the ECB reference date.
Rates are ECB reference rates, so they are reliable but not real-time
trading prices — they update once per business day.

The provider is keyless, uses only the shared httpx client, and tags
itself ``finance``/``forex`` so it participates in the ``finance`` tool
while remaining clearly distinct from stock-ticker providers.
"""

from __future__ import annotations

from typing import Any, ClassVar

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import BaseProvider

_API_URL = "https://api.frankfurter.dev/v1/latest"
_CURRENCIES_URL = "https://api.frankfurter.dev/v1/currencies"
# The API serves ECB reference rates that update once per business day.
_MAX_API_RESULTS = 30
# Map the query to this base currency when it is not itself a currency code.
_DEFAULT_BASE = "EUR"


class FrankfurterProvider(BaseProvider):
    """Search current ECB foreign-exchange reference rates.

    Keyless. Uses the Frankfurter public API, which serves daily reference
    rates published by the European Central Bank. A query may be an ISO
    4217 currency code (``USD``, ``JPY``, ...) or a common name/alias such
    as ``dollar``, ``euro``, ``yen``, ``pound`` or ``swiss franc``; the
    provider resolves it and returns the rate against the euro (the API's
    default base) plus the companion currency names.
    """

    name = "frankfurter"
    description = (
        "Current ECB foreign-exchange reference rates — convert or compare "
        "currencies (USD, EUR, GBP, JPY, ...) via the keyless Frankfurter API."
    )
    tags: ClassVar[list[str]] = ["finance", "forex"]

    # ISO 4217 code -> common English name/aliases for query resolution.
    _CURRENCY_ALIASES: ClassVar[dict[str, tuple[str, ...]]] = {
        "USD": ("dollar", "usd", "us dollar", "buck"),
        "EUR": ("euro", "eur", "euros"),
        "GBP": ("pound", "gbp", "british pound", "sterling", "quid"),
        "JPY": ("yen", "jpy", "japanese yen", "yen japanese"),
        "CHF": ("swiss franc", "chf", "franc"),
        "CAD": ("canadian dollar", "cad", "loonie"),
        "AUD": ("australian dollar", "aud", "aussie"),
        "CNY": ("yuan", "cny", "renminbi", "rmb"),
        "INR": ("rupee", "inr", "indian rupee"),
        "KRW": ("won", "krw", "south korean won"),
        "BRL": ("real", "brl", "brazilian real"),
        "MXN": ("peso", "mxn", "mexican peso"),
        "NOK": ("norwegian krone", "nok", "krone"),
        "SEK": ("swedish krona", "sek", "krona"),
        "DKK": ("danish krone", "dkk"),
        "PLN": ("zloty", "pln", "polish zloty"),
        "TRY": ("lira", "try", "turkish lira"),
        "RUB": ("ruble", "rub", "russian ruble"),
        "ZAR": ("rand", "zar", "south african rand"),
        "SGD": ("singapore dollar", "sgd"),
        "HKD": ("hong kong dollar", "hkd"),
        "NZD": ("new zealand dollar", "nzd", "kiwi"),
        "ISK": ("icelandic krona", "isk"),
        "CZK": ("czech koruna", "czk", "koruna"),
        "HUF": ("forint", "huf", "hungarian forint"),
        "RON": ("romanian leu", "ron", "leu"),
        "BGN": ("bulgarian lev", "bgn", "lev"),
        "IDR": ("indonesian rupiah", "idr", "rupiah"),
        "MYR": ("ringgit", "myr", "malaysian ringgit"),
        "PHP": ("philippine peso", "php", "peso"),
        "THB": ("baht", "thb", "thai baht"),
    }
    # Codes served by the API but without a handy alias above.
    _CURRENCY_NAMES: ClassVar[dict[str, str]] = {
        "AUD": "Australian Dollar",
        "BRL": "Brazilian Real",
        "CAD": "Canadian Dollar",
        "CHF": "Swiss Franc",
        "CNY": "Chinese Renminbi Yuan",
        "CZK": "Czech Koruna",
        "DKK": "Danish Krone",
        "EUR": "Euro",
        "GBP": "British Pound",
        "HKD": "Hong Kong Dollar",
        "HUF": "Hungarian Forint",
        "IDR": "Indonesian Rupiah",
        "ILS": "Israeli New Shekel",
        "INR": "Indian Rupee",
        "ISK": "Icelandic Króna",
        "JPY": "Japanese Yen",
        "KRW": "South Korean Won",
        "MXN": "Mexican Peso",
        "MYR": "Malaysian Ringgit",
        "NOK": "Norwegian Krone",
        "NZD": "New Zealand Dollar",
        "PHP": "Philippine Peso",
        "PLN": "Polish Złoty",
        "RON": "Romanian Leu",
        "SEK": "Swedish Krona",
        "SGD": "Singapore Dollar",
        "THB": "Thai Baht",
        "TRY": "Turkish Lira",
        "USD": "US Dollar",
        "ZAR": "South African Rand",
    }

    @staticmethod
    def _clean(value: object) -> str:
        """Collapse whitespace in a free-text field."""
        if not value:
            return ""
        return " ".join(str(value).split())

    def _resolve(self, query: str) -> str:
        """Map *query* to an ISO 4217 currency code, or ``""`` when unknown.

        A query that already looks like a three-letter ISO code is used
        verbatim; otherwise the common names/aliases table is consulted.
        """
        q = self._clean(query).lower()
        if not q:
            return ""
        # Prefer known aliases/names over the raw ISO shape: "yen" must map
        # to JPY, not be misread as the (nonexistent) code YEN.
        for code, aliases in self._CURRENCY_ALIASES.items():
            if q in aliases:
                return code
        if len(q) == 3 and q.isalpha():
            return q.upper()
        return ""

    def _parse(
        self,
        data: Any,
        base: str,
        *,
        symbols: list[str],
        amount: float | None = None,
    ) -> ProviderResult:
        """Parse a Frankfurter rates response into structured results.

        ``symbols`` lists the rate keys the response should contain; it is
        the caller's responsibility to fetch them. Each rate becomes one
        result titled ``CODE - Name`` with the rate and ECB reference date.
        """
        results: list[SearchResult] = []
        if not isinstance(data, dict):
            return ProviderResult(results=results)

        rates = data.get("rates")
        if not isinstance(rates, dict):
            return ProviderResult(results=results)

        date = self._clean(data.get("date"))
        amount_value = float(amount) if amount is not None else 1.0
        base_code = self._clean(base).upper() or _DEFAULT_BASE

        for code in symbols:
            code = self._clean(code).upper()
            if not code or code not in rates:
                continue
            try:
                rate = float(rates[code])
            except (TypeError, ValueError):
                continue

            name = self._CURRENCY_NAMES.get(code, code)
            converted = round(rate * amount_value, 6)

            snippet_parts: list[str] = []
            if amount_value != 1.0:
                snippet_parts.append(
                    f"{self._fmt_amount(amount_value)} {base_code} = "
                    f"{self._fmt_amount(converted)} {code}"
                )
            else:
                snippet_parts.append(f"1 {base_code} = {self._fmt_amount(rate)} {code}")
            snippet_parts.append(f"ECB reference rate, {date or 'latest'}")

            results.append(
                SearchResult(
                    title=f"{code} - {name}",
                    url=f"https://frankfurter.dev/?from={base_code}&to={code}",
                    snippet=" | ".join(snippet_parts),
                    source="frankfurter.dev",
                    rank=len(results) + 1,
                    provider=self.name,
                    published_date=date or None,
                    extra={
                        "code": code,
                        "name": name,
                        "base": base_code,
                        "rate": rate,
                        "amount": amount_value,
                        "converted_amount": converted,
                        "date": date,
                    },
                ),
            )

        return ProviderResult(results=results)

    @staticmethod
    def _fmt_amount(value: float) -> str:
        """Format a currency amount without excessive trailing zeros."""
        if abs(value) >= 1000 or abs(value) < 0.01:
            return f"{value:.6f}".rstrip("0").rstrip(".")
        return f"{value:.4f}".rstrip("0").rstrip(".")

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search Frankfurter for exchange rates matching *query*.

        The query is resolved to a currency code (``USD``, ``euro``,
        ``yen``, ...). When it resolves, the rates of all other currencies
        against that base are returned; otherwise the query is treated as
        a free-text lookup and every currency the API serves is returned
        against the euro, which still lets a caller scan the list.
        """
        base = self._resolve(query)
        async with self._client() as client:
            if base:
                currencies_resp = await client.get(_CURRENCIES_URL)
                currencies_resp.raise_for_status()
                currencies = currencies_resp.json()
                if not isinstance(currencies, dict):
                    currencies = {}
                # Exclude the base itself; keep the query's resolved code
                # out of the result set to avoid a self-rate entry.
                symbols = sorted(
                    code for code in currencies if code != base and code.isalpha()
                )
                limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)
                symbols = symbols[:limit]
                rates_resp = await client.get(
                    _API_URL,
                    params={
                        "base": base,
                        "symbols": ",".join(symbols),
                    },
                )
                rates_resp.raise_for_status()
                data = rates_resp.json()
            else:
                # Unknown code: list all rates against the euro so the
                # caller can still find the currency they meant.
                rates_resp = await client.get(
                    _API_URL,
                    params={"base": _DEFAULT_BASE},
                )
                rates_resp.raise_for_status()
                data = rates_resp.json()
                limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)
                rates = data.get("rates")
                if isinstance(rates, dict):
                    symbols = sorted(rates.keys())[:limit]
                else:
                    symbols = []

        return self._parse(data, base or _DEFAULT_BASE, symbols=symbols)
