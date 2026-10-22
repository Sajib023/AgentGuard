"""CLI: ``agentguard serve`` (service), ``agentguard stop``, ``doctor`` (env checks)."""

from __future__ import annotations

import argparse
import contextlib
import os
import signal
import sys
import time

from .config import Config, default_db_path


def _pidfile() -> Path:
    from pathlib import Path

    base = Path(os.environ.get("AGENTGUARD_HOME") or (Path.home() / ".agentguard"))
    base.mkdir(parents=True, exist_ok=True)
    return base / "agentguard.pid"


def cmd_serve(args: argparse.Namespace) -> int:
    cfg = Config.load(args.config)
    if args.port:
        cfg.server.port = args.port
    if args.host:
        cfg.server.host = args.host
    if args.observe:
        cfg.firewall.observe_mode = True
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


def cmd_doctor(_: argparse.Namespace) -> int:
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


def main() -> None:
    parser = argparse.ArgumentParser(prog="agentguard", description=__doc__)
    sub = parser.add_subparsers(dest="cmd")
    serve = sub.add_parser("serve", help="run the AgentGuard service")
    serve.add_argument("--config", help="YAML config path")
    serve.add_argument("--host")
    serve.add_argument("--port", type=int)
    serve.add_argument("--observe", action="store_true", help="start in observe-only mode")
    sub.add_parser("stop", help="stop a running service (pidfile)")
    sub.add_parser("doctor", help="check environment (deps, ollama, db)")
    sub.add_parser("version", help="print version")
    args = parser.parse_args()
    if args.cmd == "serve":
        sys.exit(cmd_serve(args))
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
