"""OSV.dev open source vulnerability search.

OSV (https://osv.dev) is Google's keyless aggregation of security advisories
for open source packages.  It normalizes GitHub Security Advisories, the Python
``PYSEC`` database (pip-audit), RustSec, the Go vulnerability database, OSS-Fuzz
bug reports and the Debian/Ubuntu/Alpine security trackers into one schema, and
its REST API needs no API key:

* ``GET  https://api.osv.dev/v1/vulns/<id>`` — one advisory by id
* ``POST https://api.osv.dev/v1/query`` — every advisory affecting a package
* ``POST https://api.osv.dev/v1/querybatch`` — the same for several packages

The query endpoint matches *packages*, not free text, so this provider
translates what agents actually type into the shapes OSV understands:

* an advisory id — ``GHSA-jf85-cpcp-j695``, ``CVE-2021-44228``,
  ``PYSEC-2021-1``, ``GO-2021-0113`` — is fetched directly;
* ``ecosystem:package[@version]`` (``pypi:requests@2.19.0``,
  ``maven:org.apache.logging.log4j:log4j-core``) or
  ``ecosystem package [version]`` (``npm lodash 4.17.11``,
  ``go golang.org/x/text``) queries one package in one ecosystem;
* a bare package name (``lodash``, ``lodash@4.17.11``) is broadcast over the
  default ecosystems (npm, PyPI, Go, Maven, crates.io, NuGet, RubyGems,
  Packagist, Hex, Pub, Debian, Alpine, OSS-Fuzz, GitHub Actions), because OSV
  requires an ecosystem and a name such as ``requests`` is ambiguous.

Advisories without a published version range list an affected package only, so
``pypi:requests`` (no version) is the "everything ever reported for this
package" query, while ``pypi:requests@2.19.0`` answers the dependency-audit
question "is what I have pinned vulnerable".

Unlike :mod:`metasearchmcp.providers.nvd` and
:mod:`metasearchmcp.providers.cisa_kev`, which are keyed by CVE for a product
or vendor, this provider is keyed by package and reports the exact fixed
versions, the CVE/GHSA aliases, the CVSS vector, CWE identifiers and the
advisory date.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from typing import Any, ClassVar, Literal

from metasearchmcp.contracts import ProviderResult, SearchParams, SearchResult

from .base import MAX_SNIPPET_LENGTH, BaseProvider

_API_BASE = "https://api.osv.dev"
_QUERY_URL = f"{_API_BASE}/v1/query"
_QUERYBATCH_URL = f"{_API_BASE}/v1/querybatch"
_VULN_URL = f"{_API_BASE}/v1/vulns/{{vuln_id}}"
_DETAIL_URL = "https://osv.dev/vulnerability/{vuln_id}"

# The query endpoint pages at 100 records, so asking for more is pointless.
_MAX_API_RESULTS = 100
# Advisory detail lookups issued for one ecosystem-less package name.
_MAX_DETAIL_FETCHES = 10
# Characters allowed in a package name (npm scopes and Go module paths use /).
_NAME_RE = re.compile(r"@?[A-Za-z0-9][A-Za-z0-9._+~-]*(?:/[A-Za-z0-9._+~@-]+)*")
# Names given with an explicit ecosystem may also be Maven-style group:artifact.
_SCOPED_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+~:@/-]*")
_VERSION_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+~-]*")

# Ids of the advisory databases OSV aggregates; the prefix decides that a query
# such as ``CVE-2021-44228`` is an id rather than a package name.
_ID_PREFIXES = frozenset(
    {
        "GHSA",
        "CVE",
        "OSV",
        "PYSEC",
        "RUSTSEC",
        "GO",
        "GMS",
        "GLAD",
        "HSEC",
        "MAL",
        "BIT",
        "DSA",
        "DLA",
        "USN",
        "UBUNTU",
        "DEBIAN",
        "ALPINE",
        "RHSA",
        "RLSA",
        "LBSEC",
        "MGASA",
        "OESA",
        "PHSA",
        "SNYK",
        "ZDI",
        "EEF",
        "CGA",
        "DRUPAL",
    }
)

# Ecosystems searched for a bare package name, in priority order.
_DEFAULT_ECOSYSTEMS = (
    "npm",
    "PyPI",
    "Go",
    "Maven",
    "crates.io",
    "NuGet",
    "RubyGems",
    "Packagist",
    "Hex",
    "Pub",
    "Debian",
    "Alpine",
    "OSS-Fuzz",
    "GitHub Actions",
)

# Ecosystem spellings accepted in queries, mapped to the canonical OSV name.
_ECOSYSTEM_ALIASES = {
    "npm": "npm",
    "node": "npm",
    "nodejs": "npm",
    "pypi": "PyPI",
    "python": "PyPI",
    "pip": "PyPI",
    "go": "Go",
    "golang": "Go",
    "maven": "Maven",
    "java": "Maven",
    "cargo": "crates.io",
    "crates": "crates.io",
    "crates.io": "crates.io",
    "rust": "crates.io",
    "nuget": "NuGet",
    "dotnet": "NuGet",
    "rubygems": "RubyGems",
    "gem": "RubyGems",
    "ruby": "RubyGems",
    "packagist": "Packagist",
    "composer": "Packagist",
    "php": "Packagist",
    "hex": "Hex",
    "elixir": "Hex",
    "pub": "Pub",
    "dart": "Pub",
    "debian": "Debian",
    "deb": "Debian",
    "ubuntu": "Ubuntu",
    "alpine": "Alpine",
    "oss-fuzz": "OSS-Fuzz",
    "ossfuzz": "OSS-Fuzz",
    "github-actions": "GitHub Actions",
    "actions": "GitHub Actions",
    "cran": "CRAN",
    "hackage": "Hackage",
    "bioconductor": "Bioconductor",
    "conancenter": "ConanCenter",
    "conan": "ConanCenter",
    "swifturl": "SwiftURL",
    "swift": "SwiftURL",
    "linux": "Linux",
    "ghc": "GHC",
    "opensuse": "openSUSE",
    "redhat": "Red Hat",
    "rocky": "Rocky Linux",
    "almalinux": "AlmaLinux",
    "suse": "SUSE",
    "wolfi": "Wolfi",
    "chainguard": "Chainguard",
    "android": "Android",
    "bitnami": "Bitnami",
}

# Words agents append to a package name that OSV itself never uses.
_NOISE_WORDS = frozenset(
    {
        "advisories",
        "advisory",
        "cve",
        "cves",
        "library",
        "package",
        "packages",
        "pkg",
        "security",
        "vuln",
        "vulns",
        "vulnerabilities",
        "vulnerability",
    }
)


@dataclass(frozen=True)
class QueryPlan:
    """A parsed OSV query: an advisory id, or a package to look up."""

    kind: Literal["id", "package", "name"]
    value: str
    ecosystem: str = ""
    version: str = ""


def parse_vulnerability_id(query: str) -> str | None:
    """Return *query* when it names an advisory id, else ``None``.

    An id is a single token whose first ``-``-separated segment is a known
    advisory-database prefix and which contains at least one digit, so
    ``CVE-2021-44228`` and ``GHSA-jf85-cpcp-j695`` are ids while ``node-fetch``
    and ``go-lang`` are not.
    """
    if not query or any(char.isspace() for char in query):
        return None
    prefix, separator, rest = query.partition("-")
    if not separator or not rest:
        return None
    if prefix.upper() not in _ID_PREFIXES:
        return None
    if not any(char.isdigit() for char in query):
        return None
    return query


def parse_ecosystem(token: str) -> str | None:
    """Return the canonical OSV ecosystem name for *token*, else ``None``."""
    return _ECOSYSTEM_ALIASES.get(token.strip().lower())


def _split_version(
    text: str,
    pattern: re.Pattern[str],
) -> tuple[str, str] | None:
    """Split ``name[@version]`` or ``name version`` into ``(name, version)``.

    A leading ``@`` belongs to a scoped npm name (``@scope/pkg@1.2.3``), so only
    an ``@`` after the first character separates a version.  ``None`` is
    returned when the name or the version does not look like one.
    """
    if any(char.isspace() for char in text):
        name, _, version = text.partition(" ")
        version = version.strip()
    else:
        name, separator, version = text[1:].rpartition("@")
        if separator:
            name = text[:1] + name
        else:
            name, version = text, ""
    if not name or not pattern.fullmatch(name):
        return None
    if version and not _VERSION_RE.fullmatch(version):
        return None
    return name, version


def build_query(query: str) -> QueryPlan | None:
    """Translate *query* into the OSV lookup that answers it, else ``None``.

    An empty query, or one that names neither an advisory id nor a package
    (free text such as ``prototype pollution in lodash``), yields ``None`` so no
    request is made.
    """
    cleaned = " ".join(query.split())
    if not cleaned:
        return None

    vuln_id = parse_vulnerability_id(cleaned)
    if vuln_id:
        return QueryPlan(kind="id", value=vuln_id)

    head, separator, rest = cleaned.partition(":")
    if not separator:
        head, separator, rest = cleaned.partition("/")
    if separator:
        ecosystem = parse_ecosystem(head)
        if ecosystem is not None:
            parsed = _split_version(rest, _SCOPED_NAME_RE)
            if parsed is None:
                return None
            return QueryPlan(
                kind="package",
                value=parsed[0],
                ecosystem=ecosystem,
                version=parsed[1],
            )

    tokens = cleaned.split()
    if len(tokens) > 1:
        ecosystem = parse_ecosystem(tokens[0])
        if ecosystem is not None:
            parsed = _split_version(" ".join(tokens[1:]), _SCOPED_NAME_RE)
            if parsed is None:
                return None
            return QueryPlan(
                kind="package",
                value=parsed[0],
                ecosystem=ecosystem,
                version=parsed[1],
            )
        while len(tokens) > 1 and tokens[-1].lower() in _NOISE_WORDS:
            tokens.pop()

    if len(tokens) == 1:
        parsed = _split_version(tokens[0], _NAME_RE)
    elif len(tokens) == 2 and _VERSION_RE.fullmatch(tokens[1]):
        parsed = (tokens[0], tokens[1]) if _NAME_RE.fullmatch(tokens[0]) else None
    else:
        parsed = None
    if parsed is None:
        return None
    return QueryPlan(kind="name", value=parsed[0], version=parsed[1])


def _mapping(value: object) -> dict[str, Any]:
    """Return *value* as a mapping, else an empty mapping."""
    return value if isinstance(value, dict) else {}


def _clean_text(value: object) -> str:
    """Return *value* as whitespace-normalized text, else ``""``."""
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())


def _str_list(value: object) -> list[str]:
    """Return *value* as a list of non-empty, deduplicated strings."""
    if not isinstance(value, list):
        return []
    items: list[str] = []
    seen: set[str] = set()
    for item in value:
        cleaned = _clean_text(item)
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            items.append(cleaned)
    return items


def _excerpt(text: str, limit: int) -> str:
    """Return a whitespace-collapsed, truncated excerpt of *text*."""
    return text if len(text) <= limit else text[:limit].rstrip()


def _severity_label(vuln: dict[str, Any]) -> str:
    """Return the advisory severity ("HIGH", "CRITICAL", ...), else ``""``.

    GitHub-reviewed advisories carry the label in ``database_specific``;
    distro trackers put it under the affected package instead.
    """
    label = _clean_text(_mapping(vuln.get("database_specific")).get("severity"))
    if label:
        return label
    affected = vuln.get("affected")
    if isinstance(affected, list):
        for entry in affected:
            entry_map = _mapping(entry)
            for key in ("ecosystem_specific", "database_specific"):
                label = _clean_text(_mapping(entry_map.get(key)).get("severity"))
                if label:
                    return label
    return ""


def _cvss(vuln: dict[str, Any]) -> tuple[str, str]:
    """Return ``(CVSS version, vector)``, preferring the newest version."""
    entries = vuln.get("severity")
    if not isinstance(entries, list):
        return "", ""
    found: dict[str, str] = {}
    for entry in entries:
        entry_map = _mapping(entry)
        cvss_type = _clean_text(entry_map.get("type")).upper()
        score = _clean_text(entry_map.get("score"))
        if score and cvss_type and cvss_type not in found:
            found[cvss_type] = score
    for cvss_type in ("CVSS_V4", "CVSS_V3", "CVSS_V2"):
        if cvss_type in found:
            return cvss_type, found[cvss_type]
    if found:
        first = sorted(found)[0]
        return first, found[first]
    return "", ""


def _affected_entries(
    vuln: dict[str, Any],
    default_ecosystem: str = "",
) -> list[dict[str, Any]]:
    """Summarize every package and version range an advisory applies to.

    The ``fixed`` versions are collected per range so a caller can tell whether
    a pinned version is patched.  The (potentially huge) list of individually
    enumerated vulnerable versions is only counted, never copied.
    """
    affected = vuln.get("affected")
    if not isinstance(affected, list):
        return []
    entries: list[dict[str, Any]] = []
    for raw in affected:
        entry = _mapping(raw)
        package = _mapping(entry.get("package"))
        name = _clean_text(package.get("name"))
        ecosystem = _clean_text(package.get("ecosystem")) or default_ecosystem
        if not name and not ecosystem:
            continue
        fixed: list[str] = []
        range_types: list[str] = []
        ranges = entry.get("ranges")
        if isinstance(ranges, list):
            for raw_range in ranges:
                range_map = _mapping(raw_range)
                range_type = _clean_text(range_map.get("type"))
                if range_type and range_type not in range_types:
                    range_types.append(range_type)
                events = range_map.get("events")
                if not isinstance(events, list):
                    continue
                for event in events:
                    version = _clean_text(_mapping(event).get("fixed"))
                    if version and version not in fixed:
                        fixed.append(version)
        versions = entry.get("versions")
        entries.append(
            {
                "ecosystem": ecosystem or None,
                "name": name or None,
                "purl": _clean_text(package.get("purl")) or None,
                "fixed_versions": fixed,
                "range_types": range_types,
                "vulnerable_versions_listed": (
                    len(versions) if isinstance(versions, list) else 0
                ),
            },
        )
    return entries


def _affected_labels(entries: list[dict[str, Any]], max_items: int = 3) -> list[str]:
    """Return short ``ecosystem:package (fixed in X)`` labels for a snippet."""
    labels: list[str] = []
    for entry in entries[:max_items]:
        ecosystem = entry.get("ecosystem") or ""
        name = entry.get("name") or ""
        label = f"{ecosystem}:{name}".strip(":") or "unlisted package"
        fixed = entry.get("fixed_versions") or []
        if fixed:
            label = f"{label} (fixed in {fixed[0]})"
        labels.append(label)
    return labels


def _vulns_of(bucket: object) -> list[dict[str, Any]]:
    """Return the vulnerability entries of one querybatch result bucket."""
    if not isinstance(bucket, dict):
        return []
    vulns = bucket.get("vulns")
    if not isinstance(vulns, list):
        return []
    return [entry for entry in vulns if isinstance(entry, dict)]


class OsvProvider(BaseProvider):
    """Search OSV.dev advisories for open source packages.

    Keyless.  Each result is one advisory and carries its summary and severity,
    CVSS vector, CWE identifiers, CVE/GHSA aliases, the affected packages with
    their vulnerable version ranges and first fixed version, publication dates
    and a link to the advisory page.
    """

    name = "osv"
    description = (
        "Search OSV.dev for known vulnerabilities in open source packages "
        "(npm, PyPI, Go, Maven, crates.io, NuGet, RubyGems, Packagist, Hex, "
        "Pub, Debian, Alpine, OSS-Fuzz, GitHub Actions): advisory id, summary, "
        "severity and CVSS vector, CWEs, aliases such as the CVE, affected "
        "packages with vulnerable ranges and first fixed version, publication "
        "dates and links. Accepts an advisory id ('GHSA-jf85-cpcp-j695', "
        "'CVE-2021-44228'), a package with an ecosystem "
        "('pypi:requests@2.19.0', 'npm lodash', "
        "'maven:org.apache.logging.log4j:log4j-core') or a bare package name "
        "('lodash@4.17.11') searched across the default ecosystems. No API key "
        "required."
    )
    tags: ClassVar[list[str]] = ["security", "vulnerabilities", "code", "packages"]

    def _build_result(
        self,
        vuln: dict[str, Any],
        default_ecosystem: str = "",
    ) -> SearchResult | None:
        """Build the :class:`SearchResult` for one advisory, or ``None``."""
        vuln_id = _clean_text(vuln.get("id"))
        if not vuln_id:
            return None
        summary = _clean_text(vuln.get("summary"))
        details = _clean_text(vuln.get("details"))
        aliases = _str_list(vuln.get("aliases"))
        affected = _affected_entries(vuln, default_ecosystem)
        severity = _severity_label(vuln)
        cvss_type, cvss_vector = _cvss(vuln)
        published = _clean_text(vuln.get("published"))
        modified = _clean_text(vuln.get("modified"))
        database_specific = _mapping(vuln.get("database_specific"))
        cwe_ids = _str_list(database_specific.get("cwe_ids"))
        references = [
            url
            for url in (
                _clean_text(_mapping(reference).get("url"))
                for reference in vuln.get("references") or []
            )
            if url
        ]
        ecosystems: list[str] = []
        fixed_versions: list[str] = []
        for entry in affected:
            ecosystem = entry.get("ecosystem") or ""
            if ecosystem and ecosystem not in ecosystems:
                ecosystems.append(ecosystem)
            for version in entry.get("fixed_versions") or []:
                if version not in fixed_versions:
                    fixed_versions.append(version)

        snippet_parts: list[str] = []
        if severity:
            snippet_parts.append(f"Severity: {severity}")
        if cvss_type and cvss_vector:
            snippet_parts.append(f"{cvss_type.replace('_', ' ')}: {cvss_vector}")
        description = details or summary
        if description:
            snippet_parts.append(_excerpt(description, 200))
        if affected:
            snippet_parts.append(f"Affects {', '.join(_affected_labels(affected))}")
        if aliases:
            snippet_parts.append(f"Aliases: {', '.join(aliases[:5])}")
        if published:
            snippet_parts.append(f"Published {published[:10]}")
        snippet = " | ".join(snippet_parts)[:MAX_SNIPPET_LENGTH]
        if not snippet:
            snippet = "OSV.dev advisory for this package."

        return SearchResult(
            title=f"{summary} ({vuln_id})" if summary else vuln_id,
            url=_DETAIL_URL.format(vuln_id=vuln_id),
            snippet=snippet,
            source="osv.dev",
            provider=self.name,
            published_date=self._iso_date_prefix(published),
            extra={
                "id": vuln_id,
                "aliases": aliases,
                "summary": summary or None,
                "severity": severity or None,
                "cvss_type": cvss_type or None,
                "cvss_vector": cvss_vector or None,
                "cwe_ids": cwe_ids,
                "ecosystems": ecosystems,
                "affected": affected,
                "fixed_versions": fixed_versions,
                "published": published or None,
                "modified": modified or None,
                "withdrawn": _clean_text(vuln.get("withdrawn")) or None,
                "reference_count": len(references),
                "references": references[:10],
            },
        )

    def _finalize(
        self,
        results: list[SearchResult],
        limit: int,
    ) -> ProviderResult:
        """Sort newest-first, rank, and trim a result list."""
        results.sort(key=lambda result: result.published_date or "", reverse=True)
        trimmed = results[:limit]
        for rank, result in enumerate(trimmed, start=1):
            result.rank = rank
        return ProviderResult(results=trimmed)

    def _parse_vulns(
        self,
        payload: object,
        default_ecosystem: str,
        limit: int,
    ) -> ProviderResult:
        """Parse a ``/v1/query`` response or a single ``/v1/vulns`` advisory."""
        if not isinstance(payload, dict):
            return ProviderResult(results=[])
        raw = payload.get("vulns")
        if not isinstance(raw, list):
            # ``GET /v1/vulns/<id>`` returns the advisory itself, and a query
            # without matches answers ``{}``.
            raw = [payload] if _clean_text(payload.get("id")) else []
        results: list[SearchResult] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            result = self._build_result(item, default_ecosystem)
            if result is not None:
                results.append(result)
        return self._finalize(results, limit)

    async def _fetch_by_id(
        self,
        client: Any,
        vuln_id: str,
    ) -> ProviderResult:
        """Fetch one advisory by id."""
        resp = await client.get(_VULN_URL.format(vuln_id=vuln_id))
        if resp.status_code == 404:
            # An unknown advisory id is an empty answer, not a failure.
            return ProviderResult(results=[])
        resp.raise_for_status()
        return self._parse_vulns(resp.json(), "", 1)

    async def _search_name(
        self,
        client: Any,
        plan: QueryPlan,
        limit: int,
    ) -> ProviderResult:
        """Search an ecosystem-less package name across the default ecosystems.

        OSV only answers package queries, so a bare name is broadcast with
        ``/v1/querybatch``; that endpoint reports matching advisory ids only,
        so the details of the top matches (at most
        :data:`_MAX_DETAIL_FETCHES`) are fetched afterwards.
        """
        queries: list[dict[str, Any]] = []
        for ecosystem in _DEFAULT_ECOSYSTEMS:
            query: dict[str, Any] = {
                "package": {"name": plan.value, "ecosystem": ecosystem},
            }
            if plan.version:
                query["version"] = plan.version
            queries.append(query)

        resp = await client.post(_QUERYBATCH_URL, json={"queries": queries})
        resp.raise_for_status()
        payload = resp.json()
        buckets = payload.get("results") if isinstance(payload, dict) else None
        if not isinstance(buckets, list):
            return ProviderResult(results=[])

        # The reply is positional: bucket *i* answers _DEFAULT_ECOSYSTEMS[i].
        discovered: dict[str, str] = {}
        for index, bucket in enumerate(buckets):
            if index >= len(_DEFAULT_ECOSYSTEMS):
                break
            for entry in _vulns_of(bucket):
                vuln_id = _clean_text(entry.get("id"))
                if vuln_id and vuln_id not in discovered:
                    discovered[vuln_id] = _DEFAULT_ECOSYSTEMS[index]

        wanted = list(discovered)[: min(limit, _MAX_DETAIL_FETCHES)]
        if not wanted:
            return ProviderResult(results=[])
        fetched = await asyncio.gather(
            *(self._fetch_vuln(client, vuln_id) for vuln_id in wanted),
            return_exceptions=True,
        )

        results: list[SearchResult] = []
        # ``wanted`` and ``fetched`` line up by construction; stay lenient anyway
        # so an unexpected length mismatch degrades instead of raising.
        for vuln_id, item in zip(wanted, fetched, strict=False):
            if not isinstance(item, dict):
                continue
            result = self._build_result(item, discovered[vuln_id])
            if result is not None:
                results.append(result)
        return self._finalize(results, limit)

    async def _fetch_vuln(self, client: Any, vuln_id: str) -> object:
        """Fetch one advisory's details, used for ecosystem-less name queries."""
        resp = await client.get(_VULN_URL.format(vuln_id=vuln_id))
        resp.raise_for_status()
        return resp.json()

    async def search(self, query: str, params: SearchParams) -> ProviderResult:
        """Search OSV.dev for *query*.

        An empty or unparseable query returns an empty result set instead of a
        request.
        """
        plan = build_query(query)
        if plan is None:
            return ProviderResult(results=[])

        limit = min(params.num_results, self._max_results, _MAX_API_RESULTS)
        async with self._client() as client:
            if plan.kind == "id":
                return await self._fetch_by_id(client, plan.value)
            if plan.kind == "name":
                return await self._search_name(client, plan, limit)
            body: dict[str, Any] = {
                "package": {"name": plan.value, "ecosystem": plan.ecosystem},
            }
            if plan.version:
                body["version"] = plan.version
            resp = await client.post(_QUERY_URL, json=body)
            resp.raise_for_status()
            return self._parse_vulns(resp.json(), plan.ecosystem, limit)
