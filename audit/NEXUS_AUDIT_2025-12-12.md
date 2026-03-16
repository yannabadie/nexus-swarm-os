# NEXUS Audit – 2025-12-12

## Scope and Constraints
- Read-only sandbox; no code execution or file writes were performed during review. Tests were not run. Network access is restricted, so no web research beyond the local repository.
- Focus: core orchestration (V7 FSM + V8 Hive Mind), drivers, security layers, tool execution, and configuration.

## Architecture Snapshot
- Interactive REPL driving OrchestratorV7 (FSM) with hybrid Gemini/Claude routing plus optional Hive Mind (7-phase) for MODERATE+ tasks.
- ToolManager executes bash, read/write/edit, git, web_search, web_fetch, glob/grep, dynamic tools, and swarm_delegate; PathGuardian and ExecutionPolicy enforce some bounds.
- Drivers: Gemini (JSON strict, uses Google CLI) and Claude (hybrid XML). InputGuard/OutputGuard add prompt injection and leak detection. KERNEL hash check enforces invariants at boot/runtime. Saga checkpoints in Hive Mind.

## Strengths
- Clear modularization with heavy documentation across core, swarm/hive_mind, drivers, security, and workspace.
- Multi-layer safety intent: PathGuardian for filesystem bounds, ExecutionPolicy for command analysis, CodeValidator for dynamic tools, InputGuard/OutputGuard for prompt leak control, KERNEL integrity checks.
- Robust orchestration features: hybrid swarm modes, Hive Mind phases with retries and checkpointing (SagaManager), success memory, agent registry, telemetry hooks.
- CLI drivers include streaming, retry, and stagnation detection; tool execution uses consistent ToolResult structure.

## Findings (ordered by severity)
- CRITICAL: Gemini driver auto-approves powerful tools. `core/drivers/gemini_driver_v7.py` invokes CLI with `--approval-mode yolo` and `--allowed-tools read_file,list_directory,grep,glob,read_many_files,google_web_search,web_fetch,write_file,edit_file`. These run outside PathGuardian/ExecutionPolicy, letting the model write/edit files and reach the internet without user confirmation. Exposure: workspace compromise and code exfiltration.
- CRITICAL: Shell tool still allows arbitrary Python/network. ExecutionPolicy blocks curl/wget/etc. but not `python`, `pip`, or many interpreters; `bash` executes with shell=True for complex commands. A prompt injection can run `python -c` to read files or exfiltrate over HTTP despite blocked binaries.
- HIGH: Claude driver runs with `--dangerously-skip-permissions` (core/drivers/claude_driver_hybrid.py), removing CLI confirmation for any tool use. Combined with TOOL_USE parsing, this weakens defense-in-depth; malicious outputs can trigger ToolManager operations without user consent.
- HIGH: web_fetch is marked SAFE and usable during brainstorming. It accepts arbitrary http/https URLs, has no allowlist, and returns up to 10k chars. This enables SSRF/data exfiltration via LLM-driven requests and bypasses ExecutionPolicy.
- HIGH: Gemini CLI is granted `--include-directories` pointing to the parent NEXUS root, so the model can read code outside the workspace via CLI tools. This widens leak surface beyond the current session workspace.
- MEDIUM: InputGuard is only applied to top-level user input; tool arguments (e.g., bash, web_fetch, dynamic tool code) are not screened for injection patterns. Prompt-injected tool payloads can bypass the guardrails.
- MEDIUM: Version drift: README advertises 8.4.7/“Cyborg Hardening” while `core/config.py` defaults to 8.3.1. This creates ambiguity for telemetry, compatibility, and user expectations.
- MEDIUM: web_search uses an external `gemini` subprocess without budget/cost guardrails or timeouts beyond 90s; can blow quota silently.
- LOW: Process tracking for Gemini drivers uses global lists without locks (core/drivers/gemini_driver_v7.py), which can race under parallel swarm usage (minor leak risk).
- LOW: Dynamic tool CodeValidator is very restrictive (blocks pathlib, threading, asyncio, etc.); may hinder legitimate safe tools. Consider a balanced allowlist with tests.

## Recommendations and Fast Path to Production
### Immediate hardening (day 0-2)
1) Remove auto-approval: drop `--approval-mode yolo` and `--dangerously-skip-permissions`; route all tool use through ToolManager with explicit user approval, or restrict allowed_tools to read-only (no write/edit/web_fetch/web_search) until audited.
2) Shell egress control: block `python`, `pip`, `powershell`, `apt`, `brew`, `node`, and outbound sockets in ExecutionPolicy; enforce shell=False only, and reject any network-related flags. Add per-command allowlist.
3) Disable or allowlist web_fetch/web_search by config (default OFF). If needed, restrict to explicit domain allowlist and shorter timeouts; log every call.
4) Narrow Gemini include-directories to the active workspace or a curated read-only mirror; avoid exposing parent source tree via CLI.
5) Apply InputGuard to tool arguments and dynamic tool creation; reject high-risk patterns before ToolManager executes anything.

### Short term (week 1)
- Add budget guardrails for external CLI calls (web_search) and tie to BudgetTracker. Fail fast when cost/timeout exceeded.
- Strengthen OutputGuard actions: optionally block (not just warn) on prompt-leak detections from drivers.
- Add tests for ExecutionPolicy (python/pip, redirections, Windows paths), InputGuard on tool args, and web_fetch allowlist behavior.
- Align version strings (README/config/telemetry) and expose them via `/status`.

### Mid term (week 2-3)
- Containerize runtime with a non-root user, no egress by default, and workspace-only volume; add seccomp/AppArmor profile for subprocesses.
- Introduce a policy layer for per-tool capability profiles (read-only vs mutate vs network), overridable per state (brainstorm vs execution vs hive phases).
- Add observability: structured logs for every tool invocation (agent, args hash, duration), saga checkpoints persisted with redaction, and alerts on blocked security events.
- Provide a “safe mode” preset for production that disables evolution, dynamic tools, and write/edit until explicitly enabled.

### Vision (novative but feasible)
- Ship a dual-lane runtime: “Exploration” (full swarm/evolution with guardrails) vs “Production” (read-only, audited tool set, deterministic plan execution, cost caps). Allow seamless switch with config presets.
- Precompute project RAG indices in a sidecar service and expose a bounded read-only API to agents, reducing direct filesystem exposure.
- Add attestation for spawned agents: require KERNEL heredity stamp plus signed birth certificates stored in `.nexus/sagas`.

## Suggested Next Steps
- Approve hardening changes above, then rerun the existing 667-test suite plus new security tests.
- Pilot in a container with network egress disabled; verify common flows (/swarm, Hive Mind, dynamic tools) still work under the stricter policy.
- After stability, re-enable controlled egress (web_fetch/search) behind an allowlist and monitoring.
