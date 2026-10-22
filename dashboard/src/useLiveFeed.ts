import { useEffect, useRef, useState } from "react";
import type { AgentEvent, WsMessage } from "./types";
import { api, wsUrl } from "./api";

/** Live WS feed with auto-reconnect + exponential backoff, plus a REST
 * backfill poll so the feed survives WS gaps: if the socket dies (server
 * restart, tab suspend, proxy hiccup) or silently stalls, the newest rows
 * are still merged in every few seconds from /v1/events — the symptom
 * "agent logs are not synced" came from the feed trusting only the WS. */
const BACKFILL_MS = 5000;
const FEED_MAX = 600;
const REPLAY = 150;

export function useLiveFeed(selected: string | null) {
  const [events, setEvents] = useState<AgentEvent[]>([]);
  const [connected, setConnected] = useState(false);
  const [pulse, setPulse] = useState(0);
  const ref = useRef<WebSocket | null>(null);
  const attempt = useRef(0);
  const selectedRef = useRef(selected);
  selectedRef.current = selected;
  // Shared dedup set: WS and REST both insert; REST backfill must never
  // duplicate rows the socket already delivered (or vice versa).
  const seenIds = useRef<Set<string>>(new Set());

  useEffect(() => {
    // session filter changed → rebuild the feed and the dedup set
    seenIds.current = new Set();
    setEvents([]);
    let dead = false;
    let timer: ReturnType<typeof setTimeout>;
    let poll: ReturnType<typeof setInterval> | undefined;

    const backfill = async () => {
      try {
        const r = await api.events({
          session_id: selectedRef.current ?? undefined,
          limit: 80,
          order: "desc",
        });
        const unseen = (r.events as AgentEvent[]).filter(
          e => !seenIds.current.has(e.id));
        if (dead || unseen.length === 0) return;
        unseen.forEach(e => seenIds.current.add(e.id));
        setEvents(prev => {
          const merged = [...unseen, ...prev];
          merged.sort((a, b) => b.ts - a.ts); // newest first, stable
          return merged.slice(0, FEED_MAX);
        });
        setPulse(p => p + 1);
      } catch {
        // service down; the WS retry loop handles visibility
      }
    };

    const accept = (e: AgentEvent) => {
      if (seenIds.current.has(e.id)) return;
      seenIds.current.add(e.id);
      setEvents(prev => [e, ...prev].slice(0, FEED_MAX));
    };

    const open = () => {
      if (dead) return;
      const ws = new WebSocket(wsUrl(selectedRef.current, REPLAY));
      ref.current = ws;
      ws.onopen = () => {
        attempt.current = 0;
        setConnected(true);
        void backfill(); // catch up on rows missed during the outage
      };
      ws.onmessage = (m) => {
        let msg: WsMessage;
        try {
          msg = JSON.parse(m.data);
        } catch {
          return;
        }
        if (msg.kind === "event" && msg.event) {
          accept(msg.event as AgentEvent);
          setPulse(p => p + 1);
        } else if (msg.kind === "breaker" && msg.meta && (msg.meta as any).approval) {
          setPulse(p => p + 1);
        }
      };
      ws.onclose = () => {
        setConnected(false);
        const delay = Math.min(8000, 500 * 2 ** attempt.current++);
        if (!dead) timer = setTimeout(open, delay);
      };
      ws.onerror = () => ws.close();
    };

    void backfill(); // initial history (REST always succeeds if served)
    open();
    poll = setInterval(backfill, BACKFILL_MS);

    return () => {
      dead = true;
      clearTimeout(timer);
      if (poll) clearInterval(poll);
      ref.current?.close();
    };
  }, [selected]);

  const clear = () => {
    setEvents([]);
    seenIds.current = new Set();
  };
  return { events, connected, pulse, clear };
}
