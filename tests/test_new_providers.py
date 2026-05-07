"""Parse/unit tests for the five new providers: mwmbl, gitlab, metacpan,
pkg_go_dev, lib_rs.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Mwmbl
# ---------------------------------------------------------------------------


def _mwmbl_response() -> list:
    return [
        {
            "url": "https://example.com/page",
            "title": [{"value": "Example "}, {"value": "Page"}],
            "extract": [{"value": "A description of the example page."}],
        },
        {
            "url": "https://another.org/article",
            "title": [{"value": "Another Article"}],
            "extract": [{"value": "Some more content here."}],
        },
    ]


def test_mwmbl_parse_basic():
    from metasearchmcp.providers.mwmbl import MwmblProvider

    p = MwmblProvider()
    result = p._parse(_mwmbl_response())

    assert len(result.results) == 2
    r = result.results[0]
    assert r.title == "Example Page"
    assert r.url == "https://example.com/page"
    assert r.snippet == "A description of the example page."
    assert r.provider == "mwmbl"
    assert r.rank == 1


def test_mwmbl_parse_empty():
    from metasearchmcp.providers.mwmbl import MwmblProvider

    p = MwmblProvider()
    result = p._parse([])
    assert result.results == []


def test_mwmbl_parse_title_concatenation():
    from metasearchmcp.providers.mwmbl import MwmblProvider

    p = MwmblProvider()
    data = [
        {
            "url": "https://x.com",
            "title": [{"value": "Hello"}, {"value": " World"}],
            "extract": [],
        },
    ]
    result = p._parse(data)
    assert result.results[0].title == "Hello World"


def test_mwmbl_parse_no_extract():
    from metasearchmcp.providers.mwmbl import MwmblProvider

    p = MwmblProvider()
    data = [{"url": "https://x.com", "title": [{"value": "No extract"}], "extract": []}]
    result = p._parse(data)
    assert result.results[0].snippet == ""


# ---------------------------------------------------------------------------
# GitLab
# ---------------------------------------------------------------------------


def _gitlab_response() -> list:
    return [
        {
            "id": 1,
            "name": "my-project",
            "name_with_namespace": "mygroup / my-project",
            "web_url": "https://gitlab.com/mygroup/my-project",
            "description": "A cool open source project.",
            "namespace": {"full_path": "mygroup"},
            "star_count": 42,
            "forks_count": 7,
            "last_activity_at": "2025-06-15T10:00:00.000Z",
            "topics": ["python", "api"],
            "http_url_to_repo": "https://gitlab.com/mygroup/my-project.git",
        },
        {
            "id": 2,
            "name": "another-repo",
            "name_with_namespace": "org / another-repo",
            "web_url": "https://gitlab.com/org/another-repo",
            "description": None,
            "namespace": {"full_path": "org"},
            "star_count": 0,
            "forks_count": 0,
            "last_activity_at": None,
            "topics": [],
            "http_url_to_repo": "https://gitlab.com/org/another-repo.git",
        },
    ]


def test_gitlab_parse_basic():
    from metasearchmcp.providers.gitlab import GitLabProvider

    p = GitLabProvider()
    result = p._parse(_gitlab_response())

    assert len(result.results) == 2
    r = result.results[0]
    assert r.title == "mygroup / my-project"
    assert r.url == "https://gitlab.com/mygroup/my-project"
    assert "cool open source" in r.snippet
    assert r.provider == "gitlab"
    assert r.published_date == "2025-06-15"
    assert r.extra["stars"] == 42
    assert r.extra["topics"] == ["python", "api"]


def test_gitlab_parse_no_description():
    from metasearchmcp.providers.gitlab import GitLabProvider

    p = GitLabProvider()
    result = p._parse(_gitlab_response())
    r = result.results[1]
    # description is None, snippet should still be a string
    assert isinstance(r.snippet, str)


def test_gitlab_parse_no_last_activity():
    from metasearchmcp.providers.gitlab import GitLabProvider

    p = GitLabProvider()
    result = p._parse(_gitlab_response())
    r = result.results[1]
    assert r.published_date is None


def test_gitlab_parse_empty():
    from metasearchmcp.providers.gitlab import GitLabProvider

    p = GitLabProvider()
    result = p._parse([])
    assert result.results == []


# ---------------------------------------------------------------------------
# MetaCPAN
# ---------------------------------------------------------------------------


def _metacpan_response() -> dict:
    return {
        "hits": {
            "hits": [
                {
                    "_source": {
                        "documentation": "Moose",
                        "abstract": "A postmodern object system for Perl 5",
                    },
                },
                {
                    "_source": {
                        "documentation": "LWP::UserAgent",
                        "abstract": "Web user agent class",
                    },
                },
                {
                    "_source": {
                        "documentation": "DBI",
                        # abstract missing
                    },
                },
            ],
        },
    }


def test_metacpan_parse_basic():
    from metasearchmcp.providers.metacpan import MetaCPANProvider

    p = MetaCPANProvider()
    result = p._parse(_metacpan_response())

    assert len(result.results) == 3
    r = result.results[0]
    assert r.title == "Moose"
    assert r.url == "https://metacpan.org/pod/Moose"
    assert r.snippet == "A postmodern object system for Perl 5"
    assert r.provider == "metacpan"
    assert r.source == "metacpan.org"


def test_metacpan_parse_missing_abstract():
    from metasearchmcp.providers.metacpan import MetaCPANProvider

    p = MetaCPANProvider()
    result = p._parse(_metacpan_response())
    r = result.results[2]
    assert r.title == "DBI"
    assert r.snippet == ""


def test_metacpan_parse_empty():
    from metasearchmcp.providers.metacpan import MetaCPANProvider

    p = MetaCPANProvider()
    result = p._parse({"hits": {"hits": []}})
    assert result.results == []


# ---------------------------------------------------------------------------
# pkg.go.dev
# ---------------------------------------------------------------------------


def _pkg_go_dev_html() -> str:
    return """<!DOCTYPE html>
<html>
<body>
<main>
  <div class="SearchResults">
    <div>
      <div class="SearchSnippet">
        <div class="SearchSnippet-headerContainer">
          <h2><a href="/github.com/gin-gonic/gin"><span>gin-gonic/</span>gin</a></h2>
        </div>
        <div class="SearchSnippet-infoLabel">
          <span><strong>v1.10.0</strong></span>
        </div>
        <p class="SearchSnippet-synopsis">Gin is a HTTP web framework written in Go.</p>
      </div>
      <div class="SearchSnippet">
        <div class="SearchSnippet-headerContainer">
          <h2><a href="/golang.org/x/net"><span>x/</span>net</a></h2>
        </div>
        <div class="SearchSnippet-infoLabel">
          <span><strong>v0.24.0</strong></span>
        </div>
        <p class="SearchSnippet-synopsis">Go supplementary network libraries.</p>
      </div>
    </div>
  </div>
</main>
</body>
</html>"""


def test_pkg_go_dev_parse_basic():
    from metasearchmcp.providers.pkg_go_dev import PkgGoDevProvider

    p = PkgGoDevProvider()
    result = p._parse(_pkg_go_dev_html())

    assert len(result.results) == 2
    r = result.results[0]
    assert "gin" in r.title.lower()
    assert r.url == "https://pkg.go.dev/github.com/gin-gonic/gin"
    assert "HTTP web framework" in r.snippet
    assert r.provider == "pkg_go_dev"
    assert r.source == "pkg.go.dev"


def test_pkg_go_dev_parse_empty():
    from metasearchmcp.providers.pkg_go_dev import PkgGoDevProvider

    p = PkgGoDevProvider()
    result = p._parse("<html><body><main></main></body></html>")
    assert result.results == []


# ---------------------------------------------------------------------------
# lib.rs
# ---------------------------------------------------------------------------


def _lib_rs_html() -> str:
    return """<!DOCTYPE html>
<html>
<body>
<main>
  <div>
    <ol>
      <li>
        <a href="/crates/serde">
          <div class="h">
            <h4>serde</h4>
            <p>A generic serialization/deserialization framework.</p>
          </div>
          <div class="meta">
            <span class="version">1.0.197</span>
          </div>
        </a>
      </li>
      <li>
        <a href="/crates/serde_json">
          <div class="h">
            <h4>serde_json</h4>
            <p>A JSON serialization file format.</p>
          </div>
          <div class="meta">
            <span class="version">1.0.114</span>
          </div>
        </a>
      </li>
    </ol>
  </div>
</main>
</body>
</html>"""


def test_lib_rs_parse_basic():
    from metasearchmcp.providers.lib_rs import LibRsProvider

    p = LibRsProvider()
    result = p._parse(_lib_rs_html())

    assert len(result.results) == 2
    r = result.results[0]
    assert r.title == "serde"
    assert r.url == "https://lib.rs/crates/serde"
    assert "serialization" in r.snippet
    assert r.provider == "lib_rs"
    assert r.source == "lib.rs"
    assert r.extra["version"] == "1.0.197"


def test_lib_rs_parse_rank():
    from metasearchmcp.providers.lib_rs import LibRsProvider

    p = LibRsProvider()
    result = p._parse(_lib_rs_html())
    assert result.results[0].rank == 1
    assert result.results[1].rank == 2


def test_lib_rs_parse_empty():
    from metasearchmcp.providers.lib_rs import LibRsProvider

    p = LibRsProvider()
    result = p._parse("<html><body><main><div><ol></ol></div></main></body></html>")
    assert result.results == []


def test_provider_user_agents_include_project_contact_url():
    from metasearchmcp.providers.base import (
        API_USER_AGENT,
        BOT_USER_AGENT,
        PROJECT_URL,
    )

    assert PROJECT_URL == "https://github.com/gefsikatsinelou/MetaSearchMCP"
    assert PROJECT_URL in API_USER_AGENT
    assert PROJECT_URL in BOT_USER_AGENT
    assert "your-org" not in API_USER_AGENT
    assert "your-org" not in BOT_USER_AGENT
