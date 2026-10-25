"""Cloudflare Quick Tunnel management for AgentGuard.

Launches ``cloudflared tunnel --url http://127.0.0.1:<port>``
(a *quick tunnel* — no Cloudflare account, no config file needed),
captures the generated public ``https://<id>.trycloudflare.com`` URL,
and persists it to ``$AGENTGUARD_HOME/tunnel_url`` so ``agentguard
status`` and the installer summary can display it.

Remote requests that arrive through the tunnel must pass the dashboard
access-code auth (``agentguard.security``).
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Callable

from . import oscompat

TUNNEL_URL_RE = re.compile(r"https://[-a-zA-Z0-9.]+\.trycloudflare\.com")


def _well_known_paths() -> tuple[Path, ...]:
    if oscompat.IS_WINDOWS:
        local_app = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
        program_files = Path(os.environ.get("ProgramFiles") or r"C:\Program Files")
        program_files_x86 = Path(os.environ.get("ProgramFiles(x86)") or r"C:\Program Files (x86)")
        return (
            local_app / "AgentGuard" / "bin" / "cloudflared.exe",
            Path.home() / ".agentguard" / "bin" / "cloudflared.exe",
            local_app / "Microsoft" / "WinGet" / "Links" / "cloudflared.exe",
            program_files / "cloudflared" / "cloudflared.exe",
            program_files_x86 / "cloudflared" / "cloudflared.exe",
        )
    return (
        Path.home() / ".local" / "bin" / "cloudflared",
        Path("/usr/local/bin/cloudflared"),
        Path("/usr/bin/cloudflared"),
        Path("/opt/homebrew/bin/cloudflared"),
    )


WELL_KNOWN_PATHS = _well_known_paths()


def _agentguard_home() -> Path:
    base = Path(os.environ.get("AGENTGUARD_HOME") or (Path.home() / ".agentguard")).expanduser()
    base.mkdir(parents=True, exist_ok=True)
    return base


def find_cloudflared(explicit: str = "") -> Path | None:
    """Locate the cloudflared binary: explicit config > $PATH > well-known paths."""
    if explicit:
        p = Path(explicit).expanduser()
        if oscompat.is_executable_file(p):
            return p
    which = shutil.which("cloudflared")
    if which:
        return Path(which)
    for p in WELL_KNOWN_PATHS:
        if oscompat.is_executable_file(p):
            return p
    return None


def write_tunnel_url(url: str | None, state_dir: Path | None = None) -> None:
    d = state_dir or _agentguard_home()
    try:
        if url:
            (d / "tunnel_url").write_text(url.strip() + "\n", encoding="utf-8")
    except OSError:
        pass


def read_tunnel_url(state_dir: Path | None = None) -> str | None:
    try:
        val = ((state_dir or _agentguard_home()) / "tunnel_url").read_text(encoding="utf-8").strip()
        return val or None
    except OSError:
        return None


def clear_tunnel_state(state_dir: Path | None = None) -> None:
    d = state_dir or _agentguard_home()
    for name in ("tunnel_url", "tunnel.pid"):
        try:
            (d / name).unlink(missing_ok=True)
        except OSError:
            pass


def stop_stale_tunnel(state_dir: Path | None = None, port: int | None = None, host: str = "127.0.0.1") -> bool:
    """Kill orphaned cloudflared processes (main + workers) from a previous hard-killed run.

    The tunnel command embeds ``--url http://<host>:<port>``, which is unique to
    AgentGuard's tunnel, so a full-cmdline match is safe and covers worker processes
    the main process spawns."""
    d = state_dir or _agentguard_home()
    killed = False
    if port:
        killed = oscompat.kill_matching(f"--url http://{host}:{port}") or killed
    pid_file = d / "tunnel.pid"
    try:
        pid = int(pid_file.read_text(encoding="utf-8").strip() or 0)
    except (OSError, ValueError):
        pid = 0
    if pid > 0 and pid != os.getpid():
        args = oscompat.process_cmdline(pid)
        if "cloudflared" in args and "tunnel" in args:
            killed = oscompat.terminate(pid) or killed
    clear_tunnel_state(d)
    return killed


class TunnelManager:
    """Owns the cloudflared subprocess for one service run."""

    def __init__(
        self,
        *,
        port: int,
        host: str = "127.0.0.1",
        binary: Path,
        extra_args: list[str] | None = None,
        state_dir: Path | None = None,
        on_url: Callable[[str], None] | None = None,
    ):
        self.port = int(port)
        self.host = "127.0.0.1" if host in ("0.0.0.0", "::") else host
        self.binary = binary
        self.extra_args = list(extra_args or [])
        self.state_dir = state_dir or _agentguard_home()
        self.on_url = on_url
        self.proc: subprocess.Popen | None = None
        self.url: str | None = None
        self._url_event = threading.Event()
        self._lock = threading.Lock()

    # ------------------------------------------------------------- lifecycle
    def start(self) -> bool:
        with self._lock:
            try:
                (self.state_dir / "tunnel_url").unlink(missing_ok=True)
            except OSError:
                pass
        config_url = f"http://{self.host}:{self.port}"
        cmd = [str(self.binary), "tunnel", "--url", config_url, "--no-autoupdate"]
        cmd.extend(self.extra_args)
        try:
            self.proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,  # cloudflared writes everything to stderr
                stdin=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                **oscompat.detached_popen_kwargs(detached=False),
            )
        except OSError as exc:
            print(f"[agentguard] tunnel: failed to start cloudflared ({exc})", flush=True)
            return False
        with self._lock:
            (self.state_dir / "tunnel.pid").write_text(str(self.proc.pid), encoding="utf-8")
        threading.Thread(target=self._pump_output, name="agentguard-tunnel", daemon=True).start()
        return True

    def _pump_output(self) -> None:
        proc = self.proc
        if proc is None or proc.stdout is None:
            return
        for line in proc.stdout:
            if not line:
                break
            if self.url is None:
                match = TUNNEL_URL_RE.search(line)
                if match:
                    self.url = match.group(0)
                    write_tunnel_url(self.url, self.state_dir)
                    self._url_event.set()
                    print(f"[agentguard] tunnel ready: {self.url}", flush=True)
                    if self.on_url:
                        try:
                            self.on_url(self.url)
                        except Exception:
                            pass
        self._url_event.set()

    def wait_for_url(self, timeout: float = 60.0) -> str | None:
        self._url_event.wait(timeout)
        return self.url

    def stop(self) -> None:
        """Terminate the tunnel subprocess and clear state files."""
        proc = self.proc
        self.proc = None
        if proc is None or proc.poll() is not None:
            return
        try:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                try:
                    proc.wait(timeout=3)
                except Exception:
                    pass
        except Exception:
            pass
        clear_tunnel_state(self.state_dir)


def setup_tunnel(*, cfg, state_dir: Path | None = None, on_url: Callable[[str], None] | None = None) -> TunnelManager | None:
    """Create + start a TunnelManager for the service run if enabled & available.

    Returns ``None`` when disabled, cloudflared is missing, or startup fails —
    the local dashboard keeps working without the public URL in those cases.
    """
    from .config import TunnelConfig

    tunnel_cfg = getattr(cfg, "tunnel", None) or TunnelConfig()
    if not tunnel_cfg.enabled:
        return None
    binary = find_cloudflared(tunnel_cfg.cloudflared_path)
    if binary is None:
        print(
            "[agentguard] tunnel: cloudflared not found — skipping public URL "
            "(local dashboard stays available at the configured port)",
            flush=True,
        )
        clear_tunnel_state(state_dir or _agentguard_home())
        return None
    manager = TunnelManager(
        port=cfg.server.port,
        host=cfg.server.host,
        binary=binary,
        extra_args=tunnel_cfg.extra_args,
        state_dir=state_dir,
        on_url=on_url,
    )
    stop_stale_tunnel(manager.state_dir, port=manager.port, host=manager.host)
    if not manager.start():
        return None
    return manager
