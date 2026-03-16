# Troubleshooting

## CLI Verify Fails
- Run `python nexus7.py --verify` to surface missing dependencies or config.
- Ensure `.env` exists and matches `.env.example` (no real keys committed).
- If CLI tools are missing, set `GEMINI_CLI_PATH` or `CLAUDE_CLI_PATH` in `.env`.

## Research CLI Returns No Sources
- Provide explicit paths with `--path` (repeatable) to ensure files are indexed.
- Lower the threshold: `--min-score 0.0` for a broad match.
- Use the mock backend for offline runs: `--mode mock --backend tfidf`.

## MCP Server Won't Start
- Install MCP SDK: `python -m pip install mcp`.
- Start manually: `python -m core.mcp.server`.
- If tools return errors, confirm paths are under `NEXUS_ROOT` and outputs under `WORKSPACE_PATH`.

## UI Build Issues (Cerebro)
- From `interface/ui/cerebro`: run `npm install` then `npm run dev`.
- If Playwright fails: `npx playwright install`.

## Tests Are Slow or Fail in CI
- Use targeted runs: `python -m pytest tests/test_research_cli.py -v`.
- Set `SKIP_LLM_TESTS=1` to avoid external API calls.
