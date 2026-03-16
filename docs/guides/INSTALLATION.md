# Installation Guide (NX-CG)

## Requirements
- Python 3.11+
- Optional for UI: Node.js 22+ (Cerebro)
- Optional for MCP server: `python -m pip install mcp`
- Optional for online LLM usage: configured Gemini/Claude CLIs and keys in `.env`

## Quick Install (Local)
```bash
git clone https://github.com/yannabadie/NEXUS.git
cd NEXUS
git checkout NX-CG
python -m pip install -r requirements.txt
```

Copy config:
```bash
cp .env.example .env
```

Verify:
```bash
python nexus7.py --verify
```

Run the CLI:
```bash
python nexus7.py
```

## Product Quickstarts
Flagship (research evidence pack):
```bash
python nexus_research.py "How does ProjectMemory index files?" --mode mock --path core/memory/project_memory.py
```

Companion (MCP server):
```bash
python -m pip install mcp
python -m core.mcp.server
```

## UI (Cerebro)
```bash
cd interface/ui/cerebro
npm install
npm run dev
```

## Legacy Install
The older V7 installer documentation is archived at
`docs/archive/legacy/v7/INSTALLATION_V7.md`.
