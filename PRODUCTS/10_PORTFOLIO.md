# Portfolio

## Method

- RICE score = (Reach x Impact x Confidence) / Effort.
- Scale: Reach 1-5, Impact 1-5, Confidence 0.4-0.8, Effort 1-5.

## Ideas (47)

### 01. NEXUS Research CLI + Evidence Pack (Audience A/B)
- User: Dev leads and analysts
- Problem: Need reproducible research outputs with traceability
- Value: CLI generates report + evidence pack artifacts
- Diff 2026: Local-first outputs, evidence hashing, mock mode
- MVP: CLI command, report.md, sources.json, trace.jsonl, manifest.sha256
- Risks: Source quality and offline parity
- Effort: 4 (high)
- RICE: R=4 I=5 C=0.70 E=4 Score=3.50

### 02. NEXUS MCP Server (Audience A)
- User: Developers integrating tools
- Problem: Need standard tool interface for agents
- Value: Expose NEXUS capabilities via MCP
- Diff 2026: Native MCP + evidence pack endpoints
- MVP: stdio MCP server with research/status/memory
- Risks: Protocol compliance and tool schema drift
- Effort: 3 (medium)
- RICE: R=5 I=4 C=0.70 E=3 Score=4.67

### 03. GitHub Action: Audit + Architecture Report (Audience A/C)
- User: Engineering and security teams
- Problem: Need repeatable repo health reports in CI
- Value: Automated audit and architecture snapshot
- Diff 2026: Uses NEXUS HiveMind + evidence pack
- MVP: Action runs doc_engine + security checks
- Risks: CI runtime and permissions
- Effort: 3 (medium)
- RICE: R=4 I=4 C=0.60 E=3 Score=3.20

### 04. NEXUS Repo Analyzer (Audience A)
- User: Maintainers
- Problem: Hard to summarize architecture quickly
- Value: One-command architecture + risks summary
- Diff 2026: Leverages existing architecture map tooling
- MVP: CLI that outputs map + key risks
- Risks: Summary quality varies by repo
- Effort: 2 (low)
- RICE: R=4 I=3 C=0.60 E=2 Score=3.60

### 05. NEXUS Eval Harness (Audience A)
- User: Platform teams
- Problem: Need regression tests for agent quality
- Value: Compare quality, cost, latency over prompts
- Diff 2026: Integrated with NEXUS telemetry
- MVP: Prompt set runner + metrics report
- Risks: Goldens drift over time
- Effort: 3 (medium)
- RICE: R=3 I=4 C=0.60 E=3 Score=2.40

### 06. NEXUS CI Agent Runner (Audience A)
- User: DevOps engineers
- Problem: Manual agent runs are inconsistent
- Value: Standardized CI entrypoint for NEXUS tasks
- Diff 2026: Budget caps and structured outputs
- MVP: CLI wrapper with config + logs
- Risks: CI secrets and environment setup
- Effort: 3 (medium)
- RICE: R=3 I=3 C=0.60 E=3 Score=1.80

### 07. NEXUS Prompt Linter (Audience A/C)
- User: Prompt authors
- Problem: Prompt injection or unsafe patterns
- Value: Static analysis of prompt safety
- Diff 2026: Uses NEXUS InputGuard patterns
- MVP: CLI scanning prompts/
- Risks: False positives
- Effort: 2 (low)
- RICE: R=3 I=3 C=0.60 E=2 Score=2.70

### 08. NEXUS Memory Indexer (Audience A/B)
- User: Teams with large repos
- Problem: RAG setup is ad-hoc
- Value: One-command memory index build
- Diff 2026: Uses ProjectMemory backends
- MVP: CLI to index docs/code
- Risks: Dependency weight for dense backend
- Effort: 2 (low)
- RICE: R=3 I=3 C=0.60 E=2 Score=2.70

### 09. NEXUS PR Review Bot (Red/Blue) (Audience A)
- User: Reviewers
- Problem: Security and correctness review is slow
- Value: Automated red/blue review summary
- Diff 2026: Built-in adversarial mode
- MVP: CLI that accepts diff input
- Risks: Review quality on large diffs
- Effort: 3 (medium)
- RICE: R=4 I=4 C=0.50 E=3 Score=2.67

### 10. NEXUS Test Impact Planner (Audience A)
- User: CI owners
- Problem: Running full tests is expensive
- Value: Suggests test subsets
- Diff 2026: Uses architecture map + diff
- MVP: CLI taking git diff -> test list
- Risks: False negatives if mapping incomplete
- Effort: 3 (medium)
- RICE: R=3 I=3 C=0.50 E=3 Score=1.50

### 11. NEXUS Release Notes Builder (Audience A)
- User: Release managers
- Problem: Manual release summaries are slow
- Value: Automated changelog + summary
- Diff 2026: Uses architecture map + commit summaries
- MVP: CLI to output release notes
- Risks: Needs git metadata
- Effort: 2 (low)
- RICE: R=3 I=2 C=0.50 E=2 Score=1.50

### 12. NEXUS Dependency Risk Report (Audience A/C)
- User: Security and platform teams
- Problem: Dependency risk hard to track
- Value: Summarized risk report
- Diff 2026: Aligned with NEXUS security policies
- MVP: Scan requirements + npm audit
- Risks: Requires vulnerability feeds
- Effort: 3 (medium)
- RICE: R=4 I=3 C=0.50 E=3 Score=2.00

### 13. NEXUS Migration Planner (Audience A)
- User: Engineers doing upgrades
- Problem: Complex upgrades lack guidance
- Value: Plan steps + risk checklists
- Diff 2026: Leverages ROADMAP and docs
- MVP: CLI that outputs migration plan
- Risks: Requires accurate project context
- Effort: 3 (medium)
- RICE: R=3 I=3 C=0.50 E=3 Score=1.50

### 14. NEXUS Architecture Map Generator (Audience A)
- User: Architects
- Problem: Architecture docs drift
- Value: Automated map generation
- Diff 2026: Extends doc_engine
- MVP: CLI wrapper around doc_engine
- Risks: Output correctness depends on parsing
- Effort: 2 (low)
- RICE: R=3 I=3 C=0.60 E=2 Score=2.70

### 15. NEXUS Toolchain Doctor (Audience A)
- User: Developers onboarding
- Problem: Setup failures are opaque
- Value: Diagnoses env/config issues
- Diff 2026: Uses bootstrap + config checks
- MVP: CLI /doctor report
- Risks: Cross-platform variance
- Effort: 2 (low)
- RICE: R=3 I=2 C=0.60 E=2 Score=1.80

### 16. NEXUS Sandbox Policy Simulator (Audience A/C)
- User: Security reviewers
- Problem: Tool permissions are hard to audit
- Value: Simulate tool allowance decisions
- Diff 2026: Exposes SandboxPolicy decisions
- MVP: CLI with path and command checks
- Risks: False sense of coverage
- Effort: 2 (low)
- RICE: R=2 I=3 C=0.50 E=2 Score=1.50

### 17. NEXUS Swarm Mode Explorer (Audience A)
- User: Developers optimizing workflows
- Problem: Mode selection is opaque
- Value: Benchmarks modes on sample tasks
- Diff 2026: Uses built-in mode executors
- MVP: CLI runner + report
- Risks: Requires stable tasks
- Effort: 2 (low)
- RICE: R=2 I=2 C=0.50 E=2 Score=1.00

### 18. NEXUS Workspace Manager CLI (Audience A)
- User: Power users
- Problem: Manual workspace switching
- Value: CLI for create/switch/archive
- Diff 2026: Wraps WorkspaceManager
- MVP: CLI commands for workspace ops
- Risks: Low differentiation
- Effort: 1 (low)
- RICE: R=2 I=2 C=0.60 E=1 Score=2.40

### 19. NEXUS Python SDK (Audience A)
- User: App developers
- Problem: Need simple API bindings
- Value: Thin client for API/MCP
- Diff 2026: Stable typed interface
- MVP: Client for CEREBRO + MCP
- Risks: API drift
- Effort: 3 (medium)
- RICE: R=4 I=3 C=0.60 E=3 Score=2.40

### 20. NEXUS API Starter Template (Audience A)
- User: Teams embedding NEXUS
- Problem: Integration setup is heavy
- Value: Reference deployment with config
- Diff 2026: Opinionated secure defaults
- MVP: Template repo with docker-compose
- Risks: Maintenance overhead
- Effort: 2 (low)
- RICE: R=3 I=2 C=0.50 E=2 Score=1.50

### 21. NEXUS Local Studio (Audience A)
- User: Developers needing UI
- Problem: No simple local UI for tasks
- Value: Minimal UI for jobs + evidence
- Diff 2026: Reuse CEREBRO
- MVP: Small UI + API job endpoints
- Risks: UI scope creep
- Effort: 4 (high)
- RICE: R=3 I=3 C=0.40 E=4 Score=0.90

### 22. NEXUS PR Evidence Export (Audience A/C)
- User: Compliance reviewers
- Problem: Need audit trails for changes
- Value: Attach evidence pack to PR
- Diff 2026: Hash + trace + logs
- MVP: CLI that exports evidence pack
- Risks: PR integration complexity
- Effort: 3 (medium)
- RICE: R=3 I=3 C=0.50 E=3 Score=1.50

### 23. Market Research Evidence Pack (Audience B)
- User: Analysts
- Problem: Need sourced reports quickly
- Value: Report + citations + trace
- Diff 2026: Reproducible evidence pack
- MVP: CLI with source list and report
- Risks: Source access limits
- Effort: 3 (medium)
- RICE: R=4 I=4 C=0.60 E=3 Score=3.20

### 24. Competitive Landscape Builder (Audience B)
- User: Consultants
- Problem: Landscape reports are time-consuming
- Value: Structured competitor matrix
- Diff 2026: Evidence-linked comparisons
- MVP: Template + evidence pack
- Risks: Data freshness
- Effort: 3 (medium)
- RICE: R=3 I=3 C=0.60 E=3 Score=1.80

### 25. Due Diligence Brief Generator (Audience B)
- User: Investors/analysts
- Problem: Need quick diligence briefs
- Value: One command brief with sources
- Diff 2026: Traceable research
- MVP: CLI outputs brief + sources.json
- Risks: Legal sensitivity
- Effort: 3 (medium)
- RICE: R=2 I=4 C=0.50 E=3 Score=1.33

### 26. Policy and Regulation Summary (Audience B/C)
- User: Compliance teams
- Problem: Tracking regs is costly
- Value: Summarized policy updates
- Diff 2026: Evidence pack + trace
- MVP: CLI summarizing documents
- Risks: Legal accuracy
- Effort: 3 (medium)
- RICE: R=3 I=4 C=0.50 E=3 Score=2.00

### 27. Workshop Research Pack (Audience B)
- User: Consultants
- Problem: Need pre-read materials fast
- Value: Pack with agenda + sources
- Diff 2026: Reusable evidence bundles
- MVP: CLI template + evidence
- Risks: Scope creep
- Effort: 2 (low)
- RICE: R=3 I=3 C=0.60 E=2 Score=2.70

### 28. Knowledge Base Distillation (Audience B)
- User: Analysts
- Problem: Too many docs
- Value: Concise synthesis with sources
- Diff 2026: RAG + evidence hashes
- MVP: Ingest docs + report
- Risks: Quality of ingestion
- Effort: 3 (medium)
- RICE: R=3 I=3 C=0.60 E=3 Score=1.80

### 29. Hypothesis Tracker (Audience B)
- User: Researchers
- Problem: Hypotheses drift without evidence
- Value: Track hypotheses with sources
- Diff 2026: Evidence pack per hypothesis
- MVP: CLI + JSON registry
- Risks: User workflow adoption
- Effort: 3 (medium)
- RICE: R=2 I=3 C=0.50 E=3 Score=1.00

### 30. Client Report Builder (Audience B)
- User: Consultants
- Problem: Client-ready reports take time
- Value: Standardized report + evidence
- Diff 2026: Source trace and manifest
- MVP: Template + export
- Risks: Output tone expectations
- Effort: 3 (medium)
- RICE: R=3 I=3 C=0.50 E=3 Score=1.50

### 31. Evidence Pack Diff (Audience B)
- User: Analysts
- Problem: Need to compare updates over time
- Value: Diff evidence packs between runs
- Diff 2026: Change tracking with hashes
- MVP: CLI to compare manifests
- Risks: Small audience
- Effort: 2 (low)
- RICE: R=2 I=2 C=0.60 E=2 Score=1.20

### 32. Multi-Source Fact Checker (Audience B)
- User: Researchers
- Problem: Hard to validate claims quickly
- Value: Cross-check claims with sources
- Diff 2026: Evidence pack per claim
- MVP: CLI with claim list
- Risks: Data access constraints
- Effort: 3 (medium)
- RICE: R=3 I=3 C=0.50 E=3 Score=1.50

### 33. Analyst RAG Pipeline (Audience B)
- User: Research teams
- Problem: Need organized RAG ingestion
- Value: Batch ingest + namespace search
- Diff 2026: Namespace manager + docling
- MVP: CLI ingest + query
- Risks: Compute heavy
- Effort: 3 (medium)
- RICE: R=3 I=3 C=0.50 E=3 Score=1.50

### 34. Tech Radar Builder (Audience B)
- User: Strategy teams
- Problem: Tech radar updates are manual
- Value: Auto-generate radar sections
- Diff 2026: Evidence-backed entries
- MVP: CLI outputs markdown
- Risks: Subjective categorization
- Effort: 2 (low)
- RICE: R=2 I=3 C=0.50 E=2 Score=1.50

### 35. ROI and Cost Estimator (Audience B)
- User: Consultants
- Problem: Need rough ROI models fast
- Value: Template models + assumptions
- Diff 2026: Links to evidence sources
- MVP: CLI generates spreadsheet
- Risks: Accuracy of assumptions
- Effort: 3 (medium)
- RICE: R=2 I=3 C=0.40 E=3 Score=0.80

### 36. Research Trace Visualizer (Audience B)
- User: Analysts
- Problem: Hard to explain research process
- Value: Visualize trace.jsonl to mermaid
- Diff 2026: Evidence pack visualization
- MVP: CLI to render mermaid
- Risks: Low adoption
- Effort: 2 (low)
- RICE: R=2 I=2 C=0.50 E=2 Score=1.00

### 37. Security Audit CLI + Evidence (Audience C)
- User: Security teams
- Problem: Need repeatable security review
- Value: Audit findings + evidence pack
- Diff 2026: Red/blue mode with trace
- MVP: CLI scanning core/security
- Risks: False positives
- Effort: 3 (medium)
- RICE: R=3 I=4 C=0.50 E=3 Score=2.00

### 38. Compliance Evidence Pack (Audience C)
- User: Compliance officers
- Problem: Need audit-ready evidence
- Value: Pack with logs + manifests
- Diff 2026: Hashing + traceability
- MVP: CLI export of logs
- Risks: Data sensitivity
- Effort: 3 (medium)
- RICE: R=3 I=4 C=0.50 E=3 Score=2.00

### 39. Prompt Injection and SSRF Scanner (Audience C)
- User: Security reviewers
- Problem: Need automated guard checks
- Value: Scan prompts and configs for risks
- Diff 2026: Uses InputGuard + SSRF rules
- MVP: CLI scan + report
- Risks: Coverage gaps
- Effort: 2 (low)
- RICE: R=3 I=3 C=0.60 E=2 Score=2.70

### 40. RBAC Policy Verifier (Audience C)
- User: Security and ops
- Problem: RBAC policies drift
- Value: Validate roles and permissions
- Diff 2026: Matches NEXUS RBAC model
- MVP: CLI checks against config
- Risks: Small scope
- Effort: 2 (low)
- RICE: R=2 I=3 C=0.50 E=2 Score=1.50

### 41. Audit Log Exporter (Audience C)
- User: Compliance teams
- Problem: Need exportable audit logs
- Value: CSV/JSON audit exports
- Diff 2026: Integrates AuditLogger
- MVP: CLI export + filters
- Risks: Data volume
- Effort: 2 (low)
- RICE: R=3 I=3 C=0.60 E=2 Score=2.70

### 42. Incident Report Generator (Audience C)
- User: Ops teams
- Problem: Incident docs are manual
- Value: Auto-generate incident report
- Diff 2026: Uses telemetry logs
- MVP: CLI report from logs
- Risks: Missing context
- Effort: 2 (low)
- RICE: R=2 I=3 C=0.50 E=2 Score=1.50

### 43. Data Handling Checklist Generator (Audience C)
- User: Compliance reviewers
- Problem: Need repeatable data handling review
- Value: Checklist with evidence links
- Diff 2026: Uses security docs and config
- MVP: CLI outputs checklist
- Risks: Subjective interpretation
- Effort: 1 (low)
- RICE: R=2 I=2 C=0.50 E=1 Score=2.00

### 44. Supply Chain Risk Report (Audience C)
- User: Security teams
- Problem: Need dependency risk assessment
- Value: Summarized risk plus evidence
- Diff 2026: Combines pip + npm audits
- MVP: CLI report
- Risks: Requires CVE feeds
- Effort: 3 (medium)
- RICE: R=3 I=3 C=0.50 E=3 Score=1.50

### 45. Privacy Posture Assessment (Audience C)
- User: Compliance teams
- Problem: Need privacy alignment snapshot
- Value: Checklist + evidence pack
- Diff 2026: Focus on local-first defaults
- MVP: CLI report
- Risks: Requires policy mapping
- Effort: 3 (medium)
- RICE: R=2 I=3 C=0.40 E=3 Score=0.80

### 46. Access Control Drift Detector (Audience C)
- User: Ops/security
- Problem: RBAC changes are not tracked
- Value: Detect role/permission drift
- Diff 2026: Compares stored snapshots
- MVP: CLI diff between RBAC exports
- Risks: Requires baseline snapshots
- Effort: 2 (low)
- RICE: R=2 I=3 C=0.40 E=2 Score=1.20

### 47. Operational Runbook Generator (Audience C)
- User: Ops teams
- Problem: Runbooks are stale
- Value: Generate runbook templates
- Diff 2026: Uses telemetry + configs
- MVP: CLI outputs runbook markdown
- Risks: May miss org-specific steps
- Effort: 2 (low)
- RICE: R=2 I=2 C=0.50 E=2 Score=1.00

## Shortlist (Top 7 by RICE)

- NEXUS MCP Server (Audience A) - Score 4.67
- NEXUS Repo Analyzer (Audience A) - Score 3.60
- NEXUS Research CLI + Evidence Pack (Audience A/B) - Score 3.50
- GitHub Action: Audit + Architecture Report (Audience A/C) - Score 3.20
- Market Research Evidence Pack (Audience B) - Score 3.20
- NEXUS Prompt Linter (Audience A/C) - Score 2.70
- NEXUS Memory Indexer (Audience A/B) - Score 2.70

## Selection

Flagship: NEXUS Research CLI + Evidence Pack
- Rationale: strong differentiation (evidence pack + local-first), multi-audience value, and direct reuse of NEXUS pipeline.
Companion: NEXUS MCP Server
- Rationale: lowest integration friction for dev teams and aligns with 2026 standardization trend.
Bonus (low effort): NEXUS Architecture Map Generator
- Rationale: reuses existing doc_engine and provides quick value with low build cost.

## Next Steps

1. Define flagship scope and outputs (report, sources, trace, manifest).
2. Implement MCP server endpoints for research, status, memory search, and evidence export.
3. Add demo scripts and tests for both products.