# Utils Module

## Synopsis
The Utils module provides utility functions and classes for NEXUS including JSON extraction/serialization, artifact verification, atomic file storage, stream parsing, and async utilities. These are shared utilities used across multiple NEXUS components for robust data handling and file operations.

## Component Map
| File | Purpose | Key Exports |
|------|---------|-------------|
| `json_extractor.py` | Robust JSON extraction from LLM responses with multiple fallback strategies | `extract_json()`, `extract_json_objects()`, `find_json_block()`, `repair_json()` |
| `serialization.py` | Custom JSON encoder for NEXUS types (Path, datetime, dataclasses, etc.) | `NexusJSONEncoder`, `to_json()`, `from_json()`, `safe_json_dumps()` |
| `artifact_verifier.py` | Verify agent-produced artifacts (files, Python syntax, JSON validity) | `ArtifactVerifier` |
| `atomic_store.py` | Thread-safe atomic JSON file persistence | `AtomicJsonStore`, `AtomicJsonStoreManager` |
| `stream_parser.py` | Parse streaming LLM responses (tool calls, text, JSON) | `extract_tool_call()`, `parse_streaming_chunk()`, `detect_tool_boundary()`, etc. |
| `async_utils.py` | Async utility functions (V8.4.4a) | `run_in_executor()`, `gather_with_limit()`, `timeout_after()` |
| `__init__.py` | Module initialization | Empty |

## Key Interfaces

### JSON Extraction

**`extract_json(text: str, strict: bool = False) -> Optional[Dict]`**
- Extract first JSON object from text (handles markdown code blocks, etc.)
- Multiple fallback strategies: regex search, quote repair, truncation
- Returns None if extraction fails

**`extract_json_objects(text: str) -> List[Dict]`**
- Extract all JSON objects from text
- Useful for parsing multiple tool calls or responses

**`find_json_block(text: str) -> Optional[str]`**
- Find JSON block within markdown code fences

**`repair_json(text: str) -> str`**
- Attempt to repair malformed JSON (unclosed quotes, brackets, etc.)

### JSON Serialization

**`NexusJSONEncoder(json.JSONEncoder)`**
- Custom JSON encoder supporting NEXUS types
- Handles: `Path`, `datetime`, `UUID`, `Enum`, `dataclass`, `set`, `bytes`

**`to_json(obj: Any) -> str`**
- Serialize object to JSON string with NexusJSONEncoder

**`from_json(json_str: str) -> Any`**
- Deserialize JSON string to Python object

**`safe_json_dumps(obj: Any, default: str = "{}") -> str`**
- Safe JSON serialization with fallback on error

### Artifact Verification

**`ArtifactVerifier`**
- Verify agent-produced files for correctness
- Checks: File existence, Python syntax, JSON validity

**Key Methods:**
- `verify_from_content(content: str) -> Tuple[bool, List[str], List[str]]`: Extract and verify all file references from content
- Returns: (all_valid, verified_files, errors)

### Atomic JSON Storage

**`AtomicJsonStore`**
- Thread-safe atomic JSON file persistence
- Prevents corruption from concurrent access or crashes
- Write-to-temp + atomic rename pattern

**Key Methods:**
- `load() -> Dict[str, Any]`: Load JSON (raises if file doesn't exist)
- `load_safe(default: Optional[Dict] = None) -> Dict`: Load with default fallback
- `save(data: Dict[str, Any])`: Atomically save JSON
- `update(updates: Dict[str, Any]) -> Dict`: Read-modify-write with locking
- `delete() -> bool`: Delete file

**`AtomicJsonStoreManager`**
- Singleton manager for AtomicJsonStore instances
- Ensures single instance per file path

### Stream Parsing

**`extract_tool_call(chunk: str) -> Optional[Dict]`**
- Extract tool call from streaming chunk

**`parse_streaming_chunk(chunk: str, buffer: str) -> Tuple[Optional[Dict], str]`**
- Parse streaming chunk, return tool call if complete + updated buffer

**`detect_tool_boundary(text: str) -> Optional[int]`**
- Detect where tool call ends in streaming text

### Async Utilities (V8.4.4a)

**`run_in_executor(func: Callable, *args) -> Any`**
- Run sync function in thread pool executor

**`gather_with_limit(tasks: List[Coroutine], limit: int) -> List[Any]`**
- Run tasks with concurrency limit (semaphore-based)

**`timeout_after(seconds: float, coro: Coroutine) -> Any`**
- Run coroutine with timeout

## Dependencies & Integration

### Internal Dependencies
- `pathlib` - Path handling
- `json` - JSON parsing/serialization
- `re` - Regex for extraction
- `ast` - Python syntax validation
- `threading` - Locks for thread safety
- `asyncio` - Async utilities
- `dataclasses` - Dataclass inspection

### Integration Points
- **Drivers**: Use JSON extraction for parsing LLM responses
- **Synapse**: Uses NexusJSONEncoder for message serialization
- **Memory**: Uses AtomicJsonStore for blackboard persistence
- **ExecutionEngine**: Uses ArtifactVerifier to validate tool results
- **Streaming**: Uses stream parser for real-time tool call detection

### Usage Examples

```python
from core.utils.json_extractor import extract_json, extract_json_objects
from core.utils.serialization import to_json, NexusJSONEncoder
from core.utils.artifact_verifier import ArtifactVerifier
from core.utils.atomic_store import AtomicJsonStore
from pathlib import Path

# Extract JSON from LLM response
response = "Here's the data:\\n```json\\n{\"tool\": \"read\", \"args\": {}}\\n```"
data = extract_json(response)
print(data)  # {"tool": "read", "args": {}}

# Extract multiple JSON objects
text = "{\"a\": 1} some text {\"b\": 2}"
objects = extract_json_objects(text)
print(objects)  # [{"a": 1}, {"b": 2}]

# Serialize with custom encoder
from datetime import datetime
data = {"timestamp": datetime.now(), "path": Path("/tmp/file.txt")}
json_str = to_json(data)

# Verify artifacts
verifier = ArtifactVerifier(Path("workspace"))
content = "I created src/main.py with the following code:\\n```python\\nprint('hello')\\n```"
all_valid, verified, errors = verifier.verify_from_content(content)

# Atomic JSON store
store = AtomicJsonStore(Path("workspace/state.json"))

# Save data atomically
store.save({"counter": 0, "status": "active"})

# Update with locking
updated = store.update({"counter": 1})

# Load safely with default
data = store.load_safe(default={"counter": 0})
```

## Design Notes

- **Robust Extraction**: Multiple fallback strategies for malformed JSON
- **Thread Safety**: AtomicJsonStore prevents corruption from concurrent access
- **Type Support**: NexusJSONEncoder handles all NEXUS-specific types
- **Atomic Writes**: Write-to-temp + rename prevents partial writes
- **Stream Handling**: Real-time parsing of streaming LLM responses
- **Validation**: Python and JSON syntax checking for agent artifacts
