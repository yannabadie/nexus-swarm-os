# NEXUS Memory Ingestors Module

## Synopsis

The **ingestors** module (part of V13.0 MEMORIA UNIVERSALIS) provides the UniversalIngestor system for processing diverse content types into the NEXUS memory system. It handles automatic format detection and conversion for text, code, documents, and structured data.

## Architecture

```
+-------------------------------------------------------------------------+
|                      INGESTOR ARCHITECTURE                               |
+-------------------------------------------------------------------------+
|                                                                          |
|  +------------------------------------------------------------------+   |
|  |                    UniversalIngestor                              |   |
|  |              Auto-detect and process content                      |   |
|  +----------------------------+-------------------------------------+   |
|                               |                                          |
|         +---------------------+-------------------------------------+   |
|         |           |         |         |           |               |   |
|         v           v         v         v           v               |   |
|  +----------+ +----------+ +------+ +------+ +----------+          |   |
|  |   Text   | |   Code   | | JSON | | YAML | | Markdown |          |   |
|  | Ingestor | | Ingestor | |      | |      | |          |          |   |
|  +----------+ +----------+ +------+ +------+ +----------+          |   |
|                               |                                          |
|                               v                                          |
|  +------------------------------------------------------------------+   |
|  |                    ProjectMemory (RAG)                            |   |
|  |              Store as embeddings + metadata                       |   |
|  +------------------------------------------------------------------+   |
|                                                                          |
+-------------------------------------------------------------------------+
```

## Supported Formats

| Format | Extension | Ingestor |
|--------|-----------|----------|
| Plain Text | `.txt` | TextIngestor |
| Markdown | `.md` | MarkdownIngestor |
| Python | `.py` | CodeIngestor |
| JavaScript | `.js`, `.ts` | CodeIngestor |
| JSON | `.json` | JSONIngestor |
| YAML | `.yaml`, `.yml` | YAMLIngestor |
| PDF | `.pdf` | PDFIngestor (optional) |
| HTML | `.html` | HTMLIngestor |

## Key Interfaces

### UniversalIngestor
```python
class UniversalIngestor:
    """Auto-detect and ingest diverse content."""

    def ingest(
        self,
        content: Union[str, bytes, Path],
        metadata: Optional[Dict] = None
    ) -> IngestResult

    def ingest_file(self, path: Path) -> IngestResult
    def ingest_directory(self, path: Path, recursive: bool = True) -> List[IngestResult]
    def detect_format(self, content: Union[str, bytes]) -> ContentFormat
```

### IngestResult
```python
@dataclass
class IngestResult:
    success: bool
    format: ContentFormat
    chunks: List[ContentChunk]
    metadata: Dict[str, Any]
    errors: List[str]
```

### ContentChunk
```python
@dataclass
class ContentChunk:
    content: str
    embedding: Optional[List[float]]
    metadata: Dict[str, Any]
    source: str
    chunk_index: int
```

## Usage

```python
from core.memory.ingestors import UniversalIngestor

ingestor = UniversalIngestor()

# Ingest a file
result = ingestor.ingest_file(Path("src/main.py"))

# Ingest raw content
result = ingestor.ingest("Hello world", metadata={"source": "user_input"})

# Ingest directory
results = ingestor.ingest_directory(Path("docs/"), recursive=True)
```

## Configuration

```python
ingestor = UniversalIngestor(
    chunk_size=1000,          # Characters per chunk
    chunk_overlap=100,        # Overlap between chunks
    embedding_model="text-embedding-ada-002",
    supported_formats=["txt", "md", "py", "json"]
)
```

## Dependencies

### Internal
- `core.memory.project_memory` - RAG storage
- `core.memory.embeddings` - Embedding generation

### External
- `tiktoken` - Token counting
- `pypdf` - PDF parsing (optional)
- Standard library

## Version History

- **V13.0** - MEMORIA UNIVERSALIS: Initial UniversalIngestor
- **V12.4** - Chunk optimization, metadata enhancement
