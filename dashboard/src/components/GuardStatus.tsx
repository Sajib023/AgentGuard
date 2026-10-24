import type { Health } from "../types";
import Icon from "./Icon";

export function guardState(health: Health | null, loading: boolean, unavailable: boolean) {
  if (loading) return { label: "Checking", tone: "neutral", description: "Checking Llama Guard status through the engine." };
  if (unavailable || !health) return { label: "Unknown", tone: "warning", description: "Engine status is unavailable. Ollama reachability has not been confirmed." };
  if (health.llm_guard === "reachable") return { label: "Online", tone: "online", description: "The configured Llama Guard model is reachable through Ollama." };
  if (health.llm_guard === "unavailable") return { label: "Unreachable", tone: "warning", description: "Llama Guard is enabled, but the engine cannot reach the configured model through Ollama." };
  if (health.llm_guard === null) return { label: "Disabled", tone: "neutral", description: "Llama Guard is disabled in the engine configuration; Ollama is not being checked." };
  return { label: "Unknown", tone: "neutral", description: "The engine has not reported a recognized Llama Guard status." };
}

export default function GuardStatus({ health, loading, unavailable, className = "" }: {
  health: Health | null; loading: boolean; unavailable: boolean; className?: string;
}) {
  const state = guardState(health, loading, unavailable);
  return <div className={`guard-status ${className}`} role="status" aria-label={`Llama Guard via Ollama: ${state.label}`} title={state.description}>
    <Icon name="shield" size={15} />
    <span>Llama Guard <span className="guard-runtime">/ Ollama</span></span>
    <span className={`guard-state ${state.tone}`}><i />{state.label}</span>
  </div>;
}
