# OmniMCP

OmniMCP provides rich UI context and interaction capabilities to AI models through [Model Context Protocol (MCP)](https://github.com/modelcontextprotocol) and [microsoft/OmniParser](https://github.com/microsoft/OmniParser). It focuses on enabling deep understanding of user interfaces through visual analysis, structured responses, and precise interaction.

## Core Features

- **Rich Visual Context**: Deep understanding of UI elements 
- **Natural Language Interface**: Target and analyze elements using natural descriptions
- **Comprehensive Interactions**: Full range of UI operations with verification
- **Structured Types**: Clean, typed responses using dataclasses
- **Robust Error Handling**: Detailed error context and recovery strategies

## Overview

<p align="center">
    <img src="https://github.com/user-attachments/assets/9b2f0c8b-fadf-4170-8f57-1ac958febd39" width="400" alt="Spatial Feature Understanding">
</p>

1. **Spatial Feature Understanding**: OmniMCP begins by developing a deep understanding of the user interface's visual layout. Leveraging [microsoft/OmniParser](https://github.com/microsoft/OmniParser), it performs detailed visual parsing, segmenting the screen and identifying all interactive and informational elements. This includes recognizing their types, content, spatial relationships, and attributes, creating a rich representation of the UI's static structure.

<br>

<p align="center">
    <img src="https://github.com/user-attachments/assets/b8c076bf-0d46-4130-9e7f-7e34b978e1c9" width="400" alt="Temporal Feature Understanding">
</p>

2. **Temporal Feature Understanding**: To capture the dynamic aspects of the UI, OmniMCP tracks user interactions and the resulting state transitions. It records sequences of actions and changes within the UI, building a Process Graph that represents the flow of user workflows. This temporal understanding allows AI models to reason about interaction history and plan future actions based on context.

<br>

<p align="center">
    <img src="https://github.com/user-attachments/assets/c5fa1d28-b79e-4269-9340-6f36e6746a12" width="400" alt="Internal API Generation">
</p>

3. **Internal API Generation**: Utilizing the rich spatial and temporal context it has acquired, OmniMCP leverages a Large Language Model (LLM) to generate an internal, context-specific API. Through In-Context Learning (prompting), the LLM dynamically creates a set of functions and parameters that accurately reflect the understood spatiotemporal features of the UI. This internal API is tailored to the current state and interaction history, enabling precise and context-aware interactions.

<br>

<p align="center">
    <img src="https://github.com/user-attachments/assets/78d31af5-0394-4dfc-a48e-97b524e04878" width="400" alt="External API Publication (MCP)">
</p>

4. **External API Publication (MCP)**: Finally, OmniMCP exposes this dynamically generated internal API through the [Model Context Protocol (MCP)](https://github.com/modelcontextprotocol). This provides a consistent and straightforward interface for both humans (via natural language translated by the LLM) and AI models to interact with the UI. Through this MCP interface, a full range of UI operations can be performed with verification, all powered by the AI model's deep, dynamically created understanding of the UI's spatiotemporal context.

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

## MCP Implementation and Framework API

OmniMCP provides a powerful yet intuitive API for model interaction through the Model Context Protocol (MCP). This standardized interface enables seamless integration between large language models and UI automation capabilities.

### Core API

```python
async def describe_current_state() -> str:
    """Get rich description of current UI state"""

async def find_elements(query: str) -> List[UIElement]:
    """Find elements matching natural query"""

async def take_action(
    description: str,
    image_context: Optional[bytes] = None
) -> ActionResult:
    """Execute action described in natural language with optional visual context"""
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

## Limitations and Future Work

Current limitations include:
- Need for more extensive validation across UI patterns
- Optimization of pattern recognition in process graphs
- Refinement of spatial-temporal feature synthesis

### Future Research Directions

Beyond reinforcement learning integration, we plan to explore:
- **Fine-tuning Specialized Models**: Training domain-specific models on UI automation tasks to improve efficiency and reduce token usage
- **Process Graph Embeddings with RAG**: Embedding generated process graph descriptions and retrieving relevant interaction patterns via Retrieval Augmented Generation
- Development of comprehensive evaluation metrics
- Enhanced cross-platform generalization
- Integration with broader LLM architectures
- Collaborative multi-agent UI automation frameworks

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
