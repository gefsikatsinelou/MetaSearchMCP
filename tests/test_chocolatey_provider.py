"""Unit tests for the Chocolatey community package provider."""

# Long XML fixture lines are intentional; keep them readable as-is.
# ruff: noqa: E501

from __future__ import annotations

import pytest
import respx
from httpx import HTTPStatusError

from metasearchmcp.contracts import SearchParams
from metasearchmcp.providers.chocolatey import ChocolateyProvider

_SEARCH_URL = "https://community.chocolatey.org/api/v2/Search()"

_SAMPLE_XML = """<?xml version="1.0" encoding="utf-8" standalone="yes"?>
<feed xml:base="https://community.chocolatey.org/api/v2/" xmlns:d="http://schemas.microsoft.com/ado/2007/08/dataservices" xmlns:m="http://schemas.microsoft.com/ado/2007/08/dataservices/metadata" xmlns="http://www.w3.org/2005/Atom">
  <title type="text">Search</title>
  <entry>
    <id>https://community.chocolatey.org/api/v2/Packages(Id='git',Version='2.55.0.5')</id>
    <title type="text">git</title>
    <summary type="text">Git for Windows offers a native set of tools that bring the full feature set of the Git SCM to Windows</summary>
    <updated>2026-08-20T22:15:31Z</updated>
    <author>
      <name>The Git Development Community</name>
    </author>
    <m:properties>
      <d:Version>2.55.0.5</d:Version>
      <d:Title>Git</d:Title>
      <d:Description>Git for Windows focuses on offering a lightweight, native set of tools.</d:Description>
      <d:Tags>git vcs dvcs version-control cli</d:Tags>
      <d:Dependencies>git.install:[2.55.0.5]:</d:Dependencies>
      <d:DownloadCount m:type="Edm.Int32">19998640</d:DownloadCount>
      <d:VersionDownloadCount m:type="Edm.Int32">63</d:VersionDownloadCount>
      <d:GalleryDetailsUrl>https://community.chocolatey.org/packages/git/2.55.0.5</d:GalleryDetailsUrl>
      <d:IsLatestVersion m:type="Edm.Boolean">true</d:IsLatestVersion>
      <d:IsPrerelease m:type="Edm.Boolean">false</d:IsPrerelease>
      <d:Published m:type="Edm.DateTime">2026-08-20T18:14:18.953</d:Published>
      <d:LicenseUrl>http://www.gnu.org/licenses/old-licenses/gpl-2.0.html</d:LicenseUrl>
      <d:ProjectUrl>https://git-for-windows.github.io/</d:ProjectUrl>
      <d:PackageStatus>Approved</d:PackageStatus>
    </m:properties>
  </entry>
  <entry>
    <title type="text">7zip</title>
    <summary type="text">7-Zip is a file archiver with a high compression ratio.</summary>
    <author>
      <name>Igor Pavlov</name>
    </author>
    <m:properties>
      <d:Version>24.09</d:Version>
      <d:Title>7zip (Portable)</d:Title>
      <d:Tags>7zip zip compression cli</d:Tags>
      <d:DownloadCount m:type="Edm.Int32">0</d:DownloadCount>
      <d:IsLatestVersion m:type="Edm.Boolean">true</d:IsLatestVersion>
      <d:IsPrerelease m:type="Edm.Boolean">true</d:IsPrerelease>
      <d:PackageStatus>Rejected</d:PackageStatus>
    </m:properties>
  </entry>
  <entry>
    <summary type="text">Entry with no id at all.</summary>
    <m:properties>
      <d:Version>1.0.0</d:Version>
    </m:properties>
  </entry>
  <entry>not a package</entry>
</feed>
"""

_EMPTY_XML = """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"><title>Search</title></feed>
"""


def test_name_tags_and_availability() -> None:
    p = ChocolateyProvider()
    assert p.name == "chocolatey"
    assert p.tags == ["web", "code", "developer", "packages"]
    assert p.is_available() is True


def test_provider_is_registered() -> None:
    from metasearchmcp.providers.registry import build_registry

    registry = build_registry()
    assert "chocolatey" in registry
    assert registry["chocolatey"].tags == ["web", "code", "developer", "packages"]


def test_parse_builds_full_result() -> None:
    result = ChocolateyProvider()._parse(_SAMPLE_XML, limit=10)

    assert [r.title for r in result.results] == ["Git", "7zip (Portable)"]
    first = result.results[0]
    assert first.url == "https://community.chocolatey.org/packages/git/2.55.0.5"
    assert first.source == "chocolatey.org"
    assert first.provider == "chocolatey"
    assert first.rank == 1
    assert first.published_date == "2026-08-20"
    assert first.snippet.startswith("Git for Windows offers a native set of tools")
    assert "v2.55.0.5" in first.snippet
    assert "Downloads: 19,998,640" in first.snippet
    assert first.extra["package_id"] == "git"
    assert first.extra["version"] == "2.55.0.5"
    assert first.extra["authors"] == "The Git Development Community"
    assert first.extra["tags"] == ["git", "vcs", "dvcs", "version-control", "cli"]
    assert first.extra["total_downloads"] == 19998640
    assert first.extra["version_downloads"] == 63
    assert first.extra["is_prerelease"] is False
    assert first.extra["is_latest_version"] is True
    assert first.extra["package_status"] == "Approved"
    assert first.extra["project_url"] == "https://git-for-windows.github.io/"
    assert first.extra["license_url"].endswith("gpl-2.0.html")
    assert first.extra["dependencies"] == ["git.install:[2.55.0.5]:"]


def test_parse_falls_back_to_package_page_url() -> None:
    result = ChocolateyProvider()._parse(_SAMPLE_XML, limit=10)

    second = result.results[1]
    assert second.title == "7zip (Portable)"
    assert second.url == "https://community.chocolatey.org/packages/7zip"
    assert second.rank == 2
    assert second.published_date is None
    assert "Downloads" not in second.snippet
    assert second.extra["version"] == "24.09"
    assert second.extra["total_downloads"] == 0
    assert second.extra["is_prerelease"] is True
    assert second.extra["package_status"] == "Rejected"
    assert second.extra["project_url"] is None
    assert second.extra["dependencies"] == []


def test_parse_skips_entries_without_id() -> None:
    result = ChocolateyProvider()._parse(_SAMPLE_XML, limit=10)

    # The id-less entry and the bare text node produce no results.
    assert len(result.results) == 2


def test_parse_respects_limit() -> None:
    result = ChocolateyProvider()._parse(_SAMPLE_XML, limit=1)

    assert len(result.results) == 1
    assert result.results[0].title == "Git"


def test_parse_empty_and_malformed_feeds() -> None:
    provider = ChocolateyProvider()
    assert provider._parse(_EMPTY_XML, limit=5).results == []
    assert provider._parse("<feed><entry>", limit=5).results == []
    assert provider._parse("not xml at all", limit=5).results == []


@pytest.mark.asyncio
async def test_search_parses_results(respx_mock) -> None:
    respx_mock.get(_SEARCH_URL).mock(
        return_value=respx.MockResponse(200, text=_SAMPLE_XML),
    )

    result = await ChocolateyProvider().search("git", SearchParams(num_results=5))

    assert [r.title for r in result.results] == ["Git", "7zip (Portable)"]
    assert result.results[0].provider == "chocolatey"


@pytest.mark.asyncio
async def test_search_sends_odata_query_params(respx_mock) -> None:
    route = respx_mock.get(_SEARCH_URL).mock(
        return_value=respx.MockResponse(200, text=_SAMPLE_XML),
    )

    await ChocolateyProvider().search("visual studio", SearchParams(num_results=5))

    params = route.calls.last.request.url.params
    assert params["$filter"] == "IsLatestVersion"
    assert params["searchTerm"] == "'visual studio'"
    assert params["targetFramework"] == "''"
    assert params["includePrerelease"] == "false"
    assert params["$top"] == "5"


@pytest.mark.asyncio
async def test_search_blank_query_skips_request(respx_mock) -> None:
    route = respx_mock.get(_SEARCH_URL).mock(
        return_value=respx.MockResponse(200, text=_SAMPLE_XML),
    )

    result = await ChocolateyProvider().search("   ", SearchParams(num_results=5))

    assert result.results == []
    assert not route.called


@pytest.mark.asyncio
async def test_search_raises_on_http_error(respx_mock) -> None:
    respx_mock.get(_SEARCH_URL).mock(return_value=respx.MockResponse(503))

    with pytest.raises(HTTPStatusError):
        await ChocolateyProvider().search("git", SearchParams(num_results=5))
