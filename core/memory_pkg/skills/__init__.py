"""
NEXUS V12.4 - Skills Module

Auto-crystallization of repeated tool sequences into reusable skills.

Components:
- crystallizer.py: Pattern detection and skill generation
"""

from .crystallizer import (
    CrystallizedSkill,
    SkillCrystallizer,
    ToolCallRecord,
    ToolSequencePattern,
    get_crystallizer,
    reset_crystallizer,
)
from .experience_distiller import (
    DistillationResult,
    DistillerStats,
    ExperienceDistiller,
    PrincipleCategory,
    RetrievalResult,
    StrategicPrinciple,
    get_experience_distiller,
    reset_experience_distiller,
)

__all__ = [
    "SkillCrystallizer",
    "ToolCallRecord",
    "ToolSequencePattern",
    "CrystallizedSkill",
    "get_crystallizer",
    "reset_crystallizer",
    # V12.4 COGNITIVE BOOST: Experience Distiller (arxiv:2510.16079)
    "ExperienceDistiller",
    "StrategicPrinciple",
    "PrincipleCategory",
    "DistillationResult",
    "RetrievalResult",
    "DistillerStats",
    "get_experience_distiller",
    "reset_experience_distiller",
]
