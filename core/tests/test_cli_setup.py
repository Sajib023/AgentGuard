"""Tests for `agentguard setup` auto-configuration and idempotent hook merging."""

from __future__ import annotations

import json
from pathlib import Path

from agentguard.cli import _repo_root, _setup_claude, _setup_codex, _setup_opencode


def test_setup_integrations_idempotent_merge(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("AGENTGUARD_HOME", str(tmp_path / "ag_home"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex"))

    # Pre-seed user settings to verify non-destructive merging
    claude_dir = tmp_path / "claude"
    claude_dir.mkdir(parents=True)
    (claude_dir / "settings.json").write_text(
        json.dumps(
            {
                "theme": "dark",
                "hooks": {
                    "PreToolUse": [
                        {"hooks": [{"type": "command", "command": "echo existing-user-hook"}]}
                    ]
                },
            }
        ),
        encoding="utf-8",
    )

    codex_dir = tmp_path / "codex"
    codex_dir.mkdir(parents=True)
    (codex_dir / "hooks.json").write_text(
        json.dumps(
            {
                "hooks": {
                    "PreToolUse": [
                        {"hooks": [{"type": "command", "command": "echo existing-codex-hook"}]}
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    repo = _repo_root()
    assert _setup_opencode(repo) is True
    assert _setup_claude(repo) is True
    assert _setup_codex(repo) is True

    # Run a second time to verify idempotency (no duplicate AgentGuard hook entries)
    assert _setup_claude(repo) is True
    assert _setup_codex(repo) is True

    opencode_plugin = tmp_path / "xdg" / "opencode" / "plugins" / "agentguard" / "index.js"
    assert opencode_plugin.is_file()

    claude_settings = json.loads((claude_dir / "settings.json").read_text(encoding="utf-8"))
    assert claude_settings["theme"] == "dark"
    assert len(claude_settings["hooks"]["PreToolUse"]) == 2
    assert len(claude_settings["hooks"]["SessionStart"]) == 1

    codex_hooks = json.loads((codex_dir / "hooks.json").read_text(encoding="utf-8"))
    assert len(codex_hooks["hooks"]["PreToolUse"]) == 2
    assert len(codex_hooks["hooks"]["SessionStart"]) == 1
