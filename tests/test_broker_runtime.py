"""Tests for broker tool runtime behaviour."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest


@pytest.mark.asyncio
async def test_list_tools_exposes_expected_tool_names():
    from metasearchmcp import broker

    tools = await broker.list_tools()
    names = {tool.name for tool in tools}

    assert {
        "search_web",
        "search_google",
        "search_academic",
        "search_github",
        "compare_engines",
        "search_finance",
        "search_code",
    } <= names


@pytest.mark.asyncio
async def test_call_tool_wraps_dispatch_errors_as_text_content():
    from metasearchmcp import broker

    with patch.object(broker, "dispatch_tool", side_effect=RuntimeError("boom")):
        response = await broker.call_tool("search_web", {"query": "test"})

    assert len(response) == 1
    payload = json.loads(response[0].text)
    assert payload == {"error": "boom", "tool": "search_web"}


@pytest.mark.asyncio
async def test_call_tool_serializes_success_payload():
    from metasearchmcp import broker

    with patch.object(broker, "dispatch_tool", return_value={"status": "ok"}):
        response = await broker.call_tool("search_web", {"query": "test"})

    assert len(response) == 1
    assert json.loads(response[0].text) == {"status": "ok"}


def test_run_warns_when_serpbase_missing(monkeypatch, capsys):
    from metasearchmcp import broker, config

    class FakeSettings:
        allow_unstable_providers = False
        serpbase_api_key = ""
        serper_api_key = ""

    called = {"ran": False}

    def fake_run(coro):
        called["ran"] = True
        coro.close()

    monkeypatch.setattr(config, "get_settings", lambda: FakeSettings())
    monkeypatch.setattr(broker.asyncio, "run", fake_run)

    broker.run()

    err = capsys.readouterr().err
    assert "No Google provider configured" in err
    assert called["ran"] is True


def test_run_skips_warning_when_serpbase_present(monkeypatch, capsys):
    from metasearchmcp import broker, config

    class FakeSettings:
        allow_unstable_providers = False
        serpbase_api_key = "configured"
        serper_api_key = ""

    def fake_run(coro):
        coro.close()

    monkeypatch.setattr(config, "get_settings", lambda: FakeSettings())
    monkeypatch.setattr(broker.asyncio, "run", fake_run)

    broker.run()

    err = capsys.readouterr().err
    assert "No Google provider configured" not in err


def test_run_skips_warning_when_direct_google_enabled(monkeypatch, capsys):
    from metasearchmcp import broker, config

    class FakeSettings:
        allow_unstable_providers = True
        serpbase_api_key = ""
        serper_api_key = ""

    def fake_run(coro):
        coro.close()

    monkeypatch.setattr(config, "get_settings", lambda: FakeSettings())
    monkeypatch.setattr(broker.asyncio, "run", fake_run)

    broker.run()

    err = capsys.readouterr().err
    assert "No Google provider configured" not in err
