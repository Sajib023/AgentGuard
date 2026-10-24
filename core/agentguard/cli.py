"""CLI: ``agentguard serve`` (service), ``setup``, ``status``, ``stop``, ``doctor``."""

from __future__ import annotations

import argparse
import contextlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time


def _agentguard_home() -> Path:
    base = Path(os.environ.get("AGENTGUARD_HOME") or (Path.home() / ".agentguard")).expanduser()
    base.mkdir(parents=True, exist_ok=True)
    return base


def _pidfile() -> Path:
    return _agentguard_home() / "agentguard.pid"


def _logfile() -> Path:
    return _agentguard_home() / "agentguard.log"


def _repo_root() -> Path:
    env_root = os.environ.get("AGENTGUARD_REPO_ROOT")
    if env_root:
        p = Path(env_root).expanduser().resolve()
        if (p / "integrations").is_dir():
            return p
    here = Path(__file__).resolve().parents[2]
    if (here / "integrations").is_dir():
        return here
    app_dir = _agentguard_home() / "app"
    if (app_dir / "integrations").is_dir():
        return app_dir
    return here


def _is_pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _wait_for_health(host: str, port: int, timeout_s: float = 10.0) -> dict | None:
    import urllib.request

    check_host = "127.0.0.1" if host in ("0.0.0.0", "::") else host
    url = f"http://{check_host}:{port}/v1/healthz"
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1.0) as r:
                if r.status == 200:
                    return json.loads(r.read().decode("utf-8"))
        except Exception:
            pass
        time.sleep(0.2)
    return None


def cmd_serve(args: argparse.Namespace) -> int:
    from .config import Config

    cfg = Config.load(args.config)
    if args.port:
        cfg.server.port = args.port
    if args.host:
        cfg.server.host = args.host
    if args.observe:
        cfg.firewall.observe_mode = True

    if getattr(args, "daemon", False):
        pf = _pidfile()
        if pf.is_file():
            with contextlib.suppress(ValueError):
                existing_pid = int(pf.read_text().strip() or 0)
                if _is_pid_alive(existing_pid):
                    health = _wait_for_health(cfg.server.host, cfg.server.port, timeout_s=1.5)
                    if health:
                        print(f"AgentGuard already running (pid {existing_pid}) at http://{cfg.server.host}:{cfg.server.port}/")
                        return 0
        cmd = [sys.executable, "-m", "agentguard.cli", "serve"]
        if args.config:
            cmd.extend(["--config", args.config])
        if args.host:
            cmd.extend(["--host", args.host])
        if args.port:
            cmd.extend(["--port", str(args.port)])
        if args.observe:
            cmd.append("--observe")
        log_path = _logfile()
        with open(log_path, "a", encoding="utf-8") as log_fh:
            proc = subprocess.Popen(
                cmd,
                stdout=log_fh,
                stderr=log_fh,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
            )
        health = _wait_for_health(cfg.server.host, cfg.server.port, timeout_s=12.0)
        if health:
            print(f"AgentGuard started in background (pid {proc.pid})")
            print(f"  dashboard: http://{cfg.server.host}:{cfg.server.port}/")
            print(f"  logs:      {log_path}")
            return 0
        print(f"AgentGuard daemon (pid {proc.pid}) did not pass healthcheck within 12s — check {log_path}", file=sys.stderr)
        with contextlib.suppress(Exception):
            lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-15:]
            if lines:
                print("\n--- Last log lines ---", file=sys.stderr)
                print("\n".join(lines), file=sys.stderr)
        return 1

    _pidfile().write_text(str(os.getpid()))
    try:
        import uvicorn
        from .api import create_app

        app = create_app(cfg)
        uvicorn.run(app, host=cfg.server.host, port=cfg.server.port, log_level="info")
    except KeyboardInterrupt:
        print("\nshutting down")
    finally:
        with contextlib.suppress(FileNotFoundError):
            _pidfile().unlink()
    return 0


def cmd_stop(_: argparse.Namespace) -> int:
    pf = _pidfile()
    if not pf.is_file():
        print("no pidfile — service not started via agentguard CLI")
        return 1
    pid = int(pf.read_text().strip() or 0)
    if not pid or pid == os.getpid():
        print("invalid or self pid — refusing")
        return 1
    try:
        os.kill(pid, signal.SIGTERM)
        print(f"sent SIGTERM to {pid}")
    except ProcessLookupError:
        print("process already gone")
        with contextlib.suppress(FileNotFoundError):
            pf.unlink()
        return 0
    for _ in range(30):
        try:
            os.kill(pid, 0)
            time.sleep(0.15)
        except ProcessLookupError:
            print("service stopped")
            break
    else:
        os.kill(pid, signal.SIGKILL)
        print("forced SIGKILL")
    with contextlib.suppress(FileNotFoundError):
        pf.unlink()
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    from .config import Config

    cfg = Config.load(getattr(args, "config", None))
    pf = _pidfile()
    pid = 0
    if pf.is_file():
        with contextlib.suppress(ValueError):
            pid = int(pf.read_text().strip() or 0)
    alive = _is_pid_alive(pid)
    health = _wait_for_health(cfg.server.host, cfg.server.port, timeout_s=1.5)
    if health:
        mode = "observe" if health.get("observe_mode") else "enforce"
        print(f"AgentGuard status: RUNNING (http://{cfg.server.host}:{cfg.server.port}/)")
        if pid and alive:
            print(f"  pid:          {pid}")
        print(f"  mode:         {mode}")
        print(f"  sessions:     {health.get('sessions_tracked', 0)}")
        print(f"  rag_chunks:   {health.get('rag_chunks', 0)}")
        print(f"  mcp_servers:  {health.get('mcp_servers', 0)}")
        print(f"  llama_guard:  {health.get('llama_guard', 'unknown')}")
        return 0
    print("AgentGuard status: STOPPED")
    return 1


def _setup_opencode(repo: Path) -> bool:
    src = repo / "integrations" / "opencode" / "plugin" / "agentguard-plugin.js"
    if not src.is_file():
        print(f"  [opencode] skipped (missing {src})")
        return False
    xdg = Path(os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config")).expanduser()
    dest_dir = xdg / "opencode" / "plugins" / "agentguard"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / "index.js"
    shutil.copy2(src, dest)
    print(f"  [opencode] installed global plugin -> {dest}")
    return True


def _merge_hook_groups(existing_groups: list, new_groups: list, script_marker: str) -> list:
    """Remove any existing hook entries referencing `script_marker` and append `new_groups`."""
    cleaned: list = []
    for grp in existing_groups:
        if not isinstance(grp, dict):
            cleaned.append(grp)
            continue
        hooks = grp.get("hooks", [])
        if isinstance(hooks, list):
            kept = [
                h for h in hooks
                if not (isinstance(h, dict) and script_marker in str(h.get("command", "")))
            ]
            if kept:
                grp_copy = dict(grp)
                grp_copy["hooks"] = kept
                cleaned.append(grp_copy)
        else:
            cleaned.append(grp)
    cleaned.extend(new_groups)
    return cleaned


def _setup_claude(repo: Path) -> bool:
    src = repo / "integrations" / "claude" / "hooks" / "agentguard_hook.py"
    if not src.is_file():
        print(f"  [claude]   skipped (missing {src})")
        return False
    hooks_dir = _agentguard_home() / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    dest_hook = hooks_dir / "agentguard_hook.py"
    shutil.copy2(src, dest_hook)
    dest_hook.chmod(0o755)

    claude_dir = Path(os.environ.get("CLAUDE_CONFIG_DIR") or (Path.home() / ".claude")).expanduser()
    claude_dir.mkdir(parents=True, exist_ok=True)
    settings_path = claude_dir / "settings.json"
    doc: dict = {}
    if settings_path.is_file():
        try:
            loaded = json.loads(settings_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                doc = loaded
        except Exception:
            backup = settings_path.with_suffix(".json.bak")
            shutil.copy2(settings_path, backup)
            print(f"  [claude]   backed up unreadable settings.json -> {backup}")

    hooks_map = doc.setdefault("hooks", {})
    if not isinstance(hooks_map, dict):
        hooks_map = {}
        doc["hooks"] = hooks_map

    cmd_str = f"python3 {dest_hook}"
    events = ("SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop", "SessionEnd")
    for ev in events:
        existing = hooks_map.get(ev, [])
        if not isinstance(existing, list):
            existing = []
        new_group = [{"hooks": [{"type": "command", "command": cmd_str}]}]
        hooks_map[ev] = _merge_hook_groups(existing, new_group, "agentguard_hook.py")

    settings_path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    print(f"  [claude]   installed hook -> {dest_hook} (merged into {settings_path})")
    return True


def _setup_codex(repo: Path) -> bool:
    src = repo / "integrations" / "codex" / "hooks" / "agentguard_codex_hook.py"
    example = repo / "integrations" / "codex" / "hooks.json.example"
    if not src.is_file() or not example.is_file():
        print(f"  [codex]    skipped (missing {src})")
        return False
    codex_home = Path(os.environ.get("CODEX_HOME") or (Path.home() / ".codex")).expanduser()
    hooks_dir = codex_home / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    dest_hook = hooks_dir / "agentguard_codex_hook.py"
    shutil.copy2(src, dest_hook)
    dest_hook.chmod(0o755)

    template = json.loads(example.read_text(encoding="utf-8"))
    template_hooks = template.get("hooks", {})
    cmd_str = f"python3 {dest_hook}"

    hooks_json_path = codex_home / "hooks.json"
    doc: dict = {}
    if hooks_json_path.is_file():
        try:
            loaded = json.loads(hooks_json_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                doc = loaded
        except Exception:
            backup = hooks_json_path.with_suffix(".json.bak")
            shutil.copy2(hooks_json_path, backup)
            print(f"  [codex]    backed up unreadable hooks.json -> {backup}")

    doc.setdefault("description", template.get("description", "AgentGuard lifecycle hooks"))
    hooks_map = doc.setdefault("hooks", {})
    if not isinstance(hooks_map, dict):
        hooks_map = {}
        doc["hooks"] = hooks_map

    for ev, groups in template_hooks.items():
        updated_groups = json.loads(json.dumps(groups))
        for g in updated_groups:
            g.pop("_comment", None)
            for h in g.get("hooks", []):
                h["command"] = cmd_str
        existing = hooks_map.get(ev, [])
        if not isinstance(existing, list):
            existing = []
        hooks_map[ev] = _merge_hook_groups(existing, updated_groups, "agentguard_codex_hook.py")

    hooks_json_path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    print(f"  [codex]    installed hook -> {dest_hook} (merged into {hooks_json_path})")
    return True


def cmd_setup(args: argparse.Namespace) -> int:
    repo = _repo_root()
    print(f"AgentGuard setup (repo: {repo})")
    any_selected = args.opencode or args.claude or args.codex
    do_opencode = args.opencode or not any_selected
    do_claude = args.claude or not any_selected
    do_codex = args.codex or not any_selected

    if do_opencode:
        _setup_opencode(repo)
    if do_claude:
        _setup_claude(repo)
    if do_codex:
        _setup_codex(repo)

    if args.pull_model:
        ollama_bin = shutil.which("ollama")
        if ollama_bin:
            from .config import Config

            cfg = Config.load(args.config)
            model = cfg.firewall.llm_guard.model
            print(f"  [ollama]   pulling {model}...")
            subprocess.run([ollama_bin, "pull", model], check=False)
        else:
            print("  [ollama]   skipped (ollama binary not found; Tier 1-3.5 remain active)")

    if args.start:
        serve_args = argparse.Namespace(
            config=args.config,
            host=None,
            port=None,
            observe=False,
            daemon=True,
        )
        return cmd_serve(serve_args)
    return 0


def cmd_doctor(_: argparse.Namespace) -> int:
    from .config import Config, default_db_path

    cfg = Config.load()
    print("AgentGuard doctor")
    print(f"  python:      {sys.version.split()[0]}")
    print(f"  db path:     {cfg.server.db_path or default_db_path()}")
    for mod in ("fastapi", "uvicorn", "httpx", "yaml", "pydantic"):
        try:
            __import__(mod)
            print(f"  dep {mod}: ok")
        except Exception as e:  # pragma: no cover
            print(f"  dep {mod}: MISSING ({e})")
    import httpx

    lg = cfg.firewall.llm_guard
    try:
        r = httpx.get(f"{lg.endpoint}/api/tags", timeout=2.0)
        models = [m.get("name", "") for m in r.json().get("models", [])]
        has = any(name.split(":")[0] == lg.model.split(":")[0] for name in models)
        print(f"  ollama:      reachable ({len(models)} models) — llama-guard: {'yes' if has else 'no, pull it'}")
    except Exception as e:
        print(f"  ollama:      unreachable ({type(e).__name__}) — firewall falls back to rules+heuristics")
    print("Done.")
    return 0


def cmd_mcp(args: argparse.Namespace) -> int:
    import asyncio
    from .breaker.service import CircuitBreaker
    from .bus import EventBus
    from .config import Config, default_db_path
    from .db import Database
    from .firewall.engine import FirewallEngine
    from .mcp.server import MCPHub, run_stdio_mcp_server
    from .rag.service import ThreatRAGService
    from .store import Store

    cfg = Config.load(args.config)
    db = Database(cfg.server.db_path or default_db_path())
    store = Store(db)
    bus = EventBus()
    rag = ThreatRAGService(db)
    fw = FirewallEngine(cfg.firewall, rag=rag)
    breaker = CircuitBreaker(cfg.breaker, store, bus)
    hub = MCPHub(store=store, firewall=fw, breaker=breaker, rag=rag)
    try:
        return asyncio.run(run_stdio_mcp_server(hub, server_id=args.server))
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(prog="agentguard", description=__doc__)
    sub = parser.add_subparsers(dest="cmd")
    serve = sub.add_parser("serve", help="run the AgentGuard service")
    serve.add_argument("--config", help="YAML config path")
    serve.add_argument("--host")
    serve.add_argument("--port", type=int)
    serve.add_argument("--observe", action="store_true", help="start in observe-only mode")
    serve.add_argument("-d", "--daemon", action="store_true", help="run service detached in the background")

    setup_p = sub.add_parser("setup", help="auto-configure OpenCode, Claude Code, and Codex CLI hooks")
    setup_p.add_argument("--config", help="YAML config path")
    setup_p.add_argument("--opencode", action="store_true", help="install OpenCode plugin only")
    setup_p.add_argument("--claude", action="store_true", help="install Claude Code hooks only")
    setup_p.add_argument("--codex", action="store_true", help="install Codex CLI hooks only")
    setup_p.add_argument("--pull-model", action="store_true", help="pull local llama-guard3:1b via Ollama if installed")
    setup_p.add_argument("--start", action="store_true", help="start AgentGuard daemon after setup")

    status_p = sub.add_parser("status", help="check running AgentGuard daemon status and health")
    status_p.add_argument("--config", help="YAML config path")

    mcp_p = sub.add_parser("mcp", help="run an AgentGuard MCP server over stdio")
    mcp_p.add_argument(
        "--server",
        default="agentguard-firewall-mcp",
        choices=["agentguard-firewall-mcp", "agentguard-breaker-mcp", "agentguard-lineage-mcp"],
        help="which custom MCP server to expose over stdio",
    )
    mcp_p.add_argument("--config", help="YAML config path")
    sub.add_parser("stop", help="stop a running service (pidfile)")
    sub.add_parser("doctor", help="check environment (deps, ollama, db)")
    sub.add_parser("version", help="print version")
    args = parser.parse_args()
    if args.cmd == "serve":
        sys.exit(cmd_serve(args))
    if args.cmd == "setup":
        sys.exit(cmd_setup(args))
    if args.cmd == "status":
        sys.exit(cmd_status(args))
    if args.cmd == "mcp":
        sys.exit(cmd_mcp(args))
    if args.cmd == "stop":
        sys.exit(cmd_stop(args))
    if args.cmd == "doctor":
        sys.exit(cmd_doctor(args))
    if args.cmd == "version":
        from . import __version__

        print(__version__)
        sys.exit(0)
    parser.print_help()


if __name__ == "__main__":
    main()

