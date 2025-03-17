# OmniMCP

OmniMCP provides rich UI context and interaction capabilities to AI models through the Model Context Protocol (MCP). It focuses on enabling deep understanding of user interfaces through visual analysis, structured responses, and precise interaction.

## Core Features

- **Rich Visual Context**: Deep understanding of UI elements 
- **Natural Language Interface**: Target and analyze elements using natural descriptions
- **Comprehensive Interactions**: Full range of UI operations with verification
- **Structured Types**: Clean, typed responses using dataclasses
- **Robust Error Handling**: Detailed error context and recovery strategies

## Installation

```bash
pip install omnimcp

# Or from source:
git clone https://github.com/OpenAdaptAI/omnimcp.git
cd omnimcp
./install.sh
```

## Quick Start

```python
from omnimcp import OmniMCP
from omnimcp.types import UIElement, ScreenState, InteractionResult

async def main():
    mcp = OmniMCP()
    
    # Get current UI state
    state: ScreenState = await mcp.get_screen_state()
    
    # Analyze specific element
    description = await mcp.describe_element(
        "error message in red text"
    )
    print(f"Found element: {description}")
    
    # Interact with UI
    result = await mcp.click_element(
        "Submit button",
        click_type="single"
    )
    if not result.success:
        print(f"Click failed: {result.error}")

asyncio.run(main())
```

## Core Types

```python
@dataclass
class UIElement:
    type: str          # button, text, slider, etc
    content: str       # Text or semantic content
    bounds: Bounds     # Normalized coordinates
    confidence: float  # Detection confidence
    attributes: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict:
        """Convert to serializable dict"""
    
@dataclass
class ScreenState:
    elements: List[UIElement]
    dimensions: tuple[int, int]
    timestamp: float
    
    def find_elements(self, query: str) -> List[UIElement]:
        """Find elements matching natural query"""
    
@dataclass
class InteractionResult:
    success: bool
    element: Optional[UIElement]
    error: Optional[str] = None
    context: Dict[str, Any] = field(default_factory=dict)
```

## MCP Tools

OmniMCP provides a rich set of tools for UI understanding and interaction:

### Visual Understanding
```python
@tool()
async def get_screen_state() -> ScreenState:
    """Get current state of visible UI elements"""

@tool()
async def describe_element(description: str) -> str:
    """Get rich description of UI element"""

@tool()
async def find_elements(
    query: str,
    max_results: int = 5
) -> List[UIElement]:
    """Find elements matching natural query"""
```

### UI Interaction
```python
@tool()
async def click_element(
    description: str,
    click_type: Literal["single", "double", "right"] = "single"
) -> InteractionResult:
    """Click UI element matching description"""

@tool()
async def scroll_view(
    direction: Literal["up", "down", "left", "right"],
    amount: float
) -> ScrollResult:
    """Scroll in specified direction"""

@tool()
async def type_text(
    text: str,
    target: Optional[str] = None
) -> TypeResult:
    """Type text, optionally targeting element"""
```

## Architecture

### Core Components

1. **Visual State Manager**
   - Element detection
   - State management and caching
   - Rich context extraction
   - History tracking

2. **MCP Tools**
   - Tool definitions and execution
   - Typed responses
   - Error handling
   - Debug support

3. **UI Parser**
   - Element detection
   - Text recognition
   - Visual analysis
   - Element relationships

4. **Input Controller**
   - Precise mouse control
   - Keyboard input
   - Action verification
   - Movement optimization

## Development

### Environment Setup
```bash
# Create development environment
./install.sh --dev

# Run tests
pytest tests/

# Run linting
ruff check .
```

### Debug Support
```python
@dataclass
class DebugContext:
    """Rich debug information"""
    tool_name: str
    inputs: Dict[str, Any]
    result: Any
    duration: float
    visual_state: Optional[ScreenState]
    error: Optional[Dict] = None
    
    def save_snapshot(self, path: str) -> None:
        """Save debug snapshot for analysis"""

# Enable debug mode
mcp = OmniMCP(debug=True)

# Get debug context
debug_info = await mcp.get_debug_context()
print(f"Last operation: {debug_info.tool_name}")
print(f"Duration: {debug_info.duration}ms")
```

## Configuration

```python
# .env or environment variables
OMNIMCP_DEBUG=1             # Enable debug mode
OMNIMCP_PARSER_URL=http://... # Custom parser URL
OMNIMCP_LOG_LEVEL=DEBUG    # Log level
```

## Performance Considerations

1. **State Management**
   - Smart caching
   - Incremental updates
   - Background processing
   - Efficient invalidation

2. **Element Targeting**
   - Efficient search
   - Early termination
   - Result caching
   - Smart retries

3. **Visual Analysis**
   - Minimal screen captures
   - Region-based updates
   - Parser optimization
   - Result caching

## Contributing

1. Fork repository
2. Create feature branch
3. Implement changes
4. Add tests
5. Submit pull request

## License

MIT License

## Project Status

Active development - API may change

---

For detailed implementation guidance, see [CLAUDE.md](CLAUDE.md).
For API reference, see [API.md](API.md).

## Contact

- Issues: GitHub Issues
- Questions: Discussions
- Security: security@openadapt.ai

Remember: OmniMCP focuses on providing rich UI context through visual understanding. Design for clarity, build with structure, and maintain robust error handling.
