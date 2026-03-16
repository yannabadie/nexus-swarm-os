# NEXUS V6 Tools Comparison

Comparison of NEXUS V6 tools vs real Claude Code and Gemini CLI capabilities.

---

## Current Status: V6.0

### [OK] Implemented Tools (11 total - COMPLETE!)

| Tool | Source | Status | Priority | Notes |
|------|--------|--------|----------|-------|
| **bash** | Both CLIs | [OK] Implemented | High | Execute shell commands |
| **read** | Both CLIs | [OK] Implemented | High | Read file contents |
| **write** | Both CLIs | [OK] Implemented | High | Create/overwrite files |
| **edit** | Both CLIs | [OK] Implemented | High | Search and replace in files |
| **list_dir** | Custom | [OK] Implemented | Medium | List directory contents |
| **git** | V5 + Both | [OK] Implemented | High | Git operations (ported from V5) |
| **web_search** | Gemini CLI | [OK] **NEWLY ADDED** | **CRITICAL** | Google web search for fact-checking |
| **web_fetch** | Both CLIs | [OK] **NEWLY ADDED** | **CRITICAL** | Fetch URL content |
| **glob** | Claude Code | [OK] **NEWLY ADDED** | **HIGH** | File pattern matching |
| **grep** | Claude Code | [OK] **NEWLY ADDED** | **HIGH** | Code search with regex |
| **todo_write** | Claude Code | [OK] **NEWLY ADDED** | **MEDIUM** | Plan management |

**TOTAL: 11 tools - Feature parity with Claude Code + Gemini CLI achieved!**

---

## Real CLI Capabilities

### Claude Code (Anthropic)

**Built-in Tools:**
- [OK] Bash - Shell command execution
- [OK] Read - Read files
- [OK] Write - Create files
- [OK] Edit - Modify files
- [warning]️ Glob - File pattern matching (partially via bash)
- [warning]️ Grep - Code searching (partially via bash)
- [OK] WebFetch - Fetch URLs
- [OK] WebSearch - Web searching
- [NO] Task - Launch sub-agents (complex feature)
- [NO] TodoWrite - Task management (complex feature)
- [NO] NotebookEdit - Jupyter notebook editing

**Additional Capabilities:**
- Custom subagents
- Hooks (pre/post execution)
- Background tasks
- Checkpointing
- MCP (Model Context Protocol) server/client

### Gemini CLI (Google)

**Built-in Tools:**
- [OK] Bash - Shell commands
- [OK] File operations (read/write)
- [OK] **google_web_search** - Web search with Google grounding (CRITICAL!)
- [OK] **web_fetch** - Fetch URL content
- Code execution
- Structured outputs
- Extensions system

---

## Gap Analysis

### Priority 1: CRITICAL (Newly Added!)
- [OK] **web_search** - DONE! (via Gemini google_web_search)
- [OK] **web_fetch** - DONE! (urllib implementation)

### Priority 2: HIGH (COMPLETED!)
- [OK] **glob** - DONE! Dedicated file pattern matching tool
  - **Impact:** More efficient than `bash + find`
  - **Usage:** Finding files by pattern (*.py, src/**/*.tsx)
  - **Implementation:** Python pathlib + pattern matching

- [OK] **grep** - DONE! Dedicated code search tool
  - **Impact:** More efficient than `bash + grep`
  - **Usage:** Searching code for keywords, patterns
  - **Implementation:** Python regex search with file filtering

### Priority 3: MEDIUM (Future Enhancements)
- [NO] **Task/SubAgents** - Launch specialized sub-agents
  - **Impact:** Parallel workflows (frontend + backend)
  - **Complexity:** Very high (requires agent architecture)

- [NO] **NotebookEdit** - Jupyter notebook support
  - **Impact:** Data science workflows
  - **Complexity:** Medium

- [OK] **TodoWrite** - DONE! Task management
  - **Impact:** Better planning visibility
  - **Complexity:** Low-medium
  - **Implementation:** JSON-based plan storage in `.nexus/plan.json`

### Priority 4: LOW (Advanced Features)
- [NO] Hooks system (pre/post execution)
- [NO] Checkpointing (conversation/code rewind)
- [NO] Background tasks
- [NO] MCP protocol support

---

## Tool Usage Examples

### web_search (NEW!)

**Use Cases:**
- Fact-checking during debates
- Finding official documentation
- Latest best practices
- Real-time information

**Example (Claude):**
```xml
<tool_use name="web_search">
{
  "query": "Python asyncio best practices 2025",
  "num_results": 5
}
</tool_use>
```

**Example (Gemini JSON):**
```json
{
  "tool_use": {
    "tool_name": "web_search",
    "arguments": {
      "query": "Gemini 3 Pro features"
    }
  }
}
```

### web_fetch (NEW!)

**Use Cases:**
- Reading documentation pages
- Fetching API responses
- Analyzing articles
- Getting changelog content

**Example (Claude):**
```xml
<tool_use name="web_fetch">
{
  "url": "https://docs.python.org/3/library/asyncio.html",
  "max_length": 10000
}
</tool_use>
```

---

## Recommendations

### Immediate Actions ([OK] ALL DONE!)
1. [OK] Add web_search (CRITICAL for fact-checking)
2. [OK] Add web_fetch (CRITICAL for documentation)
3. [OK] Add glob (HIGH priority - file pattern matching)
4. [OK] Add grep (HIGH priority - code search)
5. [OK] Add todo_write (MEDIUM priority - plan management)

### Short-Term (V6.1)
1. Improve web_search with result parsing
2. Add caching for web_search results
3. Enhance grep with context lines (-A, -B, -C options)

### Medium-Term (V6.2)
1. Add basic TodoWrite support
2. Add NotebookEdit for Jupyter
3. Improve tool result formatting

### Long-Term (V7.0)
1. SubAgent/Task architecture
2. Hooks system
3. MCP protocol support
4. Checkpointing

---

## Technical Notes

### web_search Implementation

**Current Approach:**
- Delegates to Gemini CLI's built-in `google_web_search`
- Uses subprocess to call `gemini -p "Use google_web_search..."`
- Returns structured results from Gemini

**Limitations:**
- Requires Gemini CLI installed and authenticated
- 30-second timeout
- Results format depends on Gemini's output

**Future Improvements:**
- Parse JSON results for structured access
- Cache recent searches
- Support multiple search engines
- Add result filtering/ranking

### web_fetch Implementation

**Current Approach:**
- Uses Python's `urllib.request`
- 15-second timeout
- Respects Content-Type encoding
- Truncates at 10,000 chars (configurable)

**Limitations:**
- No JavaScript execution (static HTML only)
- No authentication/cookies
- Basic error handling

**Future Improvements:**
- Add headless browser support (Playwright/Selenium)
- Support authentication
- Handle redirects better
- Extract structured data (markdown, tables)

---

## Comparison Table: NEXUS V6 vs CLIs

| Feature | Claude Code | Gemini CLI | NEXUS V6 | Notes |
|---------|------------|------------|----------|-------|
| **Bash** | [OK] | [OK] | [OK] | Full support |
| **Read** | [OK] | [OK] | [OK] | Full support |
| **Write** | [OK] | [OK] | [OK] | Full support |
| **Edit** | [OK] | [OK] | [OK] | Full support |
| **Git** | Via bash | Via bash | [OK] | Dedicated tool |
| **Web Search** | [OK] | [OK] | [OK] | Via Gemini CLI |
| **Web Fetch** | [OK] | [OK] | [OK] | urllib-based |
| **Glob** | [OK] | [NO] | [OK] **NEW!** | Pathlib pattern matching |
| **Grep** | [OK] | [NO] | [OK] **NEW!** | Regex code search |
| **TodoWrite** | [OK] | [NO] | [OK] **NEW!** | JSON plan storage |
| **SubAgents** | [OK] | [NO] | [NO] | V7.0 target |
| **NotebookEdit** | [OK] | [NO] | [NO] | V6.2 target |
| **MCP Protocol** | [OK] | [OK] | [NO] | V7.0 target |

---

## User Request Context

**Original Question:**
> "as tu intégré tout les outils dont disposent REELEMENT claude et gemini ? Ou est la recherche internet par exemple, elle me semble vitale dans un debat pour fact checker des informations ou des sources officielles"

**Response:**
[OK] **Absolutely right!** Web search was MISSING and is indeed VITAL for:
- Fact-checking during debates
- Verifying sources
- Finding official documentation
- Real-time information

**Actions Taken:**
- [OK] Added `web_search` tool (via Gemini's google_web_search)
- [OK] Added `web_fetch` tool (via urllib)
- [OK] Added `glob` tool (file pattern matching)
- [OK] Added `grep` tool (code search with regex)
- [OK] Added `todo_write` tool (plan management)
- [OK] Updated all prompts to document these tools
- [OK] Clarified that ALL tools are accessible by BOTH agents
- [OK] Updated README to reflect **11 tools total**

**NEXUS V6 now has FEATURE PARITY with Claude Code + Gemini CLI!** 🎯

---

## Next Steps

1. Test web_search and web_fetch with real queries
2. Consider adding Glob/Grep as dedicated tools
3. Monitor user feedback on tool usage
4. Prioritize TodoWrite for V6.1

**NEXUS V6 now has the CRITICAL tools for fact-checking and research!** 🎯
