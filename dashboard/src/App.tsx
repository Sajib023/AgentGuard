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
      if (!selected && r.sessions.length && !selected) setSelected(null); // no auto-select
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
  }, [Math.floor(feed.pulse / 5)]);  // pulse-batched refresh

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
      <header>
        <div className="brand">
          <span className="logo">AG</span>
          <span className="name">AgentGuard</span>
          <span className="ver">{health?.version}</span>
        </div>
        <div className="hstat">
          <span className={health?.llm_guard === "reachable" ? "ok" : "warn"}>
            llama-guard: {health?.llm_guard ?? "disabled"}
          </span>
          <span>uptime {Math.floor((health?.uptime_seconds ?? 0) / 60)}m</span>
          <ModeSwitch />
        </div>
      </header>
      <main>
        <aside>
          <Sessions sessions={sessions} selected={selected} onSelect={setSelected} />
          <Breaker snaps={snaps} onReset={resetBreaker} />
        </aside>
        <EventFeed events={selected || sessions.length === 0 ? selectedEvents : feed.events}
                   connected={feed.connected} sessionFilter={selected} />
        <aside className="right">
          <Approvals rows={approvals} onResolve={resolve} />
          <TokenChart events={selectedEvents} />
          <FirewallDigest events={selectedEvents} />
        </aside>
      </main>
    </div>
  );
}
