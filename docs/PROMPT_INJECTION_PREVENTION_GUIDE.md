# Prompt Injection Prevention Guide for NEXUS

**Date**: 2025-12-11
**Source**: Research agent (AWS, Azure, OWASP)
**Target**: NEXUS V8.8+ Security Hardening

---

## Executive Summary

Based on research from AWS Bedrock Guardrails, Azure Prompt Shields, and OWASP LLM Top 10 2025, this guide provides concrete implementation patterns for prompt injection prevention in NEXUS.

---

## 1. Key Industry Patterns (2025)

### AWS Bedrock Guardrails
- **Prompt Attack Filter Levels**: None, Low, Medium, High
- **Indirect Prompt Injection Protection**: Tag dynamically generated content as user input
- **Code Domain Protection**: Detect threats in code across 12 programming languages

### Azure Prompt Shields
- **Spotlighting Technique**: Mark untrusted data via base64 encoding (datamarking)
- **Detection API**: Unified API for direct (jailbreaks) and indirect attacks

### OWASP LLM Top 10 2025
- **LLM01**: Prompt Injection still #1 risk
- **Key mitigations**: Privilege control, human-in-the-loop, semantic filters

---

## 2. Recommended Implementation

### 2.1 InputGuard (Layer 1)

```python
# core/security/input_guard.py

INJECTION_PATTERNS = {
    "instruction_override": {
        "patterns": [
            r"ignore\s+(previous|all|prior)\s+(instruction|command|rule)",
            r"bypass\s+(rule|policy|restriction|security)",
        ],
        "level": ThreatLevel.CRITICAL,
    },
    "role_manipulation": {
        "patterns": [
            r"you\s+are\s+now\s+(a|an)\s+",
            r"(DAN|developer\s+mode|jailbreak)\s+mode",
        ],
        "level": ThreatLevel.CRITICAL,
    },
}

class InputGuard:
    def validate_user_input(self, text: str) -> InputValidationResult:
        # 1. Regex fast filter
        # 2. Sanitization (normalize unicode, remove null bytes)
        # 3. Risk scoring
        pass
```

### 2.2 Spotlighter (Layer 2 - RAG Protection)

```python
# core/memory/spotlighting.py

class Spotlighter:
    def spotlight_with_base64(self, content: str) -> SpotlightedContent:
        """Apply datamarking to untrusted RAG content."""
        encoded = base64.b64encode(content.encode()).decode()
        return f"<UNTRUSTED_BASE64>{encoded}</UNTRUSTED_BASE64>"
```

### 2.3 OutputGuard (Layer 3)

```python
# core/security/output_guard.py

class OutputGuard:
    PROMPT_LEAK_PATTERNS = [
        r"you\s+are\s+a\s+(helpful|ai|assistant)",
        r"your\s+(role|purpose|instruction)\s+is",
    ]

    def validate_output(self, llm_output: str) -> OutputValidationResult:
        # Check for system prompt leakage
        # Validate groundedness (RAG Triad)
        pass
```

---

## 3. Defense-in-Depth Architecture

```
Layer 1: InputGuard      -> Regex filter + sanitization
Layer 2: Spotlighter     -> Base64 encode RAG content
Layer 3: Secure Prompts  -> Trust boundaries in prompts
Layer 4: ExecutionPolicy -> Command validation (existing)
Layer 5: OutputGuard     -> Prompt leak detection
Layer 6: Monitoring      -> Security event logging
```

---

## 4. Integration Points

| Module | Integration |
|--------|-------------|
| FSM Orchestrator | Add InputGuard in BRAINSTORMING state |
| RAG Memory | Apply Spotlighter to retrieved documents |
| Agent Spawning | Use SpawnPromptValidator + InputGuard |
| Tool Execution | Existing ExecutionPolicy + OutputGuard |

---

## 5. Configuration

```bash
# .env
SECURITY_INPUT_GUARD=True
SECURITY_OUTPUT_GUARD=True
SECURITY_RAG_SPOTLIGHTING=True
SECURITY_SPOTLIGHTING_TECHNIQUE=base64
SECURITY_BLOCK_THRESHOLD=0.7
```

---

## Sources

- [AWS Bedrock Guardrails](https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-prompt-attack.html)
- [Azure Prompt Shields](https://learn.microsoft.com/en-us/azure/ai-services/content-safety/concepts/jailbreak-detection)
- [OWASP LLM01:2025 Prompt Injection](https://genai.owasp.org/llmrisk/llm01-prompt-injection/)
- [OWASP Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/LLM_Prompt_Injection_Prevention_Cheat_Sheet.html)
