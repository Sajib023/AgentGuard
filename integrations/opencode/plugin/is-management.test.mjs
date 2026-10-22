// Sanity tests for the management escape-hatch matcher in the real plugin.
import { isManagementText } from "./agentguard-plugin.js";

const MUST_PASS = [
  `{"command":"curl -s -X POST http://127.0.0.1:8907/v1/breaker/reset/ses_x"}`,
  `{"command":"curl -X POST http://localhost:8907/v1/breaker/limits -d '{...}'"}`,
  `{"command":"curl -s http://127.0.0.1:8907/v1/approvals"}`,
  `{"command":".venv/bin/agentguard stop"}`,
  `{"command":"agentguard doctor"}`,
  `{"command":"/home/sajib/AgentGuard/.venv/bin/agentguard serve --port 8907"}`,
  `{"command":"nohup bash -c 'curl ...8907/v1/config/mode ...'"}`,
];

const MUST_FAIL = [
  `{"command":"curl -s https://example.com/api"}`,
  `{"command":"rm -rf /"}`,
  `{"command":"grep 'breaker' docs.md"}`,            // mentions word only
  `{"command":"cat src/main.py && make test"}`,
  `{"file_path":"/tmp/x.py","content":"use tool_call semantics"}`,
  ``,
];

let fail = 0;
for (const t of MUST_PASS) {
  if (!isManagementText(t)) { console.error("FAIL should-match:", t); fail++; }
}
for (const t of MUST_FAIL) {
  if (isManagementText(t)) { console.error("FAIL should-NOT-match:", t); fail++; }
}
if (fail) { console.error(`${fail} mismatches`); process.exit(1); }
console.log("all escape-hatch matcher cases pass");
