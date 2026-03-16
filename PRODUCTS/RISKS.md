# Risks

## Open
- Git metadata missing in this workspace prevents branch creation and commits; mitigation: proceed with file changes, document needed git checkout, and request later validation in a proper clone.
- Dependency installation may fail or be slow due to large ML packages; mitigation: capture failures and provide minimal/smoke paths.
- Full pytest run may be long; mitigation: run baseline subset if needed and document gaps.
- CLI bootstrap depends on Gemini/Claude CLIs and keys; mitigation: run --verify and provide mock/offline paths where applicable.
- UI toolchain requires Node/npm; mitigation: record install or failure and provide fallback instructions.
- MCP server mode requires the optional `mcp` SDK; mitigation: document install step and keep companion tests independent of the SDK.
