export type EventKind =
  | "session_start" | "session_end"
  | "prompt_before" | "prompt_after" | "firewall_verdict"
  | "tool_call" | "llm_call" | "state_change" | "graph_event" | "error"
  | "breaker_alert" | "breaker_stop"
  | "approval_request" | "approval_decision";

export interface AgentEvent {
  id: string;
  ts: number;
  agent: string;
  session_id: string;
  type: EventKind;
  parent_event_id?: string | null;
  data: Record<string, any>;
}

export interface SessionRow {
  session_id: string;
  agent: string;
  first_ts: number;
  last_ts: number;
  end_ts: number | null;
  model: string | null;
  cwd?: string | null;
  pid: number | null;
  prompt_count: number;
  tool_calls: number;
  llm_calls: number;
  tokens: number;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
  iteration: number;
}

export interface BreakerSnapshot {
  session_id: string;
  agent: string;
  status: "healthy" | "warning" | "breached" | "stopped";
  usage: {
    iterations: number; llm_calls: number; tool_calls: number;
    input_tokens: number; output_tokens: number; cost_usd: number;
    wall_seconds: number; consecutive_tool_errors: number;
  };
  limits: Record<string, number>;
  started_ts: number;
}

export interface ApprovalRow {
  id: string;
  session_id: string;
  agent: string;
  metric: string | null;
  value: number | null;
  limit: number | null;
  reason: string;
  created_ts: number;
}

export interface Health {
  status: string; version: string; uptime_seconds: number;
  sessions_tracked: number; llm_guard: string | null; observe_mode: boolean;
  rag_chunks?: number; mcp_servers?: number;
}

export interface RAGHit {
  chunk_id: string;
  doc_id: string;
  source: string;
  title: string;
  category: string;
  severity: string;
  action: string;
  context_prefix: string;
  chunk_text: string;
  dense_score: number;
  colbert_maxsim: number;
  hybrid_score: number;
  metadata?: Record<string, any>;
}

export interface RAGStatus {
  status: string;
  documents_indexed: number;
  contextual_chunks: number;
  kg_nodes: number;
  kg_edges: number;
  categories: Record<string, number>;
  techniques: Record<string, any>;
}

export interface MCPStatus {
  protocol_version: string;
  transports_supported: string[];
  built_servers: Array<{
    id: string;
    name: string;
    transports: string[];
    tools: Array<{ name: string; description: string }>;
  }>;
  external_servers: Array<{
    id: string;
    package: string;
    transport: string;
    role: string;
    status: string;
  }>;
  counts: {
    built_servers: number;
    external_servers: number;
    total_tools: number;
    total_resources: number;
  };
}

export interface WsMessage {
  kind: "event" | "breaker" | "pong" | "error";
  event?: AgentEvent;
  meta?: Record<string, unknown>;
  detail?: string;
}
