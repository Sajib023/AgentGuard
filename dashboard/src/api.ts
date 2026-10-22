import type { ApprovalRow, BreakerSnapshot, Health, SessionRow } from "./types";

const BASE = "/v1";

async function j<T>(res: Response): Promise<T> {
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json() as Promise<T>;
}

export const api = {
  health: () => fetch(`${BASE}/healthz`).then(j<Health>),
  sessions: () => fetch(`${BASE}/sessions`).then(r => j<{ sessions: SessionRow[] }>(r)),
  events: (q: Record<string, string | number | undefined> = {}) => {
    const usp = new URLSearchParams();
    Object.entries(q).forEach(([k, v]) => v !== undefined && usp.set(k, String(v)));
    return fetch(`${BASE}/events?${usp}`).then(r => j<{ events: any[] }>(r));
  },
  breakerAll: () => fetch(`${BASE}/breaker/status`).then(r => j<{ sessions: BreakerSnapshot[] }>(r)),
  approvals: () => fetch(`${BASE}/approvals`).then(r => j<{ approvals: ApprovalRow[] }>(r)),
  resolveApproval: (id: string, approved: boolean) =>
    fetch(`${BASE}/approvals/${id}/resolve`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ approved, by: "dashboard" }),
    }).then(j<any>),
  setMode: (mode: "enforce" | "observe") =>
    fetch(`${BASE}/config/mode`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mode }),
    }).then(j<any>),
  resetBreaker: (sid: string) =>
    fetch(`${BASE}/breaker/reset/${sid}`, { method: "POST" }).then(j<any>),
};

export function wsUrl(sessionId?: string | null, replay = 200): string {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const p = new URLSearchParams({ replay: String(replay) });
  if (sessionId) p.set("session_id", sessionId);
  return `${proto}://${location.host}/v1/ws?${p}`;
}
