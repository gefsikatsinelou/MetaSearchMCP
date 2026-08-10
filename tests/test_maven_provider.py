"""Unit tests for the Maven Central (Java/JVM) search provider."""

from __future__ import annotations

import pytest

from metasearchmcp.providers.maven import MavenProvider

_SAMPLE_RESPONSE = {
    "responseHeader": {"status": 0},
    "response": {
        "numFound": 2,
        "start": 0,
        "docs": [
            {
                "id": "com.fasterxml.jackson.core:jackson-databind",
                "g": "com.fasterxml.jackson.core",
                "a": "jackson-databind",
                "latestVersion": "2.17.1",
                "repositoryId": "central",
                "p": "jar",
                "timestamp": 1718130184000,
                "versionCount": 300,
            },
            {
                "id": "bad:entry",
                "g": "",
                "a": "",
                "latestVersion": "1.0",
            },
        ],
    },
}

_EMPTY_RESPONSE = {"responseHeader": {"status": 0}, "response": {"docs": []}}


def test_maven_parse_basic():
    p = MavenProvider()
    result = p._parse(_SAMPLE_RESPONSE)

    assert len(result.results) == 1
    r = result.results[0]
    assert r.title == "com.fasterxml.jackson.core:jackson-databind"
    assert r.url == (
        "https://central.sonatype.com/artifact/"
        "com.fasterxml.jackson.core/jackson-databind"
    )
    assert "v2.17.1" in r.snippet
    assert "Packaging: jar" in r.snippet
    assert "Versions: 300" in r.snippet
    assert r.source == "Maven Central"
    assert r.provider == "maven"
    assert r.rank == 1
    assert r.published_date == "2024-06-11"
    assert r.extra["group"] == "com.fasterxml.jackson.core"
    assert r.extra["artifact"] == "jackson-databind"
    assert r.extra["latest_version"] == "2.17.1"
    assert r.extra["packaging"] == "jar"
    assert r.extra["version_count"] == 300


def test_maven_parse_skips_doc_without_coordinates():
    p = MavenProvider()
    result = p._parse(_SAMPLE_RESPONSE)
    # Second doc has empty group/artifact -> skipped.
    assert len(result.results) == 1
    assert all(r.url for r in result.results)


def test_maven_parse_empty():
    p = MavenProvider()
    result = p._parse(_EMPTY_RESPONSE)
    assert result.results == []


def test_maven_parse_missing_keys():
    p = MavenProvider()
    result = p._parse(
        {
            "response": {
                "docs": [
                    {
                        "g": "org.example",
                        "a": "demo",
                        # no latestVersion / p / versionCount / timestamp
                    },
                ],
            },
        },
    )
    r = result.results[0]
    assert r.snippet == ""
    assert r.published_date is None
    assert r.extra["latest_version"] == ""
    assert r.extra["packaging"] == ""
    assert r.extra["version_count"] == 0


def test_maven_timestamp_to_date():
    assert MavenProvider._timestamp_to_date(1718130184000) == "2024-06-11"
    assert MavenProvider._timestamp_to_date(None) is None
    assert MavenProvider._timestamp_to_date("") is None
    assert MavenProvider._timestamp_to_date("not-a-number") is None
    assert MavenProvider._timestamp_to_date(0) is None


def test_maven_artifact_url():
    assert MavenProvider._artifact_url("org.example", "demo") == (
        "https://central.sonatype.com/artifact/org.example/demo"
    )


def test_maven_is_available():
    """Keyless provider is always available."""
    assert MavenProvider().is_available() is True


@pytest.mark.asyncio
async def test_maven_search_builds_query(respx_mock):
    """The search method hits the Solr endpoint and parses the response."""
    import respx

    respx_mock.get("https://search.maven.org/solrsearch/select").mock(
        return_value=respx.MockResponse(200, json=_SAMPLE_RESPONSE),
    )

    from metasearchmcp.contracts import SearchParams

    p = MavenProvider()
    result = await p.search("jackson", SearchParams(num_results=5))

    assert len(result.results) == 1
    assert result.results[0].provider == "maven"
    request = respx_mock.calls.last.request
    assert request.url.params["q"] == "jackson"
    assert request.url.params["wt"] == "json"
