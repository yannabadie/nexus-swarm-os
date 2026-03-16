"""
Protocol V7 - Schémas Pydantic souples avec auto-repair

Features:
- Tous les champs optionnels avec defaults intelligents
- Validateurs auto-réparent les typos courants
- Plus de crashes sur champs manquants
"""

from typing import Any

from pydantic import BaseModel, ValidationInfo, field_validator


class ThoughtChain(BaseModel):
    """Un pas de raisonnement"""

    step: int
    reasoning: str


class LightMessageV7(BaseModel):
    """
    Message léger pour communication (TALK, DELEGATE)

    All fields optional with intelligent defaults.
    Validators auto-repair common errors.
    """

    sender: str
    action_type: str

    # Optional avec defaults
    content: str | None = ""
    thought_process: list[ThoughtChain] | None = []
    reflection: str | None = None
    next_agent: str | None = None
    status: str | None = "CONTINUE"
    action_summary: str | None = None
    instructions_for_next: str | None = None
    strategic_plan_update: list[dict] | None = None

    # Validateurs auto-réparateurs (Pydantic V2 syntax)
    @field_validator("action_type")
    @classmethod
    def repair_action_type(cls, v: str) -> str:
        """Auto-correct typos et variations"""
        if not v:
            return "TALK"  # Default safe

        repairs = {
            "DELEGATION": "DELEGATE",
            "DELEGATING": "DELEGATE",
            "TALKING": "TALK",
            "TOOL": "TOOL_USE",
            "USING_TOOL": "TOOL_USE",
            "FINISHED": "FINISH",
            "FINISHING": "FINISH",
            "ERROR": "ERROR",
            "CONTINUE": "CONTINUE",
            "CONTINUING": "CONTINUE",
        }

        v_upper = v.upper()
        return repairs.get(v_upper, v_upper)

    @field_validator("sender")
    @classmethod
    def repair_sender(cls, v: str) -> str:
        """Capitalize sender name"""
        if not v:
            return "Unknown"
        return v.capitalize()

    @field_validator("next_agent", mode="before")
    @classmethod
    def default_next_agent(cls, v: str | None, info: ValidationInfo) -> str | None:
        """V7 FIX: Si next_agent oublié, ALTERNER vers l'autre agent"""
        if v is None and info.data.get("sender"):
            sender = info.data["sender"].capitalize()
            # Alterner au lieu de garder le même
            return "Claude" if sender == "Gemini" else "Gemini"
        if v:
            return v.capitalize()
        return None

    @field_validator("status")
    @classmethod
    def repair_status(cls, v: str | None) -> str:
        """Auto-correct status"""
        if not v:
            return "CONTINUE"

        repairs = {
            "FINISHED": "FINISHED",
            "FINISH": "FINISHED",
            "DONE": "FINISHED",
            "COMPLETE": "FINISHED",
            "ERROR": "ERROR_REVIEW_NEEDED",
            "FAILED": "ERROR_REVIEW_NEEDED",
            "CONTINUE": "CONTINUE",
            "ONGOING": "CONTINUE",
            "IN_PROGRESS": "CONTINUE",
        }

        v_upper = v.upper()
        return repairs.get(v_upper, "CONTINUE")


class ToolUse(BaseModel):
    """Tool request"""

    tool_name: str
    arguments: dict[str, Any]
    expected_outcome: str | None = "Tool execution successful"


class PostActionReview(BaseModel):
    """CFL validation review"""

    validation_status: str  # SUCCESS, FAILURE, PARTIAL_SUCCESS
    analysis: str
    discrepancies: list[str] | None = []
    correction_plan: str | None = None


class HeavyMessageV7(LightMessageV7):
    """Message avec tool use (CFL)"""

    action_type: str = "TOOL_USE"
    tool_use: ToolUse | None = None
    post_action_review: PostActionReview | None = None
