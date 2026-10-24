"""Curated Threat-Intelligence & Security Policy Corpus (Stage 1 Data Sources).

Covers MITRE ATLAS adversarial tactics, OWASP LLM Top 10 (2025), indirect
prompt injection signatures (BIPIA), multi-hop credential exfiltration chains,
and AgentGuard runtime security policies.
"""

from __future__ import annotations

from typing import Any

SEED_DOCUMENTS: list[dict[str, Any]] = [
    {
        "doc_id": "mitre-aml-t0051-000",
        "source": "mitre_atlas",
        "title": "AML.T0051.000 — Direct Prompt Injection & System Instruction Override",
        "category": "injection",
        "severity": "critical",
        "action": "block",
        "metadata": {
            "mitre_id": "AML.T0051.000",
            "owasp_id": "LLM01:2025",
            "target_surface": "prompt",
        },
        "content": (
            "Adversaries craft direct prompt inputs designed to supersede or nullify the host agent's "
            "system prompt, developer hierarchy, or safety constraints. Common linguistic patterns include "
            "instructing the assistant to disregard prior directives, clear context memory, or adopt a new "
            "authoritative system persona.\n\n"
            "Paraphrased variants often avoid literal 'ignore previous instructions' phrasing by framing the "
            "override as a debugging session, compliance audit, emergency maintenance mode, or hypothetical "
            "sandbox where normal guardrails are suspended and raw shell or file commands must execute."
        ),
    },
    {
        "doc_id": "mitre-aml-t0051-001",
        "source": "mitre_atlas",
        "title": "AML.T0051.001 — Indirect Prompt Injection via Untrusted Tool Output",
        "category": "injection",
        "severity": "critical",
        "action": "block",
        "metadata": {
            "mitre_id": "AML.T0051.001",
            "owasp_id": "LLM01:2025",
            "target_surface": "tool_input",
        },
        "content": (
            "Indirect prompt injection embeds malicious instructions inside external data retrieved by an agent "
            "during tool execution, such as scraped web pages, GitHub issues, pull request descriptions, package "
            "READMEs, or log files. When the agent ingests the untrusted content, hidden directives hijack the "
            "control flow to invoke unauthorized shell commands or exfiltrate workspace secrets.\n\n"
            "Payloads frequently hide inside HTML comments, markdown links, zero-width unicode blocks, or fake "
            "system error messages instructing the coding agent to run curl, bash, or git config commands."
        ),
    },
    {
        "doc_id": "mitre-aml-t0048-exfil",
        "source": "mitre_atlas",
        "title": "AML.T0048 — Multi-Step Credential Harvesting & Outbound Network Exfiltration",
        "category": "exfiltration",
        "severity": "critical",
        "action": "block",
        "metadata": {
            "mitre_id": "AML.T0048",
            "owasp_id": "LLM02:2025",
            "target_surface": "tool_input",
        },
        "content": (
            "Compound exfiltration attacks split credential theft across multiple agent turns so each individual "
            "tool call appears benign in isolation. First, the agent reads sensitive local files such as .env, "
            "~/.ssh/id_rsa, ~/.aws/credentials, kubeconfig, or database configuration files.\n\n"
            "In a subsequent turn, the agent encodes or serializes those environment variables or private keys "
            "and transmits them to an external attacker-controlled endpoint using curl POST, wget, netcat, "
            "DNS tunneling, or webhook URLs."
        ),
    },
    {
        "doc_id": "mitre-aml-t0054-jailbreak",
        "source": "mitre_atlas",
        "title": "AML.T0054 — Adversarial Jailbreak & Unrestricted Persona Framing",
        "category": "jailbreak",
        "severity": "high",
        "action": "block",
        "metadata": {
            "mitre_id": "AML.T0054",
            "owasp_id": "LLM01:2025",
            "target_surface": "prompt",
        },
        "content": (
            "Jailbreak techniques coerce the model into operating as an unfiltered persona such as DAN, "
            "Developer Mode, GodMode, or an unrestricted red-team simulator that never refuses commands. "
            "Attackers combine flattery, urgent moral dilemmas, or fictional movie script framing to bypass "
            "refusal training.\n\n"
            "Once inside the persona frame, the prompt requests destructive filesystem operations, credential "
            "dumping, exploit generation, or disabling the AgentGuard circuit breaker and safety hooks."
        ),
    },
    {
        "doc_id": "owasp-llm02-secrets",
        "source": "owasp_llm",
        "title": "OWASP LLM02:2025 — Sensitive Information & API Key Disclosure",
        "category": "secret",
        "severity": "high",
        "action": "sanitize",
        "metadata": {
            "mitre_id": "AML.T0055",
            "owasp_id": "LLM02:2025",
            "target_surface": "prompt & tool_input",
        },
        "content": (
            "Prompts and tool arguments frequently leak live API tokens, AWS access keys, GitHub personal "
            "access tokens, OpenAI/Anthropic bearer keys, PEM private keys, and database connection URLs "
            "into third-party LLM provider logs.\n\n"
            "AgentGuard sanitizes inbound prompts and rewrites PreToolUse arguments in place by replacing "
            "high-entropy credentials with typed redaction markers before they leave the local machine."
        ),
    },
    {
        "doc_id": "owasp-llm06-excessive-agency",
        "source": "owasp_llm",
        "title": "OWASP LLM06:2025 — Excessive Agency, Destructive Commands & Runaway Loops",
        "category": "policy",
        "severity": "high",
        "action": "approve",
        "metadata": {
            "mitre_id": "AML.T0049",
            "owasp_id": "LLM06:2025",
            "target_surface": "tool_input",
        },
        "content": (
            "Autonomous coding agents granted shell and filesystem tools can cause irreversible damage when "
            "executing recursive deletions (rm -rf), disk formatting (mkfs, dd), forced git history rewrites "
            "(git push --force, git reset --hard), or privilege escalation (sudo, chmod 777).\n\n"
            "Additionally, stuck reasoning loops that repeatedly invoke failing tools exhaust token and dollar "
            "budgets unless halted by a stateful circuit breaker tracking iterations, token velocity, and "
            "A-B-A tool-call cycle signatures."
        ),
    },
    {
        "doc_id": "owasp-llm07-prompt-leakage",
        "source": "owasp_llm",
        "title": "OWASP LLM07:2025 — System Prompt & Internal Tool Schema Extraction",
        "category": "injection",
        "severity": "high",
        "action": "block",
        "metadata": {
            "mitre_id": "AML.T0056",
            "owasp_id": "LLM07:2025",
            "target_surface": "prompt",
        },
        "content": (
            "Prompt extraction attacks ask the agent to repeat, translate, base64-encode, or summarize the "
            "verbatim text above the user message, revealing confidential system instructions, internal MCP "
            "tool schemas, or security hook configurations.\n\n"
            "Attackers use extracted system prompt structure to craft targeted bypasses against downstream "
            "guardrails and approval policies."
        ),
    },
    {
        "doc_id": "ag-pol-001-obfuscation",
        "source": "repo_policy",
        "title": "AG-POL-001 — Encoded Payload & Shell Obfuscation Policy",
        "category": "encoded_payload",
        "severity": "medium",
        "action": "sanitize",
        "metadata": {
            "mitre_id": "AML.T0043",
            "owasp_id": "LLM01:2025",
            "target_surface": "tool_input",
        },
        "content": (
            "Attackers frequently encode malicious shell commands or prompt overrides using Base64, hex dumps, "
            "ROT13, or eval/exec subshells (such as echo <b64> | base64 -d | sh) to evade surface keyword rules.\n\n"
            "AgentGuard decodes embedded Base64 blobs recursively and re-evaluates the decoded cleartext through "
            "both deterministic regex rules and Contextual RAG similarity matching."
        ),
    },
]

SEED_KG_NODES: list[dict[str, Any]] = [
    {"id": "tactic:AML.TA0001", "kind": "tactic", "label": "MITRE ATLAS: ML Attack Staging & Prompt Hijacking", "risk_level": "critical"},
    {"id": "tactic:AML.TA0009", "kind": "tactic", "label": "MITRE ATLAS: Exfiltration via AI Agent Tooling", "risk_level": "critical"},
    {"id": "tactic:OWASP.LLM06", "kind": "tactic", "label": "OWASP LLM06: Excessive Agency & Loop Runaway", "risk_level": "high"},
    {"id": "tech:AML.T0051.000", "kind": "technique", "label": "Direct Prompt Injection Override", "risk_level": "critical"},
    {"id": "tech:AML.T0051.001", "kind": "technique", "label": "Indirect Prompt Injection (Untrusted Tool Output)", "risk_level": "critical"},
    {"id": "tech:AML.T0048", "kind": "technique", "label": "Multi-Hop Secret Harvesting & Network Exfiltration", "risk_level": "critical"},
    {"id": "tech:AML.T0054", "kind": "technique", "label": "Adversarial Persona Jailbreak", "risk_level": "high"},
    {"id": "res:sensitive_credentials", "kind": "resource", "label": "Sensitive Files (.env, SSH keys, AWS/Cloud creds)", "risk_level": "critical"},
    {"id": "res:external_network", "kind": "resource", "label": "Outbound Network Sink (curl, wget, webhook, nc)", "risk_level": "high"},
    {"id": "res:filesystem_git", "kind": "resource", "label": "Workspace Filesystem & Git History", "risk_level": "high"},
    {"id": "pol:firewall_block", "kind": "policy", "label": "AgentGuard Firewall: Block & Emit Verdict", "risk_level": "low"},
    {"id": "pol:firewall_sanitize", "kind": "policy", "label": "AgentGuard Firewall: In-Place Secret Redaction", "risk_level": "low"},
    {"id": "pol:breaker_shield", "kind": "policy", "label": "AgentGuard Circuit Breaker & Approval Gateway", "risk_level": "low"},
]

SEED_KG_EDGES: list[dict[str, Any]] = [
    {"src": "tactic:AML.TA0001", "dst": "tech:AML.T0051.000", "relation": "USES_TECHNIQUE", "weight": 1.0},
    {"src": "tactic:AML.TA0001", "dst": "tech:AML.T0051.001", "relation": "USES_TECHNIQUE", "weight": 1.0},
    {"src": "tactic:AML.TA0001", "dst": "tech:AML.T0054", "relation": "USES_TECHNIQUE", "weight": 0.9},
    {"src": "tactic:AML.TA0009", "dst": "tech:AML.T0048", "relation": "USES_TECHNIQUE", "weight": 1.0},
    {"src": "tech:AML.T0048", "dst": "res:sensitive_credentials", "relation": "TARGETS", "weight": 1.0},
    {"src": "tech:AML.T0048", "dst": "res:external_network", "relation": "EXFILTRATES_TO", "weight": 1.0},
    {"src": "res:sensitive_credentials", "dst": "res:external_network", "relation": "EXFILTRATION_PATH", "weight": 1.0},
    {"src": "tech:AML.T0051.000", "dst": "pol:firewall_block", "relation": "MITIGATED_BY", "weight": 1.0},
    {"src": "tech:AML.T0051.001", "dst": "pol:firewall_block", "relation": "MITIGATED_BY", "weight": 1.0},
    {"src": "tech:AML.T0048", "dst": "pol:firewall_block", "relation": "MITIGATED_BY", "weight": 1.0},
    {"src": "tactic:OWASP.LLM06", "dst": "res:filesystem_git", "relation": "TARGETS", "weight": 0.9},
    {"src": "tactic:OWASP.LLM06", "dst": "pol:breaker_shield", "relation": "MITIGATED_BY", "weight": 1.0},
]
