from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any, Literal, Tuple


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
