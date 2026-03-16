"""
NEXUS V7.5 HIVE MIND - Prompt Loader Module

Handles loading and assembling prompts with include directives.
V12.4: Added versioned prompt registry for version tracking, diff, and rollback.
"""

from .prompt_loader import load_prompt, resolve_includes

# V12.4: Prompt Template Optimizer
from .template_optimizer import (
    ConflictResult,
    PromptAnalysis,
    PromptIssue,
    PromptOptimizer,
    PromptOutcome,
    PromptStats,
    get_optimizer,
    reset_optimizer,
)

# V12.4: Versioned Prompt Registry
from .versioned_registry import PromptEntry, PromptRegistry, PromptVersion

__all__ = [
    "load_prompt",
    "resolve_includes",
    # V12.4: Versioned Registry
    "PromptRegistry",
    "PromptVersion",
    "PromptEntry",
    # V12.4: Prompt Template Optimizer
    "PromptOptimizer",
    "PromptAnalysis",
    "PromptIssue",
    "PromptStats",
    "PromptOutcome",
    "ConflictResult",
    "get_optimizer",
    "reset_optimizer",
]
