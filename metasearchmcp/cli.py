"""First-run setup wizard for MetaSearchMCP.

Run with: metasearchmcp-setup
"""

from __future__ import annotations

import json
import sys

import httpx

from metasearchmcp.config import USER_CONFIG_DIR, USER_CONFIG_FILE

_SERPBASE_VALIDATE_URL = "https://api.serpbase.dev/google/search"
_DASHBOARD_URL = "https://serpbase.dev/dashboard/api-keys"

# status codes that confirm the key itself is valid (credits may be low)
_VALID_STATUSES = {0, 2, 3}  # ok, insufficient_credits, rate_limited


# ─── Config file helpers ──────────────────────────────────────────────────────


def load_config() -> dict[str, str]:
    """Load key=value pairs from the user config file."""
    env: dict[str, str] = {}
    if not USER_CONFIG_FILE.exists():
        return env
    for raw_line in USER_CONFIG_FILE.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip()
    return env


def save_config(env: dict[str, str]) -> None:
    """Persist key=value pairs to the user config file with restricted permissions."""
    USER_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    lines = [f"{k}={v}" for k, v in env.items()]
    USER_CONFIG_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    USER_CONFIG_FILE.chmod(0o600)


# ─── Validation ───────────────────────────────────────────────────────────────


def validate_serpbase_key(api_key: str) -> bool:
    """Check whether a SerpBase API key is valid by calling the validation endpoint."""
    try:
        resp = httpx.post(
            _SERPBASE_VALIDATE_URL,
            json={"q": "test"},
            headers={"X-API-Key": api_key},
            timeout=10.0,
        )
        data = resp.json()
        return data.get("status") in _VALID_STATUSES
    except Exception:
        return False


# ─── Config snippet output ────────────────────────────────────────────────────


def _mcp_server_block() -> dict:
    return {
        "command": "uvx",
        "args": ["MetaSearchMCP"],
    }


def print_tool_configs() -> None:
    """Print MCP configuration snippets for popular AI tools."""
    block = json.dumps({"MetaSearchMCP": _mcp_server_block()}, indent=2)

    print()
    print("=" * 60)
    print("MCP Configuration for AI Tools")
    print("=" * 60)

    print("""
┌─ Claude Desktop ─────────────────────────────────────────────┐
│ File: ~/Library/Application Support/Claude/claude_desktop_config.json (macOS)
│       %APPDATA%\\Claude\\claude_desktop_config.json           (Windows)
└──────────────────────────────────────────────────────────────┘""")
    print(f'{{"mcpServers": {block}}}')

    print("""
┌─ Cursor ──────────────────────────────────────────────────────┐
│ File: ~/.cursor/mcp.json  or  <project>/.cursor/mcp.json      │
└───────────────────────────────────────────────────────────────┘""")
    print(f'{{"mcpServers": {block}}}')

    print("""
┌─ Windsurf ────────────────────────────────────────────────────┐
│ File: ~/.codeium/windsurf/mcp_config.json                     │
└───────────────────────────────────────────────────────────────┘""")
    print(f'{{"mcpServers": {block}}}')

    print("""
┌─ Claude Code (CLI) ────────────────────────────────────────────┐
│ Run: claude mcp add MetaSearchMCP uvx MetaSearchMCP            │
└────────────────────────────────────────────────────────────────┘""")

    print("""
┌─ Continue.dev ─────────────────────────────────────────────────┐
│ File: ~/.continue/config.json — add under "mcpServers"         │
└────────────────────────────────────────────────────────────────┘""")
    print(f'{{"mcpServers": [{json.dumps(_mcp_server_block(), indent=2)}]}}')

    print()
    print(f"Config file: {USER_CONFIG_FILE}")
    print("Done! Restart your AI tool to load the new MCP server.")


# ─── Setup wizard ─────────────────────────────────────────────────────────────


def setup() -> None:
    """Run the interactive setup wizard to configure MetaSearchMCP."""
    print("MetaSearchMCP Setup Wizard")
    print("=" * 60)

    env = load_config()
    is_first_run = not USER_CONFIG_FILE.exists()

    if is_first_run:
        print("\nFirst run detected. Let's configure your SerpBase API key.\n")
    else:
        current_key = env.get("SERPBASE_API_KEY", "")
        if current_key:
            masked = current_key[:8] + "..." + current_key[-4:]
            print(f"\nExisting SERPBASE_API_KEY: {masked}")
            answer = input("Reconfigure? [y/N] ").strip().lower()
            if answer != "y":
                print_tool_configs()
                return
        print()

    print(f"Get your API key at: {_DASHBOARD_URL}\n")

    api_key = input("Enter your SerpBase API key: ").strip()
    if not api_key:
        print("Error: API key cannot be empty.", file=sys.stderr)
        sys.exit(1)

    print("Validating key...", end=" ", flush=True)
    if validate_serpbase_key(api_key):
        print("✓ Valid")
    else:
        print("⚠ Could not validate (check your key or network connection)")
        answer = input("Save anyway? [y/N] ").strip().lower()
        if answer != "y":
            print("Aborted.")
            sys.exit(1)

    env["SERPBASE_API_KEY"] = api_key
    save_config(env)

    print_tool_configs()
