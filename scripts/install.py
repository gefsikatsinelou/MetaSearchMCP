#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def command_text(command: list[str]) -> str:
    return " ".join(command)


def run(command: list[str], cwd: Path = ROOT) -> None:
    print(f"+ {command_text(command)}", flush=True)
    subprocess.run(command, cwd=cwd, check=True)


def venv_python(venv_dir: Path) -> Path:
    if os.name == "nt":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def install_target(include_dev: bool) -> str:
    return ".[dev]" if include_dev else "."


def ensure_env_file(root: Path = ROOT, force: bool = False) -> bool:
    env_file = root / ".env"
    env_example = root / ".env.example"
    if env_file.exists() and not force:
        return False
    if not env_example.exists():
        raise FileNotFoundError(f"Missing template: {env_example}")
    shutil.copyfile(env_example, env_file)
    return True


def create_or_reuse_venv(venv_dir: Path) -> Path:
    python = venv_python(venv_dir)
    if not python.exists():
        run([sys.executable, "-m", "venv", str(venv_dir)])
    return python


def install_local(args: argparse.Namespace) -> None:
    copied_env = ensure_env_file(ROOT, force=args.force_env)
    if copied_env:
        print("Created .env from .env.example")
    else:
        print("Keeping existing .env")

    python = create_or_reuse_venv(ROOT / ".venv")
    run([str(python), "-m", "pip", "install", "--upgrade", "pip"])
    run([str(python), "-m", "pip", "install", "-e", install_target(args.dev or args.test)])

    if args.test:
        run([str(python), "-m", "pytest"])

    if args.run:
        run([str(python), "-m", "metasearchmcp.server"])
    else:
        print("")
        print("Installed MetaSearchMCP.")
        print(f"Start HTTP API: {python} -m metasearchmcp.server")
        print(f"Start MCP server: {python} -m metasearchmcp.broker")


def install_docker(args: argparse.Namespace) -> None:
    copied_env = ensure_env_file(ROOT, force=args.force_env)
    if copied_env:
        print("Created .env from .env.example")
    else:
        print("Keeping existing .env")

    docker = shutil.which("docker")
    if not docker:
        raise RuntimeError("Docker is required for --mode docker")

    command = [docker, "compose", "up", "-d", "--build"]
    if args.no_detach:
        command = [docker, "compose", "up", "--build"]
    run(command)

    if not args.no_detach:
        print("")
        print("MetaSearchMCP is running at http://localhost:8000")
        print("Stop it with: docker compose down")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Install and optionally run MetaSearchMCP in one command.",
    )
    parser.add_argument(
        "--mode",
        choices=("local", "docker"),
        default="local",
        help="Install into a local virtualenv or deploy with Docker Compose.",
    )
    parser.add_argument(
        "--dev",
        action="store_true",
        help="Install development dependencies.",
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help="Run the full pytest suite after installation.",
    )
    parser.add_argument(
        "--run",
        action="store_true",
        help="Start the HTTP API after local installation.",
    )
    parser.add_argument(
        "--force-env",
        action="store_true",
        help="Overwrite .env from .env.example.",
    )
    parser.add_argument(
        "--no-detach",
        action="store_true",
        help="Keep Docker Compose attached instead of running in the background.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.mode == "docker":
            install_docker(args)
        else:
            install_local(args)
    except subprocess.CalledProcessError as exc:
        return exc.returncode
    except Exception as exc:
        print(f"install failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
