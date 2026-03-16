$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path "."
Set-Location $repoRoot

$pythonScript = @'
import importlib.util
from pathlib import Path

if importlib.util.find_spec("mcp") is None:
    raise SystemExit("MCP SDK not installed. Run: python -m pip install mcp")

from core.mcp import MCPClient

client = MCPClient(command=["python", "-m", "core.mcp.server"], cwd=Path("."))
try:
    client.start()
    client.initialize()

    search = client.call_tool(
        "nexus_memory_search",
        {
            "query": "ProjectMemory evidence packs",
            "mode": "mock",
            "backend": "tfidf",
            "paths": ["core/memory/project_memory.py"],
            "limit": 3,
            "min_score": 0.0,
        },
    )
    print("Memory search result:")
    print(search.text)

    pack = client.call_tool(
        "nexus_export_evidence_pack",
        {
            "question": "How does ProjectMemory index files?",
            "mode": "mock",
            "backend": "tfidf",
            "paths": ["core/memory/project_memory.py"],
            "output_dir": "demo_companion_pack",
        },
    )
    print("Evidence pack result:")
    print(pack.text)
finally:
    client.close()
'@

$pythonScript | python -
