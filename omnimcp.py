"""
# Example usage from README.md
async def example():
    mcp = OmniMCP()

    # Get current UI state
    state: ScreenState = await mcp.get_screen_state()

    # Analyze specific element
    description = await mcp.describe_element("error message in red text")
    print(f"Found element: {description}")

    # Interact with UI
    result = await mcp.click_element("Submit button", click_type="single")
    if not result.success:
        print(f"Click failed: {result.error}")
"""

from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any, Literal, Tuple
from mcp.server.fastmcp import FastMCP
from PIL import Image


@dataclass
class Bounds:
    x: float
    y: float
    width: float
    height: float


@dataclass
class UIElement:
    type: str  # button, text, slider, etc
    content: str  # Text or semantic content
    bounds: Bounds  # Normalized coordinates
    confidence: float  # Detection confidence
    attributes: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ScreenState:
    elements: List[UIElement]
    dimensions: Tuple[int, int]
    timestamp: float


@dataclass
class ActionVerification:
    success: bool
    before_state: bytes  # Screenshot
    after_state: bytes
    changes_detected: List[Bounds]
    confidence: float


@dataclass
class InteractionResult:
    success: bool
    element: Optional[UIElement]
    error: Optional[str] = None
    context: Dict[str, Any] = field(default_factory=dict)
    verification: Optional[ActionVerification] = None


@dataclass
class ScrollResult(InteractionResult):
    scroll_amount: float


@dataclass
class TypeResult(InteractionResult):
    text_entered: str


@dataclass
class ToolError:
    message: str
    visual_context: Optional[bytes]  # Screenshot
    attempted_action: str
    element_description: str
    recovery_suggestions: List[str]


@dataclass
class DebugContext:
    tool_name: str
    inputs: Dict[str, Any]
    result: Any
    duration: float
    visual_state: Optional[ScreenState]
    error: Optional[Dict] = None

    def save_snapshot(self, path: str) -> None:
        """Save debug snapshot for analysis"""


class OmniMCP:
    """Model Context Protocol server for UI understanding"""

    def __init__(self, parser_url: Optional[str] = None, debug: bool = False):
        self.mcp = FastMCP("omnimcp")
        self._setup_tools()

    def _setup_tools(self):
        """Register MCP tools from README/CLAUDE.md"""

        @self.mcp.tool()
        async def get_screen_state() -> ScreenState:
            """Get current state of visible UI elements"""

        @self.mcp.tool()
        async def describe_element(description: str) -> str:
            """Get rich description of UI element"""

        @self.mcp.tool()
        async def find_elements(query: str, max_results: int = 5) -> List[UIElement]:
            """Find elements matching natural query"""

        @self.mcp.tool()
        async def click_element(
            description: str,
            click_type: Literal["single", "double", "right"] = "single",
        ) -> InteractionResult:
            """Click UI element matching description"""

        @self.mcp.tool()
        async def scroll_view(
            direction: Literal["up", "down", "left", "right"], amount: float
        ) -> ScrollResult:
            """Scroll in specified direction"""

        @self.mcp.tool()
        async def type_text(text: str, target: Optional[str] = None) -> TypeResult:
            """Type text, optionally targeting element"""

        @self.mcp.tool()
        async def press_key(key: str, modifiers: List[str] = None) -> InteractionResult:
            """Press keyboard key with optional modifiers"""

    async def start(self, port: int = 8000):
        """Start MCP server"""
        await self.mcp.serve(port=port)
