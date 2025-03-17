from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any, Literal, Tuple


@dataclass
class Bounds:
    """Normalized bounds of a UI element (0-1 range)."""

    x: float
    y: float
    width: float
    height: float


@dataclass
class UIElement:
    """Represents a UI element with its properties."""

    type: str  # button, text, slider, etc
    content: str  # Text or semantic content
    bounds: Bounds  # Normalized coordinates
    confidence: float  # Detection confidence
    attributes: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict:
        """Convert to serializable dict."""
        return {
            "type": self.type,
            "content": self.content,
            "bounds": {
                "x": self.bounds.x,
                "y": self.bounds.y,
                "width": self.bounds.width,
                "height": self.bounds.height,
            },
            "confidence": self.confidence,
            "attributes": self.attributes,
        }


@dataclass
class ScreenState:
    """Represents the current state of the screen with UI elements."""

    elements: List[UIElement]
    dimensions: Tuple[int, int]
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

    scroll_amount: float


@dataclass
class TypeResult(InteractionResult):
    """Result of typing text."""

    text_entered: str


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
