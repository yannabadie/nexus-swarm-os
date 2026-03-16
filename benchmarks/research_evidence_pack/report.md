# Research Report

Question: How does the AsyncDriverFactory select between SDK and CLI drivers?
Mode: mock
Backend: tfidf
Generated: 2026-03-16T07:28:18.696087+00:00
Confidence: medium (0.67)
Subqueries: 6

## Research Plan
- How does the AsyncDriverFactory select between SDK and CLI drivers
- How does the AsyncDriverFactory select between SDK
- CLI drivers
- asyncdriverfactory between cli drivers sdk select
- implementation asyncdriverfactory between cli drivers sdk select
- documentation asyncdriverfactory between cli drivers sdk select

## Answer
- Supported: Implementation evidence around `AsyncDriverFactory` indicates: Defines class AsyncDriverFactory:. [S1, S2]
- Supported: Implementation evidence around `__init__` indicates: Defines def __init__(self, config: Any, workspace_path: Path | None = None):. [S3, S4]

## Verified Claims
- [CL1] (supported / high 0.86) Implementation evidence around `AsyncDriverFactory` indicates: Defines class AsyncDriverFactory:. [S1, S2]
- [CL2] (supported / medium 0.73) Implementation evidence around `__init__` indicates: Defines def __init__(self, config: Any, workspace_path: Path | None = None):. [S3, S4]
- [CL3] (weak / medium 0.52) Implementation evidence around `claude_sdk_available` indicates: Check if Claude SDK driver can be created (API key present). [S5]

## Findings
- [F1] (supported / high 0.86) Implementation evidence around `AsyncDriverFactory` indicates: Defines class AsyncDriverFactory:. [S1, S2]
- [F2] (supported / medium 0.73) Implementation evidence around `__init__` indicates: Defines def __init__(self, config: Any, workspace_path: Path | None = None):. [S3, S4]
- [F3] (weak / medium 0.52) Implementation evidence around `claude_sdk_available` indicates: Check if Claude SDK driver can be created (API key present). Evidence is still narrow or weak. [S5]

## Contradictions
- No heuristic contradictions detected among the retrieved sources.

## Sources
- [S1] core\drivers\async_factory.py (L61-68) score=0.88 queries=6
- [S2] core\drivers\async_factory.py (L1-60) score=0.85 queries=6
- [S3] core\drivers\async_factory.py (L69-124) score=0.71 queries=5
- [S4] core\drivers\async_factory.py (L149-177) score=0.69 queries=5
- [S5] core\drivers\async_factory.py (L411-415) score=0.55 queries=4

## Notes
- This report was generated in mock/local mode using on-disk project data.
- No external network calls or API keys were required.
- Retrieval uses decomposed subqueries, evidence aggregation, and deterministic claim verification heuristics.
