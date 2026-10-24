"""Dashboard access authentication: random access code + session token.

Every service launch generates a fresh random access code (printed to
the terminal and stored at ``$AGENTGUARD_HOME/access_code``). Anyone who
reaches the dashboard from outside the machine — e.g. through the
Cloudflare tunnel URL — must enter that code once; the browser then
receives an HttpOnly session cookie. Local processes (AgentGuard hooks,
CLI, localhost curl) are exempt so the firewall integrations keep
working without credentials.

Brute-force protection: after ``max_attempts`` failed logins the login
endpoint locks out for ``lockout_seconds``.

The middleware is a small pure-ASGI app (works for ``http`` and
``websocket`` scopes) so it also gates WebSocket subscribers.
"""

from __future__ import annotations

import os
import secrets
import string
import threading
import time
from http import cookies as http_cookies
from http.cookies import SimpleCookie
from pathlib import Path

from starlette.datastructures import Headers

TOKEN_COOKIE = "agentguard_token"

# Exempt from auth for remote clients: the login page itself and the login API.
EXEMPT_PATHS = ("/login", "/v1/auth/login", "/v1/auth/logout", "/v1/auth/status")

# Headers that indicate the request was forwarded through a proxy/tunnel
# (Cloudflare sets cf-* on every tunnel request).
FORWARDED_HEADERS = ("cf-connecting-ip", "cf-ray", "cf-worker", "cf-tunnel", "x-forwarded-host", "x-forwarded-for")

CODE_ALPHABET = "".join(sorted(set(string.ascii_uppercase + string.digits) - set("IO01")))


def _agentguard_home() -> Path:
    base = Path(os.environ.get("AGENTGUARD_HOME") or (Path.home() / ".agentguard")).expanduser()
    base.mkdir(parents=True, exist_ok=True)
    return base


def generate_access_code(length: int = 8) -> str:
    """Cryptographically random code from an unambiguous alphabet (no I/O/0/1)."""
    length = max(6, min(16, length))
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(length))


def format_access_code(code: str | None) -> str:
    """``ABCD1234`` -> ``ABCD-1234`` (display only; input accepts both forms)."""
    if not code:
        return ""
    half = max(1, len(code) // 2)
    return f"{code[:half]}-{code[half:]}"


def read_access_code(state_dir: Path | None = None) -> str | None:
    path = (state_dir or _agentguard_home()) / "access_code"
    try:
        val = path.read_text(encoding="utf-8").strip()
        return val or None
    except OSError:
        return None


class AuthManager:
    """Holds the per-launch access code + session token with lockout."""

    def __init__(
        self,
        *,
        enabled: bool = True,
        code_length: int = 8,
        max_attempts: int = 5,
        lockout_seconds: float = 30.0,
        state_dir: Path | None = None,
    ):
        self.enabled = bool(enabled)
        self.max_attempts = max(1, int(max_attempts))
        self.lockout_seconds = max(1.0, float(lockout_seconds))
        self._state_dir = state_dir or _agentguard_home()
        self.code = generate_access_code(code_length) if self.enabled else ""
        self.token = secrets.token_urlsafe(32)
        self._failures = 0
        self._lockout_until = 0.0
        self._lock = threading.Lock()
        if self.enabled:
            self._persist_code()

    # ------------------------------------------------------------------ state
    def _persist_code(self) -> None:
        """Store the code (0600) so `agentguard status` / install summary can show it."""
        try:
            path = self._state_dir / "access_code"
            path.write_text(self.code + "\n", encoding="utf-8")
            path.chmod(0o600)
        except OSError:
            pass

    # ------------------------------------------------------------ verification
    def is_locked(self) -> bool:
        return time.time() < self._lockout_until

    def retry_after(self) -> int:
        return max(0, int(round(self._lockout_until - time.time())))

    def verify_code(self, code: str | None) -> bool:
        """Check a login attempt; counts failures and enforces lockout."""
        if not self.enabled:
            return True
        with self._lock:
            if self.is_locked():
                return False
            matched = bool(code) and secrets.compare_digest(code.strip().upper(), self.code)
            if matched:
                self._failures = 0
                return True
            self._failures += 1
            if self._failures >= self.max_attempts:
                self._lockout_until = time.time() + self.lockout_seconds
                self._failures = 0
            return False

    def verify_token(self, token: str | None) -> bool:
        if not token:
            return False
        return secrets.compare_digest(token, self.token)


# ----------------------------------------------------------------- middleware
class AuthMiddleware:
    """Pure ASGI middleware gating non-local browser/API/WebSocket traffic.

    Local bypass: loopback clients *without* proxy-forwarding headers
    (hooks, CLI, localhost curl). Everyone else must present the session
    token via cookie, ``Authorization: Bearer <token>``,
    ``X-AgentGuard-Token`` header, or ``?token=`` query param.
    """

    def __init__(self, app, auth: AuthManager):
        self.app = app
        self.auth = auth

    # ------------------------------------------------------------- helpers
    @staticmethod
    def _is_local(scope) -> bool:
        client = scope.get("client") or (None, None)
        ip = client[0] if isinstance(client, (tuple, list)) else None
        headers = Headers(scope=scope)
        if any(hdr in headers for hdr in FORWARDED_HEADERS):
            return False
        if not ip:
            return True  # in-process / test clients
        try:
            import ipaddress

            return ipaddress.ip_address(ip).is_loopback
        except ValueError:
            return True  # non-IP client names (e.g. testclient)

    @staticmethod
    def _extract_token(scope) -> str | None:
        headers = Headers(scope=scope)
        authz = headers.get("authorization", "")
        if authz.startswith("Bearer "):
            return authz[7:].strip() or None
        direct = headers.get("x-agentguard-token")
        if direct:
            return direct.strip()
        raw_cookie = headers.get("cookie")
        if raw_cookie:
            try:
                parsed = SimpleCookie()
                parsed.load(raw_cookie)
                if TOKEN_COOKIE in parsed:
                    return parsed[TOKEN_COOKIE].value
            except http_cookies.CookieError:
                pass
        query = scope.get("query_string", b"").decode("latin-1", "ignore")
        for pair in query.split("&"):
            if pair.startswith("token="):
                from urllib.parse import unquote

                return unquote(pair[6:]) or None
        return None

    # ------------------------------------------------------------- main flow
    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket") or not self.auth.enabled:
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if path in EXEMPT_PATHS or self._is_local(scope):
            await self.app(scope, receive, send)
            return

        if self.auth.verify_token(self._extract_token(scope)):
            await self.app(scope, receive, send)
            return

        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 4401})
            return

        from starlette.responses import JSONResponse, RedirectResponse

        if path.startswith("/v1/") or scope.get("method") not in ("GET", "HEAD"):
            resp = JSONResponse(
                status_code=401,
                content={"detail": "authentication required — open /login and enter the dashboard access code"},
                headers={"WWW-Authenticate": "Bearer realm=agentguard"},
            )
        else:
            resp = RedirectResponse(url="/login?next=" + path, status_code=307)
        await resp(scope, receive, send)


# ------------------------------------------------------------------ login UI
LOGIN_PAGE_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="dark">
<title>AgentGuard · Secure Login</title>
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    min-height: 100vh; display: grid; place-items: center;
    background: radial-gradient(1200px 700px at 70% -10%, #131826 0%, #05060a 55%, #000 100%);
    font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    color: #e5e9f0; padding: 24px;
  }
  .card {
    width: min(420px, 100%);
    background: linear-gradient(180deg, #0b0d14 0%, #07080d 100%);
    border: 1px solid #1a1f2e; border-radius: 18px;
    padding: 40px 34px 30px;
    box-shadow: 0 30px 80px rgba(0,0,0,.65), 0 0 0 1px rgba(255,255,255,.02) inset;
  }
  .brand { display:flex; align-items:center; gap:12px; margin-bottom: 8px; }
  .shield {
    width: 42px; height: 42px; border-radius: 12px; display: grid; place-items: center;
    background: linear-gradient(135deg, #7c3aed, #06b6d4); font-size: 20px;
    box-shadow: 0 0 24px rgba(124,58,237,.35);
  }
  h1 { font-size: 19px; letter-spacing: .04em; }
  h1 span { color:#8b93a7; font-weight: 400; font-size: 12px; display:block; margin-top:3px; letter-spacing:.12em; text-transform:uppercase; }
  p.hint { color: #8b93a7; font-size: 12.5px; line-height: 1.6; margin: 18px 0 20px; }
  p.hint code { color: #a78bfa; }
  label { display:block; font-size: 11px; letter-spacing:.14em; text-transform:uppercase; color:#8b93a7; margin-bottom:8px; }
  input {
    width: 100%; padding: 13px 14px; font: inherit; font-size: 16px; letter-spacing: .28em;
    text-transform: uppercase; text-align: center; color: #e5e9f0;
    background: #05070c; border: 1px solid #232a3d; border-radius: 10px; outline: none;
    transition: border-color .15s ease, box-shadow .15s ease;
  }
  input:focus { border-color: #7c3aed; box-shadow: 0 0 0 3px rgba(124,58,237,.22); }
  button {
    width: 100%; margin-top: 14px; padding: 13px; border: 0; border-radius: 10px; cursor: pointer;
    font: inherit; font-size: 14px; font-weight: 700; letter-spacing: .08em;
    color: #fff; background: linear-gradient(135deg, #7c3aed, #06b6d4);
    box-shadow: 0 10px 30px rgba(124,58,237,.35);
  }
  button:disabled { opacity:.55; cursor: wait; }
  .msg { min-height: 18px; margin-top: 14px; font-size: 12.5px; text-align: center; color: #f87171; }
  .shake { animation: shake .35s ease; }
  @keyframes shake { 0%,100% { transform: translateX(0);} 25% { transform: translateX(-6px);} 75% { transform: translateX(6px);} }
  footer { margin-top: 22px; text-align: center; font-size: 11px; color:#4b5568; letter-spacing:.06em; }
</style>
</head>
<body>
  <main class="card">
    <div class="brand">
      <div class="shield">🛡️</div>
      <h1>AgentGuard<span>Runtime Firewall · Secure Access</span></h1>
    </div>
    <p class="hint">
      This dashboard is reachable from the internet through a tunnel.
      Enter the <code>random access code</code> printed in the terminal where
      AgentGuard started (or run <code>agentguard status</code> on the host machine).
    </p>
    <label for="code">Dashboard Access Code</label>
    <input id="code" inputmode="text" autocomplete="one-time-code" spellcheck="false" placeholder="••••-••••" autofocus>
    <button id="go">Unlock Dashboard</button>
    <div class="msg" id="msg"></div>
    <footer>code rotates on every service restart</footer>
  </main>
<script>
  const $ = (id) => document.getElementById(id);
  const input = $("code"), msg = $("msg"), btn = $("go");

  fetch("/v1/auth/status").then(r => r.json()).then(d => {
    if (d.authenticated) location.replace("/");
  }).catch(() => {});

  async function tryLogin() {
    const code = input.value.trim().toUpperCase();
    msg.textContent = "";
    if (!code) { msg.textContent = "Enter the access code."; return; }
    btn.disabled = true;
    try {
      const r = await fetch("/v1/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ code })
      });
      if (r.ok) { location.replace("/"); return; }
      let payload = null;
      try { payload = await r.json(); } catch {}
      let detail = (payload && payload.detail) || "Invalid access code.";
      if (r.status === 429 && payload && payload.retry_after !== undefined) {
        detail = "Too many attempts — retry in " + payload.retry_after + "s";
      }
      msg.textContent = detail;
      input.classList.remove("shake");
      void input.offsetWidth;
      input.classList.add("shake");
    } catch {
      msg.textContent = "Login request failed.";
    } finally {
      btn.disabled = false;
    }
  }
  btn.addEventListener("click", tryLogin);
  input.addEventListener("keydown", (e) => { if (e.key === "Enter") tryLogin(); });
</script>
</body>
</html>
"""
