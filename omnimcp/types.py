# omnimcp/types.py

from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any, Tuple, Literal

from pydantic import BaseModel, Field, field_validator, ValidationInfo


# Define Bounds (assuming normalized coordinates 0.0-1.0)
Bounds = Tuple[float, float, float, float]  # (x, y, width, height)


@dataclass
class UIElement:
    """Represents a UI element with its properties."""

    id: int  # Unique identifier for referencing
    type: str  # button, text_field, checkbox, link, text, etc.
    content: str  # Text content or accessibility label
    bounds: Bounds  # Normalized coordinates (x, y, width, height)
    confidence: float = 1.0  # Detection confidence (1.0 for synthetic)
    attributes: Dict[str, Any] = field(default_factory=dict)  # e.g., {'checked': False}

    def to_dict(self) -> Dict[str, Any]:
        """Convert UIElement to a dictionary."""
        return {
            "id": self.id,
            "type": self.type,
            "content": self.content,
            "bounds": self.bounds,
            "confidence": self.confidence,
            "attributes": self.attributes,
        }

    def to_prompt_repr(self) -> str:
        """Concise representation for LLM prompts."""
        bound_str = (
            f"({self.bounds[0]:.2f}, {self.bounds[1]:.2f}, "
            f"{self.bounds[2]:.2f}, {self.bounds[3]:.2f})"
        )
        # Truncate long content
        content_preview = (
            (self.content[:30] + "...") if len(self.content) > 33 else self.content
        )
        # Avoid newlines in prompt list
        content_preview = content_preview.replace("\n", " ")
        return (
            f"ID: {self.id}, Type: {self.type}, "
            f"Content: '{content_preview}', Bounds: {bound_str}"
        )


@dataclass
class ScreenState:
    """Represents the current state of the screen with UI elements."""

    elements: List[UIElement]
    dimensions: Tuple[int, int]  # Actual pixel dimensions
    timestamp: float


@dataclass
class ActionVerification:
    """Verification data for an action."""

    success: bool
    before_state: bytes  # Screenshot
    after_state: bytes
    changes_detected: List[Bounds]
    confidence: float


@dataclass
class InteractionResult:
    """Result of an interaction with the UI."""

    success: bool
    element: Optional[UIElement]
    error: Optional[str] = None
    context: Dict[str, Any] = field(default_factory=dict)
    verification: Optional[ActionVerification] = None


@dataclass
class ScrollResult(InteractionResult):
    """Result of a scroll action."""

    scroll_amount: float = 0.0


@dataclass
class TypeResult(InteractionResult):
    """Result of typing text."""

    text_entered: str = ""


@dataclass
class ToolError:
    """Rich error information for MCP tools."""

    message: str
    visual_context: Optional[bytes]  # Screenshot
    attempted_action: str
    element_description: str
    recovery_suggestions: List[str]


@dataclass
class DebugContext:
    """Debug information for tool execution."""

    tool_name: str
    inputs: Dict[str, Any]
    result: Any
    duration: float
    visual_state: Optional[ScreenState]
    error: Optional[Dict] = None

    def save_snapshot(self, path: str) -> None:
        """Save debug snapshot for analysis."""
        # TODO: Implement snapshot saving


class LLMActionPlan(BaseModel):
    """Defines the structured output expected from the LLM for action planning."""

    # Required fields: Use '...' as first arg OR Field(description=...) might work in V2+
    # Using Field(..., description=...) is explicit and clear for required fields.
    reasoning: str = Field(
        ..., description="Step-by-step thinking process leading to the chosen action."
    )
    action: Literal["click", "type", "scroll", "press_key"] = Field(
        ..., description="The single next action to perform."
    )
    is_goal_complete: bool = Field(
        ...,
        description="Set to true if the user's overall goal is fully achieved by the current state, false otherwise.",
    )

    # Optional fields: Use 'default=None'
    element_id: Optional[int] = Field(
        default=None,
        description="The ID of the target UI element IF the action is 'click' or 'type'. Must be null for 'press_key' and 'scroll'.",
    )
    text_to_type: Optional[str] = Field(
        default=None,
        description="Text to type IF action is 'type'. Must be null otherwise.",
    )
    key_info: Optional[str] = Field(
        default=None,
        description="Key or shortcut to press IF action is 'press_key' (e.g., 'Enter', 'Cmd+Space', 'Win'). Must be null otherwise, UNLESS is_goal_complete is true.",  # Added note
    )
    is_goal_complete: bool = Field(
        ..., description="Set to true if the user's overall goal is fully achieved..."
    )

    @field_validator("element_id")
    @classmethod
    def check_element_id(cls, v: Optional[int], info: ValidationInfo) -> Optional[int]:
        action = info.data.get("action")
        is_complete = info.data.get("is_goal_complete")  # Get goal completion status

        # Allow element_id to be None if the goal is already complete
        if is_complete:
            return v  # Allow None or any value if goal is complete

        # Original validation (only applied if goal is NOT complete)
        # Click requires element_id
        if action == "click" and v is None:
            raise ValueError(
                "element_id is required for action 'click' when goal is not complete"
            )
        # Scroll and press_key must not have element_id
        if action in ["scroll", "press_key"] and v is not None:
            raise ValueError(f"element_id must be null for action '{action}'")
        # Type *can* have null element_id (e.g., typing in search bar)
        return v

    @field_validator("text_to_type")
    @classmethod
    def check_text_to_type(
        cls, v: Optional[str], info: ValidationInfo
    ) -> Optional[str]:
        action = info.data.get("action")
        if action == "type" and v is None:
            # Allow empty string for type, but not None if action is type
            raise ValueError("text_to_type is required for action 'type'")
        if action != "type" and v is not None:
            raise ValueError("text_to_type must be null for actions other than 'type'")
        return v

    @field_validator("key_info")
    @classmethod
    def check_key_info(cls, v: Optional[str], info: ValidationInfo) -> Optional[str]:
        action = info.data.get("action")
        is_complete = info.data.get("is_goal_complete")  # Get goal completion status

        # Allow key_info to be None if the goal is already complete, regardless of action
        if is_complete:
            return v  # Allow None or any value if goal is complete

        # Original validation: If goal is NOT complete, enforce rules
        if action == "press_key" and v is None:
            raise ValueError(
                "key_info is required for action 'press_key' when goal is not complete"
            )
        if action != "press_key" and v is not None:
            raise ValueError("key_info must be null for actions other than 'press_key'")
        return v
