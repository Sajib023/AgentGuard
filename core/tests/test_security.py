"""Access-code auth (`agentguard.security`) + Cloudflare tunnel glue (`agentguard.tunnel`)."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from agentguard.api import create_app
from agentguard.config import Config
from agentguard.security import (
    AuthManager,
    CODE_ALPHABET,
    format_access_code,
    generate_access_code,
    read_access_code,
)
from agentguard.tunnel import (
    clear_tunnel_state,
    find_cloudflared,
    read_tunnel_url,
    write_tunnel_url,
)

REMOTE_HEADERS = {"CF-Connecting-IP": "203.0.113.10", "CF-Ray": "8791b4fb4-test"}


def make_cfg(tmp_path: Path, **overrides) -> Config:
    cfg = Config.load()
    cfg.firewall.llm_guard.enabled = False
    cfg.server.db_path = str(tmp_path / "sec.db")
    cfg.tunnel.enabled = False  # never spawn cloudflared from unit tests
    for attr, val in overrides.items():
        section, _, key = attr.partition("__")
        if key:
            setattr(getattr(cfg, section), key, val)
        else:
            setattr(cfg, attr, val)
    return cfg


def remote_client(tmp_path: Path, **overrides) -> TestClient:
    app = create_app(make_cfg(tmp_path, **overrides))
    return TestClient(app, follow_redirects=False)


# --------------------------------------------------------------------- codes
def test_generate_access_code_shape_and_randomness():
    codes = {generate_access_code() for _ in range(50)}
    assert len(codes) == 50  # 8 chars over 34 symbols: collisions practically impossible
    for code in codes:
        assert len(code) == 8
        assert set(code) <= set(CODE_ALPHABET)
        assert "I" not in code and "O" not in code and "0" not in code and "1" not in code
    assert len(generate_access_code(12)) == 12


def test_format_access_code():
    assert format_access_code("ABCD1234") == "ABCD-1234"
    assert format_access_code("ABC") == "A-BC"
    assert format_access_code("") == ""
    assert format_access_code(None) == ""


def test_auth_manager_verify_and_lockout(tmp_path: Path):
    auth = AuthManager(enabled=True, max_attempts=3, lockout_seconds=60.0, state_dir=tmp_path)
    assert read_access_code(state_dir=tmp_path) == auth.code
    assert auth.verify_token(auth.token)
    assert not auth.verify_token("junk") and not auth.verify_token(None)
    assert auth.verify_code(auth.code) is True
    for _ in range(3):
        assert auth.verify_code("WRONG000") is False
    assert auth.is_locked() and auth.retry_after() > 0
    # correct code is refused while locked out
    assert auth.verify_code(auth.code) is False


def test_auth_manager_persists_and_formats(tmp_path: Path):
    auth = AuthManager(enabled=True, state_dir=tmp_path)
    code_file = tmp_path / "access_code"
    assert code_file.is_file()
    assert oct(code_file.stat().st_mode & 0o777) == "0o600"
    assert format_access_code(auth.code) == f"{auth.code[:4]}-{auth.code[4:]}"


# -------------------------------------------------------------- http gating
def test_local_client_bypasses_auth(tmp_path: Path):
    client = remote_client(tmp_path)
    with client:
        assert client.get("/v1/healthz").status_code == 200
        assert client.get("/").status_code == 200


def test_remote_client_requires_code(tmp_path: Path):
    client = remote_client(tmp_path)
    with client:
        auth = client.app.state.ctx.auth  # type: ignore[attr-defined]
        # unauthenticated remote: API -> 401, app page -> redirect to /login
        r = client.get("/v1/healthz", headers=REMOTE_HEADERS)
        assert r.status_code == 401 and "authentication required" in r.json()["detail"]
        r = client.get("/", headers=REMOTE_HEADERS)
        assert r.status_code == 307 and r.headers["location"].startswith("/login")
        # wrong code -> 401
        r = client.post("/v1/auth/login", headers=REMOTE_HEADERS, json={"code": "NOPE1234"})
        assert r.status_code == 401
        # correct code -> session cookie (TestClient keeps the cookie jar)
        r = client.post("/v1/auth/login", headers=REMOTE_HEADERS, json={"code": auth.code})
        assert r.status_code == 200 and r.json()["ok"] is True
        # remote traffic now passes with the cookie
        assert client.get("/v1/healthz", headers=REMOTE_HEADERS).status_code == 200
        assert client.get("/", headers=REMOTE_HEADERS).status_code == 200


def test_remote_bearer_token_header(tmp_path: Path):
    client = remote_client(tmp_path)
    with client:
        auth = client.app.state.ctx.auth  # type: ignore[attr-defined]
        headers = dict(REMOTE_HEADERS, authorization=f"Bearer {auth.token}")
        r = client.get("/v1/breaker/status", headers=headers)
        assert r.status_code == 200


def test_remote_bruteforce_lockout(tmp_path: Path):
    client = remote_client(tmp_path, auth__max_attempts=2, auth__lockout_seconds=60.0)
    with client:
        for _ in range(2):
            r = client.post("/v1/auth/login", headers=REMOTE_HEADERS, json={"code": "WRONG000"})
            assert r.status_code == 401
        r = client.post("/v1/auth/login", headers=REMOTE_HEADERS, json={"code": "WRONG000"})
        assert r.status_code == 429 and r.json()["retry_after"] >= 59


def test_auth_disabled_lets_everyone_in(tmp_path: Path):
    client = remote_client(tmp_path, auth__enabled=False)
    with client:
        r = client.get("/v1/healthz", headers=REMOTE_HEADERS)
        assert r.status_code == 200
        assert r.json()["auth_enabled"] is False


def test_login_page_and_status_endpoints(tmp_path: Path):
    client = remote_client(tmp_path)
    with client:
        r = client.get("/login")
        assert r.status_code == 200 and "Access Code" in r.text
        r = client.get("/v1/auth/status", headers=REMOTE_HEADERS)
        d = r.json()
        assert d["auth_enabled"] is True and d["authenticated"] is False


def test_remote_websocket_closed_without_code(tmp_path: Path):
    client = remote_client(tmp_path)
    with client:
        auth = client.app.state.ctx.auth  # type: ignore[attr-defined]
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/v1/ws", headers=REMOTE_HEADERS):
                pass
        # with the token it opens again
        headers = dict(REMOTE_HEADERS, authorization=f"Bearer {auth.token}")
        with client.websocket_connect("/v1/ws?types=state_change", headers=headers) as ws:
            ws.send_text("ping")
            assert "pong" in ws.receive_text()


def test_ws_healthz_tunnel_field(tmp_path: Path):
    client = remote_client(tmp_path)
    with client:
        body = client.get("/v1/healthz").json()
        assert body["tunnel_url"] is None  # unit tests run with the tunnel disabled
        assert body["auth_enabled"] is True


# ------------------------------------------------------------------- tunnel
def test_tunnel_state_roundtrip(tmp_path: Path):
    assert read_tunnel_url(state_dir=tmp_path) is None
    write_tunnel_url("https://abc-test.example.trycloudflare.com", state_dir=tmp_path)
    assert read_tunnel_url(state_dir=tmp_path) == "https://abc-test.example.trycloudflare.com"
    clear_tunnel_state(state_dir=tmp_path)
    assert read_tunnel_url(state_dir=tmp_path) is None
    assert not (tmp_path / "tunnel_url").exists()


def test_find_cloudflared_explicit_path(tmp_path: Path, monkeypatch):
    import agentguard.tunnel as tunnel_mod
    import shutil as shutil_mod

    monkeypatch.setattr(shutil_mod, "which", lambda name: None)
    monkeypatch.setattr(tunnel_mod, "WELL_KNOWN_PATHS", ())

    assert find_cloudflared() is None  # nothing installed / discoverable
    from agentguard import oscompat

    fake = tmp_path / oscompat.exe_name("cloudflared")
    fake.write_text("#!/bin/sh\nexit 0\n")
    oscompat.make_executable(fake)
    assert find_cloudflared(str(fake)) == fake
    assert find_cloudflared(str(tmp_path / "missing")) is None
    assert find_cloudflared() is None
