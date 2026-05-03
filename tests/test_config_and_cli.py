from __future__ import annotations

import shutil
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

from metasearchmcp.config import Settings


@pytest.fixture
def config_sandbox(request):
    sandbox = (
        Path(__file__).resolve().parents[1]
        / ".test-artifacts"
        / f"{request.node.name}-{uuid.uuid4().hex}"
    )
    sandbox.mkdir(parents=True)
    yield sandbox
    shutil.rmtree(sandbox, ignore_errors=True)


def test_enabled_provider_list_normalizes_case_and_deduplicates():
    settings = Settings(
        enabled_providers=" GitHub, ,ARXIV , duckduckgo, github, DuckDuckGo ,, ",
    )

    assert settings.enabled_provider_list() == ["github", "arxiv", "duckduckgo"]


def test_enabled_provider_list_empty_string_means_auto():
    settings = Settings(enabled_providers="   ")

    assert settings.enabled_provider_list() == []


def test_load_config_returns_empty_when_file_missing(config_sandbox, monkeypatch):
    from metasearchmcp import cli

    monkeypatch.setattr(cli, "USER_CONFIG_FILE", config_sandbox / "missing.env")

    assert cli.load_config() == {}


def test_load_config_skips_comments_and_malformed_lines(config_sandbox, monkeypatch):
    from metasearchmcp import cli

    config_file = config_sandbox / "config.env"
    config_file.write_text(
        "# comment\nSERPBASE_API_KEY=test-key\nINVALID\nHOST=127.0.0.1\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(cli, "USER_CONFIG_FILE", config_file)

    assert cli.load_config() == {
        "SERPBASE_API_KEY": "test-key",
        "HOST": "127.0.0.1",
    }


def test_save_config_writes_file_and_trailing_newline(config_sandbox, monkeypatch):
    from metasearchmcp import cli

    config_dir = config_sandbox / ".metasearchmcp"
    config_file = config_dir / "config.env"
    monkeypatch.setattr(cli, "USER_CONFIG_DIR", config_dir)
    monkeypatch.setattr(cli, "USER_CONFIG_FILE", config_file)

    cli.save_config({"SERPBASE_API_KEY": "abc", "HOST": "0.0.0.0"})

    assert config_file.exists()
    content = config_file.read_text(encoding="utf-8")
    assert content.endswith("\n")
    assert "SERPBASE_API_KEY=abc" in content
    assert "HOST=0.0.0.0" in content


def test_validate_serpbase_key_accepts_known_success_statuses(monkeypatch):
    from metasearchmcp import cli

    class FakeResponse:
        def json(self) -> dict[str, int]:
            return {"status": 2}

    def fake_post(*args, **kwargs):
        return FakeResponse()

    monkeypatch.setattr(cli.httpx, "post", fake_post)

    assert cli.validate_serpbase_key("valid-key") is True


def test_validate_serpbase_key_rejects_errors_and_exceptions(monkeypatch):
    from metasearchmcp import cli

    class BadResponse:
        def json(self) -> dict[str, int]:
            return {"status": 9}

    monkeypatch.setattr(cli.httpx, "post", lambda *args, **kwargs: BadResponse())
    assert cli.validate_serpbase_key("bad-key") is False

    def boom(*args, **kwargs):
        raise RuntimeError("network")

    monkeypatch.setattr(cli.httpx, "post", boom)
    assert cli.validate_serpbase_key("bad-key") is False


def test_mcp_server_block_shape():
    from metasearchmcp import cli

    assert cli._mcp_server_block() == {
        "command": "uvx",
        "args": ["MetaSearchMCP"],
    }


def test_print_tool_configs_includes_common_integrations(capsys):
    from metasearchmcp import cli

    cli.print_tool_configs()

    output = capsys.readouterr().out
    assert "Claude Desktop" in output
    assert "Cursor" in output
    assert "Windsurf" in output
    assert "MetaSearchMCP" in output


def test_setup_reuses_existing_key_without_reconfigure(monkeypatch, capsys):
    from metasearchmcp import cli

    monkeypatch.setattr(
        cli, "load_config", lambda: {"SERPBASE_API_KEY": "abcdefgh1234"},
    )
    monkeypatch.setattr(
        cli,
        "USER_CONFIG_FILE",
        SimpleNamespace(exists=lambda: True, __str__=lambda self: "config.env"),
    )
    monkeypatch.setattr("builtins.input", lambda prompt="": "n")

    called = {"printed": False}

    def fake_print_tool_configs() -> None:
        called["printed"] = True

    monkeypatch.setattr(cli, "print_tool_configs", fake_print_tool_configs)

    cli.setup()

    output = capsys.readouterr().out
    assert "Existing SERPBASE_API_KEY" in output
    assert called["printed"] is True


def test_setup_saves_validated_key(monkeypatch):
    from metasearchmcp import cli

    answers = iter(["new-key"])
    saved: dict[str, str] = {}

    monkeypatch.setattr(
        cli,
        "USER_CONFIG_FILE",
        SimpleNamespace(exists=lambda: False, __str__=lambda self: "config.env"),
    )
    monkeypatch.setattr(cli, "load_config", lambda: {})
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    monkeypatch.setattr(cli, "validate_serpbase_key", lambda key: True)
    monkeypatch.setattr(cli, "save_config", lambda env: saved.update(env))
    monkeypatch.setattr(cli, "print_tool_configs", lambda: None)

    cli.setup()

    assert saved == {"SERPBASE_API_KEY": "new-key"}


def test_setup_aborts_when_key_empty(monkeypatch):
    from metasearchmcp import cli

    monkeypatch.setattr(
        cli,
        "USER_CONFIG_FILE",
        SimpleNamespace(exists=lambda: False, __str__=lambda self: "config.env"),
    )
    monkeypatch.setattr(cli, "load_config", lambda: {})
    monkeypatch.setattr("builtins.input", lambda prompt="": "")

    with pytest.raises(SystemExit) as exc_info:
        cli.setup()

    assert exc_info.value.code == 1


def test_setup_aborts_when_validation_fails_and_user_declines(monkeypatch):
    from metasearchmcp import cli

    answers = iter(["bad-key", "n"])

    monkeypatch.setattr(
        cli,
        "USER_CONFIG_FILE",
        SimpleNamespace(exists=lambda: False, __str__=lambda self: "config.env"),
    )
    monkeypatch.setattr(cli, "load_config", lambda: {})
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    monkeypatch.setattr(cli, "validate_serpbase_key", lambda key: False)

    with pytest.raises(SystemExit) as exc_info:
        cli.setup()

    assert exc_info.value.code == 1
