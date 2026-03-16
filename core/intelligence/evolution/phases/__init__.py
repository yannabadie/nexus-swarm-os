"""
Evolution Phases - V7.5 Phase 0a

Individual phase implementations for the evolution pipeline.
Each phase is a separate module that can be tested independently.

Phases:
1. brainstorm.py - AI-driven mutation proposal generation [IMPLEMENTED]
2. create.py - Child instance creation from mutations [IMPLEMENTED]
3. validate.py - Tiered validation dispatch (uses existing TieredValidator)
4. evaluate.py - Fitness evaluation (uses existing evaluator.py)
5. promote.py - Winner promotion and archiving [IMPLEMENTED]
"""

from .brainstorm import BrainstormPhase, run_brainstorm
from .create import CreatePhase, create_children
from .promote import PromotePhase, archive_child, promote_child

__all__ = [
    "BrainstormPhase",
    "run_brainstorm",
    "CreatePhase",
    "create_children",
    "PromotePhase",
    "promote_child",
    "archive_child",
]
