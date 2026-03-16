# Security Model

## Core Principles
- Protect kernel integrity: changes to `KERNEL.py` must update `KERNEL_HASH.txt`.
- Keep secrets out of the repo: all credentials live in `.env` or environment variables.
- Prefer local-first execution: mock/local modes avoid external calls by default.

## Execution Guards
- Tool execution is centralized in `core/execution/` with policy checks.
- MCP server limits evidence pack outputs to `WORKSPACE_PATH` and requires index paths under `NEXUS_ROOT`.
- `nexus_bash` requests are validated by the execution policy before running.

## Data Handling
- Evidence packs are deterministic and auditable (manifest + trace + metrics).
- ProjectMemory data is stored under `.nexus/` in the project root (not in `workspace`).

## Network Safety
- External calls should use timeouts and allowlists where applicable.
- CI skips LLM-network tests by default (`SKIP_LLM_TESTS=1`).

## Recommended Practices
- Rotate credentials and use least-privilege API keys.
- Run `python nexus7.py --verify` after changes that touch the kernel or config.
- Validate inputs to any new network or file-system tool before exposing it via MCP.
