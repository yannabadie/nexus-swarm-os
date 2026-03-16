# Repository Guidelines

## Project Structure & Module Organization
- `nexus7.py` is the main CLI entrypoint for local runs and verification.
- `core/` contains the orchestrator, memory, swarm, API, MCP server, and security layers.
- `interface/ui/cerebro/` hosts the React 19 + TypeScript UI (Vite + Tailwind).
- `tests/` is the Python test suite; UI tests live in `interface/ui/cerebro/tests/` with `e2e/` for Playwright.
- `docs/`, `prompts/`, `audit/`, and `memory-bank/` store documentation, prompts, audits, and context templates.
- `scripts/` contains utilities and demos; `PRODUCTS/` stores delivery logs, ADRs, and product docs.

## Build, Test, and Development Commands
Backend (Python 3.11+):
```bash
python -m pip install -r requirements.txt
python nexus7.py --verify
python nexus7.py
python nexus_research.py "Question" --mode mock --path core/memory/project_memory.py
python -m pytest tests/ -v
uvicorn core.api.cerebro.app:create_cerebro_app --factory --port 8080
python -m core.mcp.server
powershell -ExecutionPolicy Bypass -File scripts/demo_flagship.ps1
powershell -ExecutionPolicy Bypass -File scripts/demo_companion.ps1
```

Frontend (Cerebro UI):
```bash
cd interface/ui/cerebro
npm install
npm run dev
npm run build
npm test
npx playwright test
npm run lint
```

## Coding Style & Naming Conventions
- Python follows PEP 8 and uses type hints extensively; keep signatures typed and use f-strings.
- Naming: `snake_case` for Python functions/vars/files, `PascalCase` for classes, `UPPER_CASE` for constants.
- React components use `PascalCase` files (e.g., `LoginForm.tsx`); hooks use `useX.ts` (e.g., `useWebSocket.ts`).

## Testing Guidelines
- Python: `pytest` + `pytest-asyncio`; pattern `tests/test_*.py` and category folders like `tests/api/`.
- UI: Vitest for `interface/ui/cerebro/tests/*.test.tsx`; Playwright for `interface/ui/cerebro/e2e/*.spec.ts`.
- No explicit coverage target is documented; add unit + smoke tests for new behavior.

## Commit & Pull Request Guidelines
- Git history is not available in this workspace, so prior conventions could not be verified.
- Follow Conventional Commits: `feat:`, `fix:`, `docs:`, `test:`, `refactor:`, `chore:`.
- PRs should include a concise scope summary, test results, linked issues when relevant, and UI screenshots for `interface/ui/cerebro` changes.
- If you modify `KERNEL.py`, update `KERNEL_HASH.txt` and explain the change in the PR description.

## Security & Configuration Tips
- Start from `.env.example`; never commit secrets or API keys.
- Keep runtime data under `WORKSPACE_PATH` (default `./workspace`) and validate network inputs with timeouts/allowlists.

## Product Delivery Logs
- Maintain `PRODUCTS/PROGRESS_LOG.md`, `PRODUCTS/RISKS.md`, and ADRs under `PRODUCTS/DECISIONS/`.
- Demo scripts should live in `scripts/demo_flagship.*` and `scripts/demo_companion.*` once products ship.
