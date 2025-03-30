# OmniMCP

[![CI](https://github.com/OpenAdaptAI/OmniMCP/actions/workflows/ci.yml/badge.svg)](https://github.com/OpenAdaptAI/OmniMCP/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python Version](https://img.shields.io/badge/python-3.10%20|%203.11%20|%203.12-blue)](https://www.python.org/)
[![Code style: ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

OmniMCP provides rich UI context and interaction capabilities to AI models through [Model Context Protocol (MCP)](https://github.com/modelcontextprotocol) and [microsoft/OmniParser](https://github.com/microsoft/OmniParser). It focuses on enabling deep understanding of user interfaces through visual analysis, structured responses, and precise interaction.

## Core Features

- **Rich Visual Context**: Deep understanding of UI elements
- **Natural Language Interface**: Target and analyze elements using natural descriptions
- **Comprehensive Interactions**: Full range of UI operations with verification
- **Structured Types**: Clean, typed responses using dataclasses
- **Robust Error Handling**: Detailed error context and recovery strategies
- **Automated Deployment**: On-demand deployment of OmniParser backend to AWS EC2 with auto-shutdown.

## Overview

Here's a quick demonstration of the multi-step planning loop working on a synthetic login UI:

![OmniMCP Demo GIF](images/omnimcp_demo.gif)
*(This GIF shows the process: identifying the username field, simulating typing; identifying the password field, simulating typing; identifying the login button, simulating the click and transitioning to a final state.)*

The system works by analyzing the screen, planning actions with an LLM, and optionally executing them.

<p align="center">
    <img src="https://github.com/user-attachments/assets/9b2f0c8b-fadf-4170-8f57-1ac958febd39" width="400" alt="Spatial Feature Understanding">
</p>

1. **Spatial Feature Understanding**: OmniMCP begins by developing a deep understanding of the user interface's visual layout. Leveraging [microsoft/OmniParser](https://github.com/microsoft/OmniParser) (potentially deployed automatically to EC2), it performs detailed visual parsing, segmenting the screen and identifying all interactive and informational elements. This includes recognizing their types, content, spatial relationships, and attributes, creating a rich representation of the UI's static structure.

<br>

<p align="center">
    <img src="https://github.com/user-attachments/assets/b8c076bf-0d46-4130-9e7f-7e34b978e1c9" width="400" alt="Temporal Feature Understanding">
</p>

2. **Temporal Feature Understanding**: To capture the dynamic aspects of the UI, OmniMCP tracks user interactions and the resulting state transitions. It records sequences of actions and changes within the UI, building a Process Graph that represents the flow of user workflows. This temporal understanding allows AI models to reason about interaction history and plan future actions based on context. (Note: Process Graph generation is a future goal).

<br>

<p align="center">
    <img src="https://github.com/user-attachments/assets/c5fa1d28-b79e-4269-9340-6f36e6746a12" width="400" alt="Internal API Generation">
</p>

3. **Internal API Generation / Action Planning**: Utilizing the rich spatial and (optionally) temporal context it has acquired, OmniMCP leverages a Large Language Model (LLM) to plan the next action. Through In-Context Learning (prompting), the LLM dynamically determines the best action (e.g., click, type) and target element based on the current UI state, the user's goal, and the action history.

<br>

<p align="center">
    <img src="https://github.com/user-attachments/assets/78d31af5-0394-4dfc-a48e-97b524e04878" width="400" alt="External API Publication (MCP)">
</p>

4. **External API Publication (MCP)**: Optionally, OmniMCP can expose UI interaction capabilities through the [Model Context Protocol (MCP)](https://github.com/modelcontextprotocol). This provides a consistent interface for AI models (or other tools) to interact with the UI via standardized tools like `get_screen_state`, `click_element`, `type_text`, etc. (Note: MCP server implementation is currently experimental).

### Multi-Step Demo (Synthetic UI)

*(Optional: Add an animated GIF here generated from the commands below, showing the steps from `demo_output_multistep`)*
## Prerequisites

- Python >=3.10, <3.13
- `uv` installed (`pip install uv` or see [Astral Docs](https://astral.sh/uv))

### For AWS Deployment Features

The automated deployment of the OmniParser server (`omnimcp/omniparser/server.py`, triggered by `OmniParserClient` when no URL is provided) requires AWS credentials. These are loaded via `pydantic-settings` from a `.env` file in the project root or from environment variables. Ensure you have configured:

```.env
AWS_ACCESS_KEY_ID=YOUR_ACCESS_KEY
AWS_SECRET_ACCESS_KEY=YOUR_SECRET_KEY
# AWS_REGION=us-east-1 # Optional, defaults work
ANTHROPIC_API_KEY=YOUR_ANTHROPIC_KEY # Needed for LLM planning
# OMNIPARSER_URL=http://... # Optional: Specify if NOT using auto-deploy
```

**Warning:** Using the automated deployment will create and manage AWS resources (EC2 `g4dn.xlarge`, Lambda, CloudWatch Alarms, IAM Roles, Security Groups) in your account, which **will incur costs**. The system includes an auto-shutdown mechanism based on CPU inactivity (default ~60 minutes), but always remember to use `python omnimcp/omniparser/server.py stop` to clean up resources manually when finished to guarantee termination and avoid unexpected charges.

## Installation

Currently, installation is from source only.

```bash
# 1. Clone the repository
git clone [https://github.com/OpenAdaptAI/OmniMCP.git](https://www.google.com/search?q=https://github.com/OpenAdaptAI/OmniMCP.git)
cd OmniMCP

# 2. Setup environment and install dependencies
./install.sh  # Creates .venv, activates, installs deps using uv

# 3. Configure API Keys and AWS Credentials
cp .env.example .env
# Edit .env file to add your ANTHROPIC_API_KEY and AWS credentials

# To activate the environment in the future:
# source .venv/bin/activate  # Linux/macOS
# source .venv/Scripts/activate # Windows
```
*The `./install.sh` script creates a virtual environment using `uv`, activates it, and installs OmniMCP in editable mode along with test dependencies (`uv pip install -e ".[test]"`).*

## Quick Start (Illustrative Example)

**Note:** The `OmniMCP` high-level class and its associated MCP tools (`get_screen_state`, `click_element`, etc.) shown in this example (`omnimcp/omnimcp.py`) are currently under development and refactoring to fully integrate the latest `OmniParserClient`. This example represents the intended future API. For current functional examples, please see `demo.py` (synthetic UI loop) and `test_deploy_and_parse.py` (deployment verification). See [Issue #1](https://github.com/OpenAdaptAI/OmniMCP/issues/1) for related work.

```python
# Example of intended future usage
from omnimcp import OmniMCP
from omnimcp.types import ScreenState # Assuming types are importable

async def main():
    # Ensure .env file has ANTHROPIC_API_KEY and AWS keys (if using auto-deploy)
    # OmniMCP might internally create OmniParserClient which handles deployment
    mcp = OmniMCP() # May trigger deployment if OMNIPARSER_URL not set

    # Get current UI state (would use real screenshot + OmniParser)
    state: ScreenState = await mcp.get_screen_state()
    print(f"Found {len(state.elements)} elements on screen.")

    # Analyze specific element (would use LLM + visual state)
    description = await mcp.describe_element(
        "the main login button"
    )
    print(f"Description: {description}")

    # Interact with UI (would use input controllers)
    result = await mcp.click_element(
        "Login button",
        click_type="single"
    )
    if not result.success:
        print(f"Click failed: {result.error}")
    else:
        print("Click successful (basic verification).")

# Requires running in an async context
# import asyncio
# asyncio.run(main())
```

## Running the Multi-Step Demo (Synthetic UI)

This demo showcases the planning loop using generated UI images.

```bash
# Ensure environment is activated: source .venv/bin/activate
# Ensure ANTHROPIC_API_KEY is in your .env file
python demo.py
# Check the demo_output_multistep/ directory for generated images
```

## Verifying Deployment & Parsing (Real Screenshot)

This script tests the EC2 deployment and gets raw data from OmniParser for your current screen.

```bash
# Ensure environment is activated: source .venv/bin/activate
# Ensure ANTHROPIC_API_KEY and AWS credentials are in your .env file
python test_deploy_and_parse.py
# This will deploy an EC2 instance if needed (takes time!), take a screenshot,
# send it for parsing, and print the raw JSON result.
# Remember to stop the instance afterwards!
python omnimcp/omniparser/server.py stop
```

## Core Types

*(Keep the existing Core Types section)*
```python
@dataclass
class Bounds: # Example if Bounds is a dataclass, adjust if it's Tuple
    x: float
    y: float
    width: float
    height: float

@dataclass
class UIElement:
    id: int            # Unique ID assigned during processing
    type: str          # button, text_field, slider, etc
    content: str       # Text or semantic content
    bounds: Bounds     # Normalized coordinates (x, y, width, height)
    confidence: float = 1.0 # Detection confidence
    attributes: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict:
        """Convert to serializable dict"""
        # ... implementation ...
        pass

    def to_prompt_repr(self) -> str:
         """Concise representation for LLM prompts."""
         # ... implementation ...
         pass

@dataclass
class ScreenState:
    elements: List[UIElement]
    dimensions: tuple[int, int] # Actual pixel dimensions
    timestamp: float

# ... other types like InteractionResult, etc.
```

## MCP Implementation and Framework API

*(Keep this section, but maybe add a note that it reflects the target state under development)*

**Note:** This API represents the target interface provided via the Model Context Protocol, currently experimental in `omnimcp/omnimcp.py`.

### Core API

```python
async def get_screen_state() -> ScreenState:
     """Get current state of visible UI elements"""

async def describe_element(description: str) -> str:
     """Get rich description of UI element"""

async def find_elements(query: str, max_results: int = 5) -> List[UIElement]:
     """Find elements matching natural query"""

async def click_element(description: str, click_type: Literal["single", "double", "right"] = "single") -> InteractionResult:
     """Click UI element matching description"""

async def type_text(text: str, target: Optional[str] = None) -> TypeResult:
     """Type text, optionally clicking a target element first"""

# ... other potential actions like scroll_view, press_key ...
```

## Architecture

*(Keep existing Architecture section)*
### Core Components
1.  **Visual State Manager** (`omnimcp/omnimcp.py` - `VisualState` class)
    * Takes screenshot.
    * Calls OmniParser Client.
    * Maps results to `UIElement` list.
    * Provides element finding capabilities (currently basic, LLM planned).
2.  **OmniParser Client & Deploy** (`omnimcp/omniparser/`)
    * Manages communication with the OmniParser backend.
    * Handles automated deployment of OmniParser to EC2 (`server.py`).
    * Includes auto-shutdown based on inactivity (`server.py`).
3.  **LLM Planner** (`omnimcp/core.py`)
    * Takes goal, history, and current `UIElement` list.
    * Prompts LLM (e.g., Claude) to determine the next best action.
    * Parses structured JSON response from LLM.
4.  **Input Controller** (`omnimcp/input.py` or `omnimcp/utils.py`)
    * Wraps `pynput` or other libraries for mouse clicks, keyboard typing, scrolling.
5.  **(Optional) MCP Server** (`omnimcp/omnimcp.py` - `OmniMCP` class using `FastMCP`)
    * Exposes functionality as MCP tools for external interaction.

## Development

### Environment Setup
```bash
# Clone repo and cd into it (see Installation)
./install.sh # Creates venv, activates, installs dependencies
# Activate env if needed: source .venv/bin/activate or .venv\Scripts\activate
```

### Running Checks
```bash
# Run linters and format check
uv run ruff check .
uv run ruff format --check . # Use 'uv run ruff format .' to apply formatting

# Run basic tests (unit/integration, skips e2e)
uv run pytest tests/

# Run end-to-end tests (Requires AWS Credentials configured!)
# WARNING: Creates/Destroys real AWS resources! May incur costs.
uv run pytest --run-e2e tests/
```

### Debug Support
*(Keep existing Debug Support section, but note it depends on `OmniMCP` class refactor)*

## Configuration

OmniMCP uses a `.env` file in the project root for configuration, loaded via `omnimcp/config.py`. See `.env.example`.

Key variables:
```dotenv
# Required for LLM planning
ANTHROPIC_API_KEY=sk-ant-api03-...

# Required for EC2 deployment features (if not using OMNIPARSER_URL)
AWS_ACCESS_KEY_ID=YOUR_AWS_ACCESS_KEY
AWS_SECRET_ACCESS_KEY=YOUR_AWS_SECRET_KEY
AWS_REGION=us-east-1 # Or your preferred region

# Optional: URL for a manually managed OmniParser server
# OMNIPARSER_URL=http://<your-parser-ip>:8000

# Optional: EC2 Instance configuration (defaults provided)
# AWS_EC2_INSTANCE_TYPE=g4dn.xlarge
# INACTIVITY_TIMEOUT_MINUTES=60

# Optional: Debugging
# DEBUG=True
# LOG_LEVEL=DEBUG
```

## Performance Considerations
*(Keep existing Performance Considerations section)*

## Limitations and Future Work
*(Keep existing Limitations and Future Work section)*

## Contributing
*(Keep existing Contributing section)*

## License
MIT License

## Project Status
Actively developing core OmniParser integration and action execution capabilities. API is experimental and subject to change.

---

*(Keep existing links to other MD files if they exist)*
For detailed implementation guidance, see [CLAUDE.md](CLAUDE.md).
For API reference, see [API.md](API.md).

## Contact
*(Keep existing Contact section)*

Remember: OmniMCP focuses on providing rich UI context through visual understanding. Design for clarity, build with structure, and maintain robust error handling.
