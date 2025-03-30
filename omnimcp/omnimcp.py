# omnimcp/omnimcp.py

"""
OmniMCP: High-level UI automation interface using visual perception.

This module provides the main entry points and orchestration logic for OmniMCP.
It defines:
  - `VisualState`: Manages screen state by capturing screenshots, invoking the
    `OmniParserClient` (which handles communication with and deployment of the
    OmniParser backend), and mapping the parser's output into structured
    `UIElement` objects.
  - `OmniMCP`: Implements an optional Model Context Protocol (MCP) server (`FastMCP`)
    exposing UI interaction capabilities (like get state, click, type) as tools
    for external agents (e.g., LLMs). It uses `VisualState` for perception
    and basic input controllers (`MouseController`, `KeyboardController`) for interaction.

Core Workflow (Conceptual):
1. Capture Screenshot (`take_screenshot`)
2. Get UI Element Structure via `OmniParserClient` -> `parse_image` (returns JSON)
3. Map JSON to `List[UIElement]` (`VisualState._update_elements_from_parser`)
4. (Optional) LLM plans next action based on `List[UIElement]` and goal (`core.py`)
5. (Optional) Execute action using input controllers (`MouseController`, etc.)
6. (Optional) Verify action result (`_verify_action`).

Note: The MCP server aspect is experimental. Core functionality involves
`VisualState` for perception and `core.py` for planning.
"""

import asyncio
import time
from typing import Any, Dict, List, Literal, Optional, Tuple

import numpy as np
from mcp.server.fastmcp import FastMCP
from loguru import logger
from PIL import Image

from omnimcp.omniparser.client import OmniParserClient
from omnimcp.utils import (
    take_screenshot,
    compute_diff,
    MouseController,
    KeyboardController,
)
from omnimcp.types import (
    Bounds,
    UIElement,
    ScreenState,
    ActionVerification,
    InteractionResult,
    ScrollResult,
    TypeResult,
)


class VisualState:
    """
    Manages the current state of visible UI elements by taking screenshots,
    using OmniParserClient for analysis, and mapping results.
    """

    def __init__(self, parser_client: OmniParserClient):
        """Initialize the visual state manager.

        Args:
            parser_client: An initialized OmniParserClient instance.
        """
        self.elements: List[UIElement] = []
        self.timestamp: Optional[float] = None
        self.screen_dimensions: Optional[Tuple[int, int]] = None
        self._last_screenshot: Optional[Image.Image] = None
        self._parser_client = parser_client
        if not self._parser_client:
            logger.critical("VisualState initialized without a valid parser_client!")
            raise ValueError("VisualState requires a valid OmniParserClient instance.")
        logger.info("VisualState initialized.")

    async def update(self) -> None:
        """
        Update visual state: take screenshot, parse via client, map results.
        Updates self.elements, self.timestamp, self.screen_dimensions.
        """
        logger.info("VisualState update requested...")
        start_time = time.time()
        try:
            # 1. Capture screenshot
            logger.debug("Taking screenshot...")
            screenshot = take_screenshot()
            if screenshot is None:
                raise RuntimeError("Failed to take screenshot.")
            self._last_screenshot = screenshot
            self.screen_dimensions = screenshot.size
            logger.debug(f"Screenshot taken: dimensions={self.screen_dimensions}")

            # 2. Process with UI parser client
            if not self._parser_client.server_url:
                # This might happen if client failed init but wasn't caught earlier
                logger.error(
                    "OmniParser client server URL not available. Cannot parse."
                )
                self.elements = []  # Clear elements
                self.timestamp = time.time()
                return

            logger.debug(f"Parsing screenshot via {self._parser_client.server_url}...")
            parser_result = self._parser_client.parse_image(screenshot)

            # 3. Update elements list using the mapping logic
            logger.debug("Mapping parser results...")
            self._update_elements_from_parser(parser_result)
            self.timestamp = time.time()
            logger.info(
                f"VisualState update complete. Found {len(self.elements)}"
                f"elements. Took {time.time() - start_time:.2f}s."
            )

        except Exception as e:
            logger.error(f"Failed to update visual state: {e}", exc_info=True)
            self.elements = []  # Clear elements on error
            self.timestamp = time.time()  # Still update timestamp

    def _update_elements_from_parser(self, parser_json: Dict):
        """Process parser results dictionary into UIElements."""
        new_elements: List[UIElement] = []
        element_id_counter = 0

        if not isinstance(parser_json, dict):
            logger.error(
                f"Parser result is not a dictionary: {type(parser_json)}. "
                "Cannot map elements."
            )
            self.elements = new_elements  # Assign empty list
            return

        if "error" in parser_json:
            logger.error(
                f"Parser returned an error in JSON response: {parser_json['error']}"
            )
            self.elements = new_elements  # Assign empty list
            return

        # Adjust key based on actual OmniParser output schema if different from
        # "parsed_content_list"
        raw_elements: List[Dict[str, Any]] = parser_json.get("parsed_content_list", [])
        if not isinstance(raw_elements, list):
            logger.error(
                "Expected 'parsed_content_list' key in parser JSON to be a list, got: "
                f"{type(raw_elements)}"
            )
            self.elements = new_elements  # Assign empty list
            return

        logger.debug(
            f"Mapping {len(raw_elements)} raw elements from OmniParser response."
        )

        for item in raw_elements:
            # Pass screen dimensions for validation inside _convert_to_ui_element
            ui_element = self._convert_to_ui_element(item, element_id_counter)
            if ui_element:
                new_elements.append(ui_element)
                element_id_counter += 1

        logger.debug(f"Successfully mapped {len(new_elements)} valid UIElements.")
        self.elements = new_elements  # Atomically update the list

    def _convert_to_ui_element(
        self, item: Dict[str, Any], element_id: int
    ) -> Optional[UIElement]:
        """Convert single parser element dict to UIElement dataclass with validation."""
        try:
            if not isinstance(item, dict):
                logger.warning(f"Skipping non-dict item in parsed_content_list: {item}")
                return None

            # 1. Extract and validate bbox
            # Assuming OmniParser bbox is [x_min_rel, y_min_rel, x_max_rel, y_max_rel]
            bbox_rel = item.get("bbox")
            if not isinstance(bbox_rel, list) or len(bbox_rel) != 4:
                logger.debug(
                    f"Skipping element (id={element_id}) due to invalid/missing bbox: "
                    f"{item.get('content')}"
                )
                return None

            # 2. Convert bbox to normalized (x, y, width, height) format and validate values
            x_min, y_min, x_max, y_max = map(float, bbox_rel)  # Ensure floats
            x = x_min
            y = y_min
            w = x_max - x_min
            h = y_max - y_min

            # Validate coordinate ranges (relative 0-1) and dimensions (positive w/h)
            tolerance = 0.001  # Allow for minor float inaccuracies near edges
            if not (
                (-tolerance <= x <= 1.0 + tolerance)
                and (-tolerance <= y <= 1.0 + tolerance)
                and w > 0.0
                and h > 0.0
                and (x + w) <= 1.0 + tolerance
                and (y + h) <= 1.0 + tolerance
            ):
                logger.warning(
                    f"Skipping element (id={element_id}) due to invalid relative "
                    f"bounds values (x={x:.3f}, y={y:.3f}, w={w:.3f}, h={h:.3f}): "
                    f"{item.get('content')}"
                )
                return None

            # Clamp values to ensure they are strictly within [0.0, 1.0] after validation
            x = max(0.0, min(1.0, x))
            y = max(0.0, min(1.0, y))
            w = max(0.0, min(1.0 - x, w))  # Ensure width doesn't exceed boundary
            h = max(0.0, min(1.0 - y, h))  # Ensure height doesn't exceed boundary

            # Re-check width/height after clamping, must be > 0
            if w <= 0.0 or h <= 0.0:
                logger.warning(
                    f"Skipping element (id={element_id}) due to zero width/height "
                    f"after clamping: {item.get('content')}"
                )
                return None

            bounds: Bounds = (x, y, w, h)

            # Optionally filter tiny elements based on absolute size
            if self.screen_dimensions:
                img_width, img_height = self.screen_dimensions
                min_pixel_size = 3  # Configurable? Minimum width or height in pixels
                if (w * img_width < min_pixel_size) or (
                    h * img_height < min_pixel_size
                ):
                    logger.debug(
                        f"Skipping tiny element (id={element_id}, w={w * img_width:.1f}, "
                        f"h={h * img_height:.1f} px): {item.get('content')}"
                    )
                    return None
            # else: # If dimensions aren't available yet, cannot filter by pixel size
            #     logger.warning(
            #         "Cannot filter tiny elements: "
            #         "screen_dimensions not yet available."
            #     )

            # 3. Extract and normalize type string
            element_type = (
                str(item.get("type", "unknown")).lower().strip().replace(" ", "_")
            )

            # 4. Extract content
            content = str(item.get("content", "")).strip()  # Strip whitespace

            # 5. Create UIElement
            return UIElement(
                id=element_id,
                type=element_type,
                content=content,
                bounds=bounds,
                confidence=float(
                    item.get("confidence", 0.0)
                ),  # Default confidence to 0.0
                attributes=item.get("attributes", {})
                or {},  # Ensure it's a dict, default to empty
            )

        except (ValueError, TypeError, KeyError) as e:
            logger.warning(
                f"Skipping element (id={element_id}) due to mapping error: "
                f"{item.get('content')} - Error: {e}"
            )
            return None
        except Exception as unexpected_e:
            # Catch any other unexpected errors during item processing
            logger.error(
                f"Unexpected error mapping element (id={element_id}): {item.get('content')} - {unexpected_e}",
                exc_info=True,
            )
            return None

    def find_element(self, description: str) -> Optional[UIElement]:
        """Find UI element matching description (basic placeholder)."""
        # NOTE: This is a basic placeholder and should be replaced with a more
        # sophisticated matching algorithm, potentially using an LLM.
        logger.debug(
            f"Finding element described as: '{description}' using basic matching."
        )
        if not self.elements:
            logger.warning("find_element called but no elements in current state.")
            return None

        search_terms = [term for term in description.lower().split() if term]
        if not search_terms:
            logger.warning("find_element called with empty description.")
            return None

        best_match = None
        # Initialize score to 0, only update if a better positive score is found
        highest_score = 0

        for element in self.elements:
            content_lower = element.content.lower()
            type_lower = element.type.lower()
            score = 0
            for term in search_terms:
                if term in content_lower:
                    score += 2
                if term in type_lower:
                    score += 1

            # Only update best_match if the current score is positive AND higher than the previous best
            if score > highest_score:
                highest_score = score
                best_match = element
            # Optional tie-breaking (e.g., prefer elements with content) could go here
            # elif score == highest_score and score > 0: ...

        # Check if any positive score was found
        if best_match and highest_score > 0:
            logger.info(
                f"Found best match (score={highest_score}) for '{description}': ID={best_match.id}, Type={best_match.type}, Content='{best_match.content[:30]}...'"
            )
            return best_match  # Return the element if score > 0
        else:
            logger.warning(
                f"No element found with positive match score for description: '{description}'"
            )
            return None  # Return None if no term matched (score remained 0 or less)


class OmniMCP:
    """Model Context Protocol server for UI understanding."""

    def __init__(self, parser_url: Optional[str] = None, debug: bool = False):
        """Initialize the OmniMCP server."""
        logger.info(f"Initializing OmniMCP. Debug={debug}")
        try:
            self._parser_client = OmniParserClient(
                server_url=parser_url, auto_deploy=(parser_url is None)
            )
            logger.success("OmniParserClient initialized successfully within OmniMCP.")
        except Exception as client_init_e:
            logger.critical(
                f"Failed to initialize OmniParserClient needed by OmniMCP: {client_init_e}",
                exc_info=True,
            )
            raise RuntimeError(
                "OmniMCP cannot start without a working OmniParserClient"
            ) from client_init_e

        # Initialize other components, passing the client to VisualState
        self._visual_state = VisualState(parser_client=self._parser_client)
        self._mouse = MouseController()
        self._keyboard = KeyboardController()
        self._debug = debug
        self._debug_context = None

        self.mcp = FastMCP("omnimcp")  # Initialize MCP server
        self._setup_tools()  # Register tools
        logger.info("OmniMCP initialization complete. Tools registered.")

    # Ensure they use `await self._visual_state.update()` before needing elements
    # and interact with self._mouse, self._keyboard correctly.
    def _setup_tools(self):
        @self.mcp.tool()
        async def get_screen_state() -> ScreenState:
            """Get current state of visible UI elements"""
            logger.info("Tool: get_screen_state called")
            await self._visual_state.update()  # Ensure state is fresh
            return ScreenState(
                elements=self._visual_state.elements,
                dimensions=self._visual_state.screen_dimensions or (0, 0),
                timestamp=self._visual_state.timestamp or time.time(),
            )

        @self.mcp.tool()
        async def describe_element(description: str) -> str:
            """Get rich description of UI element"""
            # Update visual state
            await self._visual_state.update()

            # Find element
            element = self._visual_state.find_element(description)
            if not element:
                return f"No element found matching: {description}"

            # Generate basic description for now
            # TODO: Enhance with Claude's description
            return (
                f"Found {element.type} with content '{element.content}' "
                f"at position {element.bounds}"
            )

        @self.mcp.tool()
        async def find_elements(query: str, max_results: int = 5) -> List[UIElement]:
            """Find elements matching natural query"""
            # Update visual state
            await self._visual_state.update()

            # For now, use simple matching
            # TODO: Enhance with semantic search
            matching_elements = []
            for element in self._visual_state.elements:
                if any(
                    word in element.content.lower() for word in query.lower().split()
                ):
                    matching_elements.append(element)
                    if len(matching_elements) >= max_results:
                        break

            return matching_elements

        @self.mcp.tool()
        async def click_element(
            description: str,
            click_type: Literal["single", "double", "right"] = "single",
        ) -> InteractionResult:
            """Click UI element matching description"""
            logger.info(f"Tool: click_element '{description}' (type: {click_type})")
            await self._visual_state.update()
            element = self._visual_state.find_element(description)
            if not element:
                logger.error(f"Element not found for click: {description}")
                return InteractionResult(
                    success=False,
                    element=None,
                    error=f"Element not found: {description}",
                )

            before_screenshot = self._visual_state._last_screenshot
            logger.info(f"Attempting {click_type} click on element ID {element.id}")
            success = False  # Default to failure
            try:
                if self._visual_state.screen_dimensions:
                    w, h = self._visual_state.screen_dimensions
                    # Calculate center absolute coordinates
                    abs_x = int((element.bounds[0] + element.bounds[2] / 2) * w)
                    abs_y = int((element.bounds[1] + element.bounds[3] / 2) * h)
                    self._mouse.move(abs_x, abs_y)
                    time.sleep(0.1)  # Short pause after move

                    # Perform the click using MouseController
                    if click_type == "single":
                        self._mouse.click(button="left")
                    # NOTE: pynput controller doesn't have double_click directly, needs two clicks
                    elif click_type == "double":
                        self._mouse.click(button="left")
                        time.sleep(0.05)
                        self._mouse.click(button="left")
                    elif click_type == "right":
                        self._mouse.click(button="right")
                    success = True
                    logger.success(
                        f"Performed {click_type} click at ({abs_x}, {abs_y})"
                    )
                else:
                    logger.error(
                        "Screen dimensions unknown, cannot calculate click coordinates."
                    )
                    success = False
            except Exception as click_e:
                logger.error(f"Click action failed: {click_e}", exc_info=True)
                success = False

            time.sleep(0.5)  # Wait for UI to potentially react
            await self._visual_state.update()  # Update state *after* action
            verification = await self._verify_action(
                before_screenshot, self._visual_state._last_screenshot, element.bounds
            )

            return InteractionResult(
                success=success,
                element=element,
                verification=verification,
                error="Click failed" if not success else None,
            )

        @self.mcp.tool()
        async def scroll_view(
            direction: Literal["up", "down", "left", "right"], amount: float
        ) -> ScrollResult:
            """Scroll in specified direction"""
            # Update visual state
            await self._visual_state.update()

            # Take before screenshot for verification
            before_screenshot = self._visual_state._last_screenshot

            # TODO: Implement scroll using input controller
            # For now, just log
            logger.info(f"Scroll {direction} by {amount}")

            # Update visual state after action
            await self._visual_state.update()

            # Verify action
            verification = self._verify_action(
                before_screenshot, self._visual_state._last_screenshot
            )

            return ScrollResult(
                success=True,
                element=None,
                scroll_amount=amount,
                verification=verification,
            )

        @self.mcp.tool()
        async def type_text(text: str, target: Optional[str] = None) -> TypeResult:
            """Type text, optionally clicking a target element first"""
            logger.info(
                f"Tool: type_text '{text[:20]}...' (target: {target})"
            )  # Log safely
            await self._visual_state.update()

            element = None
            # If target specified, try to click it
            if target:
                logger.info(f"Clicking target '{target}' before typing...")
                # Assuming click_element is another tool defined within _setup_tools
                # It needs to be defined *before* type_text or accessible
                # We might need to make click_element a helper method if called internally like this,
                # or ensure tools can call other tools via the mcp instance (less common).
                # Let's assume for now click_element is available/works.
                try:
                    # NOTE: Calling another tool directly like this might bypass MCP processing.
                    # A better pattern might be needed later if full MCP context is required for the click.
                    # For now, assume it resolves to the click logic.
                    click_result = await click_element(target, click_type="single")
                    if not click_result.success:
                        logger.error(
                            f"Failed to click target '{target}': {click_result.error}"
                        )
                        return TypeResult(
                            success=False,
                            element=None,
                            error=f"Failed to click target: {target}",
                            text_entered="",
                        )
                    element = click_result.element
                    time.sleep(0.2)  # Pause after click before typing
                except NameError:
                    logger.error(
                        "click_element tool was called before it was defined in _setup_tools."
                    )
                    return TypeResult(
                        success=False,
                        element=None,
                        error="Internal error: click_element not ready",
                        text_entered="",
                    )
                except Exception as click_err:
                    logger.error(
                        f"Error during pre-type click on '{target}': {click_err}",
                        exc_info=True,
                    )
                    return TypeResult(
                        success=False,
                        element=None,
                        error=f"Error clicking target: {target}",
                        text_entered="",
                    )

            # Store state just before typing
            before_screenshot = self._visual_state._last_screenshot
            logger.info(f"Attempting to type text: '{text[:20]}...'")
            success = False  # Default to failure
            try:
                # Use the synchronous type method from the KeyboardController
                self._keyboard.type(text)
                success = True
                logger.success("Text typed successfully via KeyboardController.")
            except Exception as type_e:
                logger.error(f"Typing action failed: {type_e}", exc_info=True)
                success = False

            # Wait slightly for UI to potentially react after typing
            time.sleep(0.5)
            await self._visual_state.update()  # Update state *after* action

            # Verify action (using placeholder verification for now)
            verification = await self._verify_action(
                before_screenshot, self._visual_state._last_screenshot
            )

            return TypeResult(
                success=success,
                element=element,  # The element that was clicked (if any)
                text_entered=text if success else "",
                verification=verification,
                error="Typing failed" if not success else None,
            )

        @self.mcp.tool()
        async def press_key(key: str, modifiers: List[str] = None) -> InteractionResult:
            """Press keyboard key with optional modifiers"""
            logger.info(f"Tool: press_key '{key}' (modifiers: {modifiers})")
            await self._visual_state.update()  # Update state first
            before_screenshot = self._visual_state._last_screenshot
            success = False
            try:
                # Simple key press, ignores modifiers for now (add later if needed)
                if modifiers:
                    logger.warning(
                        "Modifier handling in press_key tool not implemented."
                    )
                self._keyboard.press(key)  # Use the keyboard controller's press method
                success = True
                logger.success(f"Key '{key}' pressed successfully.")
            except Exception as press_e:
                logger.error(f"Key press action failed: {press_e}", exc_info=True)
                success = False

            time.sleep(0.5)  # Wait for UI reaction
            await self._visual_state.update()
            verification = await self._verify_action(
                before_screenshot, self._visual_state._last_screenshot
            )

            return InteractionResult(
                success=success,
                element=None,
                context={"key": key, "modifiers": modifiers or []},
                verification=verification,
                error="Key press failed" if not success else None,
            )

    async def _verify_action(
        self, before_image, after_image, element_bounds=None, action_description=None
    ) -> Optional[ActionVerification]:  # Added Optional type hint
        """Verify action success (basic pixel diff implementation)."""
        # TODO: Use Claude Vision API to verify action success
        # Implementation steps:
        # 1. Prepare a prompt that describes the action performed (click, type, etc.)
        # 2. Send the before image, after image, and optionally the diff image to Claude
        # 3. Ask Claude to analyze whether the action was successful by examining UI changes
        # 4. Parse Claude's response to determine success/failure and confidence level
        # 5. Extract any additional context about the changes from Claude's response
        # Example prompt: "I performed [action_description]. Analyze the before and after
        # screenshots and tell me if the action was successful."
        logger.debug("Verifying action using pixel difference...")
        # NOTE: Returns None only on input error, otherwise ActionVerification instance
        if not before_image or not after_image:
            logger.warning("Cannot verify action, missing before or after image.")
            return ActionVerification(
                success=False,
                confidence=0.0,
                changes_detected=[],
                before_state=None,
                after_state=None,
            )

        try:
            # Generate diff image
            diff_image = compute_diff(before_image, after_image)
            diff_array = np.array(diff_image)

            # Basic pixel change detection parameters
            change_threshold = 30  # Pixel value difference
            min_changed_pixels = (
                50  # Minimum number of changed pixels to consider "success"
            )

            changes = 0
            # Default to checking whole image size unless ROI is valid
            total_pixels_in_roi = diff_array.size if diff_array.size > 0 else 1

            # Focus on bounds if provided and valid
            if element_bounds and self.screen_dimensions:
                img_width, img_height = self.screen_dimensions
                # Calculate absolute coordinates, clamped to image dimensions
                x0 = max(0, int(element_bounds[0] * img_width))
                y0 = max(0, int(element_bounds[1] * img_height))
                x1 = min(
                    img_width, int((element_bounds[0] + element_bounds[2]) * img_width)
                )
                y1 = min(
                    img_height,
                    int((element_bounds[1] + element_bounds[3]) * img_height),
                )

                if x1 > x0 and y1 > y0:  # Check if roi is valid
                    roi = diff_array[y0:y1, x0:x1]
                    if roi.size > 0:
                        changes = np.sum(roi > change_threshold)
                        total_pixels_in_roi = roi.size
                    else:  # ROI is valid but has zero size? Should not happen if w,h > 0
                        changes = 0
                else:
                    logger.warning(
                        f"Invalid element bounds {element_bounds} resulted in invalid ROI [{x0}:{x1}, {y0}:{y1}]. Checking whole image."
                    )
                    # Fall back to checking whole image if ROI is invalid
                    changes = np.sum(diff_array > change_threshold)
            else:
                # Check changes in the whole image if no bounds or screen dimensions
                changes = np.sum(diff_array > change_threshold)

            # Determine success based on numpy comparison
            success_np = changes > min_changed_pixels
            # --- CAST TO PYTHON BOOL ---
            success = bool(success_np)
            # --- END CAST ---

            # Simple confidence calculation
            confidence = (
                min(1.0, changes / max(1, total_pixels_in_roi * 0.001))
                if success
                else 0.0
            )
            logger.info(
                f"Action verification: Changed pixels={changes}, Success={success}, Confidence={confidence:.2f}"
            )

            # Convert images to bytes (optional, can omit if not needed downstream)
            # before_bytes = io.BytesIO(); before_image.save(before_bytes, format="PNG")
            # after_bytes = io.BytesIO(); after_image.save(after_bytes, format="PNG")

            return ActionVerification(
                success=success,  # Use Python bool here
                before_state=None,  # before_bytes.getvalue() if needed
                after_state=None,  # after_bytes.getvalue() if needed
                changes_detected=[element_bounds] if element_bounds else [],
                confidence=float(confidence),
            )
        except Exception as e:
            logger.error(f"Error during action verification: {e}", exc_info=True)
            # Return failure on error
            return ActionVerification(
                success=False,
                confidence=0.0,
                changes_detected=[],
                before_state=None,
                after_state=None,
            )

    async def start(self, port: int = 8000):
        """Start MCP server"""
        logger.info(f"Starting OmniMCP server on port {port}")
        await self.mcp.serve(port=port)


if __name__ == "__main__":
    # This allows running the MCP server directly, e.g., python -m omnimcp.omnimcp
    # Configuration (API keys, AWS keys from .env) is loaded when OmniMCP is initialized.
    try:
        server = OmniMCP()
        # Start the FastMCP server loop using asyncio.run()
        # Listen on 0.0.0.0 to be accessible from network if needed, not just localhost.
        asyncio.run(server.start(host="0.0.0.0", port=8000))
    except RuntimeError as init_error:
        # Catch specific runtime errors from OmniMCP/Client initialization
        logger.critical(f"OmniMCP Server initialization failed: {init_error}")
        # Exit with error code
        import sys

        sys.exit(1)
    except KeyboardInterrupt:
        logger.info("OmniMCP Server stopped by user.")
    except Exception as main_e:
        # Catch any other unexpected errors during startup
        logger.critical(
            f"An unexpected error occurred starting the OmniMCP server: {main_e}",
            exc_info=True,
        )
        import sys

        sys.exit(1)
