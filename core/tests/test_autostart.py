"""Tests for autostart helper."""

from __future__ import annotations

from pathlib import Path
from agentguard import autostart


def test_write_boot_script(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("AGENTGUARD_HOME", str(tmp_path))
    script = autostart.write_boot_script(
        config=str(tmp_path / "custom.yaml"),
        port=8907,
        model="llama-guard3:1b",
        ollama="http://127.0.0.1:11434",
    )
    assert script.is_file()
    content = script.read_text(encoding="utf-8")
    assert "llama-guard3:1b" in content
    assert "8907" in content
    assert "agentguard" in content


def test_autostart_status():
    st = autostart.status()
    assert isinstance(st, dict)
    assert "platform" in st
