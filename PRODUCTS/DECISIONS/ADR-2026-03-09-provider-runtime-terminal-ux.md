# ADR 2026-03-09: Provider Runtime, Registry Refresh, and Terminal UX

## Status

Accepted

## Context

NEXUS had three structural problems:

1. `core/provider_registry.json` was a static artifact that drifted from provider reality.
2. The SDK layer already had `deepseek` and `kimi`, but the runtime contract still centered on `Claude/Gemini`.
3. The terminal experience exposed too little runtime state: users could not clearly see which orchestration path, provider mode, or agent activity was happening.

We also need one explicit source of truth for the version/codename/canonical branch used by runtime, docs, and release artifacts.

## Decision

### 1. Source of Truth

- `pyproject.toml` is the canonical metadata source.
- `core/version.py` is the only runtime reader for version, codename, and canonical branch.
- Active runtime surfaces must import from `core.version` instead of hardcoding values.

### 2. Provider Registry

- `core/provider_registry.json` remains the runtime artifact consumed by config, CI, docs, and UI.
- It is not updated implicitly at boot.
- Registry mutation is an explicit maintenance action via:
  - `python scripts/refresh_provider_registry.py`
  - `python nexus7.py --refresh-provider-registry`
- Refresh uses official provider APIs where stable endpoints exist and curated fallbacks otherwise.
- This avoids boot-time nondeterminism while still removing manual hardcoding as the steady-state process.

### 3. SDK Providers

- `deepseek`, `kimi`, `openai`, and `minimax` are supported in the SDK layer.
- This does not mean the orchestration kernel is yet provider-agnostic.
- The current production contract remains:
  - core orchestration: `anthropic + google`
  - auxiliary SDK backends: `deepseek + kimi + openai + minimax`
- The next architectural step is to replace `gemini_info/claude_info` with a generic provider descriptor map across runtime, router, telemetry, and UI.

### 4. Provider Configuration UX

The target user path is:

1. Open `CEREBRO > Settings > Providers`.
2. Review current runtime posture:
   - driver mode
   - sandbox posture
   - available SDK providers
   - stale model warnings
3. Connect credentials per provider.
4. Choose defaults by role:
   - orchestration primary
   - fast/cheap fallback
   - auxiliary providers for explicit tasks
5. Run verification before activation.
6. Promote the profile to team/runtime usage.

The backend contract for this flow starts with `GET /api/settings/providers`.

### 5. Terminal UX Direction

Short term:

- keep the current REPL
- expose runtime plan at startup
- expose compact agent activity and runtime transitions during execution

Medium term:

- replace the archaic linear REPL with an event-driven TUI
- recommended stack: `Textual`

Why `Textual`:

- it is the most flexible option for a pane-based local-first terminal control plane
- it supports incremental updates, timelines, tables, logs, and keyboard-driven workflows cleanly
- it matches NEXUS better than a plain streaming prompt because NEXUS is already an evented control plane

The TUI should expose:

- orchestration mode chosen
- current phase
- live agent cards/status
- tool execution timeline
- token/output stream
- reasoning summaries, not raw chain-of-thought
- workspace/sandbox/provider posture

## Research Notes

Provider/model references:

- Anthropic models overview: <https://docs.anthropic.com/en/docs/about-claude/models/overview>
- Google Gemini models: <https://ai.google.dev/gemini-api/docs/models>
- OpenAI models guide: <https://developers.openai.com/resources/models>
- OpenAI models list API: <https://platform.openai.com/docs/api-reference/models/list>
- DeepSeek list models / pricing docs: <https://api-docs.deepseek.com/api/list-models>
- Moonshot Kimi K2 Thinking: <https://platform.moonshot.ai/docs/guide/use-kimi-k2-thinking-model>
- MiniMax text generation + OpenAI-compatible SDK: <https://platform.minimaxi.chat/docs/guides/text-generation>

Terminal UX references:

- Claude Code output styles/status line: <https://docs.anthropic.com/en/docs/claude-code/output-styles>
- Aider docs: <https://aider.chat/docs/>
- OpenCode docs: <https://opencode.ai/docs/>
- Textual / Toad AI terminal example: <https://textual.textualize.io/blog/2025/10/07/toad-ai-a-free-and-open-source-ai-coding-agent-built-with-textual/>

Existing registry-style inspiration:

- models.dev: <https://models.dev/>

## Consequences

Positive:

- provider metadata can be refreshed deliberately from real sources
- runtime/docs/versioning converge on one canonical source
- auxiliary SDK providers are now first-class at the config/factory layer
- terminal users see more of what NEXUS is doing in real time

Negative:

- orchestration is still not fully provider-generic
- pricing telemetry remains partially provider-specific and needs a dedicated follow-up
- the full TUI replacement is still ahead
