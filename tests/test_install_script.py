from __future__ import annotations

import importlib.util
import os
from pathlib import Path


def _load_install_module():
    script = Path(__file__).resolve().parents[1] / "scripts" / "install.py"
    spec = importlib.util.spec_from_file_location("metasearchmcp_install", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_install_target_uses_dev_extra_when_requested():
    install = _load_install_module()

    assert install.install_target(False) == "."
    assert install.install_target(True) == ".[dev]"


def test_venv_python_uses_platform_layout(tmp_path):
    install = _load_install_module()

    expected = (
        tmp_path / "Scripts" / "python.exe"
        if os.name == "nt"
        else tmp_path / "bin" / "python"
    )
    assert install.venv_python(tmp_path) == expected


def test_ensure_env_file_copies_template_without_overwriting(tmp_path):
    install = _load_install_module()
    (tmp_path / ".env.example").write_text("HOST=0.0.0.0\n", encoding="utf-8")

    assert install.ensure_env_file(tmp_path) is True
    assert (tmp_path / ".env").read_text(encoding="utf-8") == "HOST=0.0.0.0\n"

    (tmp_path / ".env").write_text("HOST=127.0.0.1\n", encoding="utf-8")
    assert install.ensure_env_file(tmp_path) is False
    assert (tmp_path / ".env").read_text(encoding="utf-8") == "HOST=127.0.0.1\n"


def test_ensure_env_file_force_overwrites_existing_file(tmp_path):
    install = _load_install_module()
    (tmp_path / ".env.example").write_text("PORT=8000\n", encoding="utf-8")
    (tmp_path / ".env").write_text("PORT=9000\n", encoding="utf-8")

    assert install.ensure_env_file(tmp_path, force=True) is True
    assert (tmp_path / ".env").read_text(encoding="utf-8") == "PORT=8000\n"
