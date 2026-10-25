"""Tests for cross-platform OS helpers (oscompat.py)."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest
from agentguard import oscompat


def test_is_pid_alive_self():
    assert oscompat.is_pid_alive(os.getpid()) is True


def test_is_pid_alive_invalid():
    assert oscompat.is_pid_alive(None) is False
    assert oscompat.is_pid_alive(-1) is False
    assert oscompat.is_pid_alive(0) is False
    # Very high PID that should not exist
    assert oscompat.is_pid_alive(9999999) is False


def test_memory_info():
    total_mb, avail_mb = oscompat.memory_info()
    # On any valid system, total RAM should be > 0
    assert total_mb > 0
    assert avail_mb >= 0


def test_cpu_info():
    model, flags = oscompat.cpu_info()
    assert isinstance(model, str)
    assert len(model) > 0
    assert isinstance(flags, set)


def test_detached_popen_kwargs():
    kwargs = oscompat.detached_popen_kwargs(detached=True)
    assert isinstance(kwargs, dict)
    if oscompat.IS_WINDOWS:
        assert "creationflags" in kwargs
    else:
        assert kwargs.get("start_new_session") is True


def test_hook_command():
    script = Path("/path/to/hook.py")
    cmd = oscompat.hook_command(script, python="/usr/bin/python3")
    assert "/path/to/hook.py" in cmd
    assert "/usr/bin/python3" in cmd


def test_secure_file(tmp_path: Path):
    test_file = tmp_path / "secret.txt"
    test_file.write_text("supersecret\n", encoding="utf-8")
    oscompat.secure_file(test_file)
    assert test_file.is_file()
    assert test_file.read_text(encoding="utf-8").strip() == "supersecret"


def test_exe_name():
    if oscompat.IS_WINDOWS:
        assert oscompat.exe_name("cloudflared") == "cloudflared.exe"
        assert oscompat.exe_name("cloudflared.exe") == "cloudflared.exe"
    else:
        assert oscompat.exe_name("cloudflared") == "cloudflared"
