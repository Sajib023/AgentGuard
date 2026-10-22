import { useEffect, useMemo, useState } from "react";
import { api } from "./api";
import { useLiveFeed } from "./useLiveFeed";
import EventFeed from "./components/EventFeed";
import { Approvals, Breaker, FirewallDigest, ModeSwitch, Sessions, TokenChart } from "./components/Panels";
import type { ApprovalRow, BreakerSnapshot, Health, SessionRow } from "./types";

export default function App() {
  const [sessions, setSessions] = useState<SessionRow[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [snaps, setSnaps] = useState<BreakerSnapshot[]>([]);
  const [approvals, setApprovals] = useState<ApprovalRow[]>([]);

  const feed = useLiveFeed(selected);

  const refresh = () => {
    api.health().then(setHealth).catch(() => setHealth(null));
    api.sessions().then(r => {
      setSessions(r.sessions);
    }).catch(() => {});
    api.breakerAll().then(r => setSnaps(r.sessions)).catch(() => {});
    api.approvals().then(r => setApprovals(r.approvals)).catch(() => {});
  };

  // initial + regular refresh; activity pulses trigger immediate refresh
  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 4000);
    return () => clearInterval(t);
  }, []);

  useEffect(() => {
    refresh();
  }, [Math.floor(feed.pulse / 5)]);

  // Keyboard shortcut: ESC to clear session selection
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setSelected(null);
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, []);

  const selectedEvents = useMemo(
    () => (selected ? feed.events.filter(e => e.session_id === selected) : feed.events),
    [feed.events, selected]
  );

  const resolve = (id: string, approved: boolean) => {
    api.resolveApproval(id, approved).then(() => refresh()).catch(() => {});
  };

  const resetBreaker = (id: string) => {
    api.resetBreaker(id).then(() => refresh()).catch(() => {});
  };

  return (
    <div className="app">
      {/* Developer Tool AMOLED Header */}
      <header className="dev-header">
        <div className="header-left">
          <div className="brand">
            <div className="logo-hex">
              <span className="logo-text">AG</span>
            </div>
            <div className="brand-text">
              <div className="brand-name-row">
                <span className="name">AgentGuard</span>
                <span className="dev-badge-mono">DEVTOOLS</span>
                <span className="ver">v{health?.version || "0.1.0"}</span>
              </div>
              <span className="brand-sub">agent safety engine &amp; runtime telemetry</span>
            </div>
          </div>
        </div>

        <div className="header-right">
          <div className="hstat">
            {/* LLM Guard Pill */}
            <div className="tele-pill">
              <span
                className={`pill-led ${
                  health?.llm_guard === "reachable" ? "led-green" : "led-dim"
                }`}
              />
              <span className="pill-key">LLAMA-GUARD:</span>
              <span
                className={`pill-val ${
                  health?.llm_guard === "reachable" ? "text-green" : "text-muted"
                }`}
              >
                {health?.llm_guard ?? "disabled"}
              </span>
            </div>

            {/* Sessions Tracked */}
            <div className="tele-pill">
              <span className="pill-key">SESSIONS:</span>
              <span className="pill-val text-white">{sessions.length}</span>
            </div>

            {/* Uptime */}
            <div className="tele-pill">
              <span className="pill-key">UPTIME:</span>
              <span className="pill-val text-white">
                {Math.floor((health?.uptime_seconds ?? 0) / 60)}m
              </span>
            </div>

            {/* Mode Toggle Button */}
            <ModeSwitch />
          </div>
        </div>
      </header>

      {/* Main 3-Column Developer Grid */}
      <main className="dev-main">
        <aside className="sidebar-left">
          <Sessions
            sessions={sessions}
            selected={selected}
            onSelect={setSelected}
          />
          <Breaker snaps={snaps} onReset={resetBreaker} />
        </aside>

        <EventFeed
          events={selected || sessions.length === 0 ? selectedEvents : feed.events}
          connected={feed.connected}
          sessionFilter={selected}
          onClear={feed.clear}
        />

        <aside className="sidebar-right">
          <Approvals rows={approvals} onResolve={resolve} />
          <TokenChart events={selectedEvents} />
          <FirewallDigest events={selectedEvents} />
        </aside>
      </main>

      {/* Developer Status Bottom Bar */}
      <footer className="dev-footer">
        <div className="footer-left">
          <span className="footer-label">ENGINE:</span>
          <span className="text-green">READY</span>
          <span className="footer-sep">/</span>
          <span className="footer-label">FILTER:</span>
          <span className="text-cyan">
            {selected ? `SESSION (${selected.slice(0, 8)}…)` : "GLOBAL (ALL AGENTS)"}
          </span>
          {selected && (
            <button
              type="button"
              className="footer-btn"
              onClick={() => setSelected(null)}
              title="Clear session filter (Esc)"
            >
              [ESC TO RESET]
            </button>
          )}
        </div>
        <div className="footer-right">
          <span className="footer-label">FEED BUFFER:</span>
          <span className="text-white">{feed.events.length} EVENTS</span>
          <span className="footer-sep">/</span>
          <span className="footer-label">PULSE:</span>
          <span className="text-green">#{feed.pulse}</span>
        </div>
      </footer>
    </div>
  );
}
