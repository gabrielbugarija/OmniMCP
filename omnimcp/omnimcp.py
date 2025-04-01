# omnimcp/omnimcp.py

"""
OmniMCP: High-level UI automation interface using visual perception.

Provides VisualState for perception and an optional MCP server (OmniMCP)
for tool-based interaction.
"""

from typing import Any, Dict, List, Literal, Optional, Tuple
import asyncio
import sys
import time

import numpy as np
from mcp.server.fastmcp import FastMCP
from loguru import logger
from PIL import Image

# --- Updated Imports ---
from omnimcp.omniparser.client import OmniParserClient
from omnimcp.input import InputController  # Import the unified controller
from omnimcp.utils import (
    take_screenshot,
    compute_diff,
    denormalize_coordinates,  # Need this for click tool
    # Removed MouseController, KeyboardController imports
)
from omnimcp.types import (
    Bounds,  # Assuming this is Tuple[float, float, float, float]
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
        """Initialize the visual state manager."""
        self.elements: List[UIElement] = []
        self.timestamp: Optional[float] = None
        self.screen_dimensions: Optional[Tuple[int, int]] = None
        self._last_screenshot: Optional[Image.Image] = None
        self._parser_client = parser_client
        if not self._parser_client:
            logger.critical("VisualState initialized without a valid parser_client!")
            raise ValueError("VisualState requires a valid OmniParserClient instance.")
        logger.info("VisualState initialized.")

    # --- Made update synchronous ---
    def update(self) -> None:
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
                logger.error(
                    "OmniParser client server URL not available. Cannot parse."
                )
                self.elements = []
                self.timestamp = time.time()
                return

            logger.debug(f"Parsing screenshot via {self._parser_client.server_url}...")
            parser_result = self._parser_client.parse_image(screenshot)

            # 3. Update elements list using the mapping logic
            logger.debug("Mapping parser results...")
            self._update_elements_from_parser(parser_result)
            self.timestamp = time.time()
            logger.info(
                f"VisualState update complete. Found {len(self.elements)} "
                f"elements. Took {time.time() - start_time:.2f}s."
            )

        except Exception as e:
            logger.error(f"Failed to update visual state: {e}", exc_info=True)
            self.elements = []
            self.timestamp = time.time()

    def _update_elements_from_parser(self, parser_json: Dict):
        # ... (implementation remains the same as before) ...
        new_elements: List[UIElement] = []
        element_id_counter = 0

        if not isinstance(parser_json, dict):
            logger.error(
                f"Parser result is not a dictionary: {type(parser_json)}. Cannot map."
            )
            self.elements = new_elements
            return
        if "error" in parser_json:
            logger.error(f"Parser returned an error: {parser_json['error']}")
            self.elements = new_elements
            return

        raw_elements: List[Dict[str, Any]] = parser_json.get("parsed_content_list", [])
        if not isinstance(raw_elements, list):
            logger.error(
                f"Expected 'parsed_content_list' to be a list, got: {type(raw_elements)}"
            )
            self.elements = new_elements
            return

        logger.debug(f"Mapping {len(raw_elements)} raw elements from OmniParser.")
        for item in raw_elements:
            ui_element = self._convert_to_ui_element(item, element_id_counter)
            if ui_element:
                new_elements.append(ui_element)
                element_id_counter += 1
        logger.debug(f"Successfully mapped {len(new_elements)} valid UIElements.")
        self.elements = new_elements

    def _convert_to_ui_element(
        self, item: Dict[str, Any], element_id: int
    ) -> Optional[UIElement]:
        # ... (implementation remains the same as before, including validation) ...
        try:
            if not isinstance(item, dict):
                logger.warning(f"Skipping non-dict item: {item}")
                return None

            bbox_rel = item.get("bbox")
            if not isinstance(bbox_rel, list) or len(bbox_rel) != 4:
                logger.debug(
                    f"Skipping element (id={element_id}) invalid/missing bbox: {item.get('content')}"
                )
                return None

            x_min, y_min, x_max, y_max = map(float, bbox_rel)
            x, y, w, h = x_min, y_min, x_max - x_min, y_max - y_min

            tolerance = 0.001
            if not (
                (-tolerance <= x <= 1.0 + tolerance)
                and (-tolerance <= y <= 1.0 + tolerance)
                and w > 0.0
                and h > 0.0
                and (x + w) <= 1.0 + tolerance
                and (y + h) <= 1.0 + tolerance
            ):
                logger.warning(
                    f"Skipping element (id={element_id}) invalid relative bounds: {item.get('content')}"
                )
                return None

            x, y = max(0.0, min(1.0, x)), max(0.0, min(1.0, y))
            w, h = max(0.0, min(1.0 - x, w)), max(0.0, min(1.0 - y, h))
            if w <= 0.0 or h <= 0.0:
                logger.warning(
                    f"Skipping element (id={element_id}) zero w/h after clamp: {item.get('content')}"
                )
                return None

            bounds: Bounds = (x, y, w, h)  # Type hint assumes Bounds is Tuple

            # Optional tiny element filter
            if self.screen_dimensions:
                img_width, img_height = self.screen_dimensions
                min_pixel_size = 3
                if (w * img_width < min_pixel_size) or (
                    h * img_height < min_pixel_size
                ):
                    logger.debug(
                        f"Skipping tiny element (id={element_id}): {item.get('content')}"
                    )
                    return None

            element_type = (
                str(item.get("type", "unknown")).lower().strip().replace(" ", "_")
            )
            content = str(item.get("content", "")).strip()

            return UIElement(
                id=element_id,
                type=element_type,
                content=content,
                bounds=bounds,
                confidence=float(item.get("confidence", 0.0)),
                attributes=item.get("attributes", {}) or {},
            )
        except (ValueError, TypeError, KeyError) as e:
            logger.warning(
                f"Skipping element (id={element_id}) mapping error: {item.get('content')} - {e}"
            )
            return None
        except Exception as unexpected_e:
            logger.error(
                f"Unexpected error mapping element (id={element_id}): {item.get('content')} - {unexpected_e}",
                exc_info=True,
            )
            return None

    def find_element(self, description: str) -> Optional[UIElement]:
        # ... (implementation remains the same as before) ...
        logger.debug(f"Finding element: '{description}' using basic matching.")
        if not self.elements:
            return None
        search_terms = [term for term in description.lower().split() if term]
        if not search_terms:
            return None

        best_match = None
        highest_score = 0
        for element in self.elements:
            content_lower = element.content.lower()
            type_lower = element.type.lower()
            score = sum(2 for term in search_terms if term in content_lower) + sum(
                1 for term in search_terms if term in type_lower
            )

            if score > highest_score:
                highest_score = score
                best_match = element

        if best_match:
            logger.info(
                f"Found best match (score={highest_score}) for '{description}': ID={best_match.id}"
            )
        else:
            logger.warning(
                f"No element found with positive match score for: '{description}'"
            )
        return best_match


class OmniMCP:
    """Model Context Protocol server for UI understanding and interaction."""

    def __init__(self, parser_url: Optional[str] = None, debug: bool = False):
        """Initialize the OmniMCP server."""
        logger.info(f"Initializing OmniMCP. Debug={debug}")
        try:
            self._parser_client = OmniParserClient(
                server_url=parser_url, auto_deploy=(parser_url is None)
            )
            logger.success("OmniParserClient initialized successfully.")
        except Exception as client_init_e:
            logger.critical(
                f"Failed to initialize OmniParserClient: {client_init_e}", exc_info=True
            )
            raise RuntimeError(
                "OmniMCP cannot start without OmniParserClient"
            ) from client_init_e

        # --- Use unified InputController ---
        try:
            self._controller = InputController()
            logger.info("InputController initialized.")
        except ImportError as e:
            logger.critical(
                f"Failed to initialize InputController: {e}. Is pynput installed?"
            )
            raise RuntimeError("OmniMCP cannot start without InputController") from e
        except Exception as controller_init_e:
            logger.critical(
                f"Failed to initialize InputController: {controller_init_e}",
                exc_info=True,
            )
            raise RuntimeError(
                "OmniMCP cannot start without InputController"
            ) from controller_init_e

        self._visual_state = VisualState(parser_client=self._parser_client)
        self._debug = debug
        self._debug_context = None

        self.mcp = FastMCP("omnimcp")  # Initialize MCP server
        self._setup_tools()  # Register tools
        logger.info("OmniMCP initialization complete. Tools registered.")

    def _setup_tools(self):
        """Register MCP tools for UI interaction."""

        @self.mcp.tool()
        def get_screen_state() -> ScreenState:
            """Get current state of visible UI elements."""
            logger.info("Tool: get_screen_state called")
            self._visual_state.update()  # Now synchronous
            return ScreenState(
                elements=self._visual_state.elements,
                dimensions=self._visual_state.screen_dimensions or (0, 0),
                timestamp=self._visual_state.timestamp or time.time(),
            )

        @self.mcp.tool()
        def describe_element(description: str) -> str:
            """Get rich description of UI element (Basic implementation)."""
            logger.info(f"Tool: describe_element '{description}'")
            self._visual_state.update()  # Now synchronous
            element = self._visual_state.find_element(description)
            if not element:
                return f"No element found matching: {description}"
            # TODO: Enhance with more detail or LLM description
            return f"Found {element.type} with content '{element.content}' at bounds {element.bounds}"

        @self.mcp.tool()
        def find_elements(query: str, max_results: int = 5) -> List[UIElement]:
            """Find elements matching natural query (Basic implementation)."""
            logger.info(f"Tool: find_elements '{query}' (max: {max_results})")
            self._visual_state.update()  # Now synchronous
            # Basic matching, TODO: Enhance
            matching_elements = []
            for element in self._visual_state.elements:
                if any(
                    word in element.content.lower() for word in query.lower().split()
                ):
                    matching_elements.append(element)
                    if len(matching_elements) >= max_results:
                        break
            logger.info(f"Found {len(matching_elements)} elements matching query.")
            return matching_elements

        @self.mcp.tool()
        def click_element(
            description: str,
            click_type: Literal["single", "double", "right"] = "single",
        ) -> InteractionResult:
            """Click UI element matching description."""
            logger.info(f"Tool: click_element '{description}' (type: {click_type})")
            self._visual_state.update()  # Now synchronous
            element = self._visual_state.find_element(description)
            if not element:
                logger.error(f"Element not found for click: {description}")
                return InteractionResult(
                    success=False,
                    element=None,
                    error=f"Element not found: {description}",
                )

            before_screenshot = (
                self._visual_state._last_screenshot
            )  # Capture state before action
            logger.info(f"Attempting {click_type} click on element ID {element.id}")
            success = False
            error_msg = None
            try:
                if self._visual_state.screen_dimensions:
                    w, h = self._visual_state.screen_dimensions
                    # Denormalize here to get absolute coords for InputController
                    abs_x, abs_y = denormalize_coordinates(
                        element.bounds[0],
                        element.bounds[1],
                        w,
                        h,
                        element.bounds[2],
                        element.bounds[3],  # Pass width/height for center click
                    )
                    # --- Use InputController ---
                    success = self._controller.click(
                        abs_x, abs_y, click_type=click_type
                    )
                    if not success:
                        error_msg = (
                            f"InputController failed to perform {click_type} click."
                        )
                else:
                    error_msg = (
                        "Screen dimensions unknown, cannot calculate click coordinates."
                    )
                    success = False
            except Exception as click_e:
                logger.error(f"Click action failed: {click_e}", exc_info=True)
                success = False
                error_msg = f"Exception during click: {click_e}"

            time.sleep(0.5)  # Wait for UI reaction
            self._visual_state.update()  # Update state *after* action
            verification = self._verify_action(  # Now synchronous
                before_screenshot, self._visual_state._last_screenshot, element.bounds
            )

            return InteractionResult(
                success=success,
                element=element,
                verification=verification,
                error=error_msg if not success else None,
            )

        @self.mcp.tool()
        def scroll_view(
            direction: Literal["up", "down", "left", "right"],
            amount: int = 1,  # Amount could be steps/pixels
        ) -> ScrollResult:
            """Scroll view in the specified direction by a relative amount/steps."""
            logger.info(f"Tool: scroll_view '{direction}' (amount: {amount})")
            # Note: amount interpretation depends on the OS and pynput implementation
            # Usually it's 'units' or 'clicks', not precise pixels. Let's use small steps.
            scroll_steps = amount * 2  # Convert abstract amount to scroll steps
            dx = 0
            dy = 0
            if direction == "up":
                dy = scroll_steps
            elif direction == "down":
                dy = -scroll_steps
            elif direction == "left":
                dx = -scroll_steps
            elif direction == "right":
                dx = scroll_steps

            before_screenshot = (
                self._visual_state._last_screenshot
            )  # Get state before scroll
            success = False
            error_msg = None
            if dx != 0 or dy != 0:
                try:
                    # --- Use InputController ---
                    success = self._controller.scroll(dx, dy)
                    if not success:
                        error_msg = "InputController failed to scroll."
                except Exception as scroll_e:
                    logger.error(f"Scroll action failed: {scroll_e}", exc_info=True)
                    success = False
                    error_msg = f"Exception during scroll: {scroll_e}"
            else:
                logger.warning(
                    "Scroll direction resulted in zero delta, skipping scroll."
                )
                success = True  # No action needed counts as success here

            time.sleep(0.5)  # Wait for scroll effect
            self._visual_state.update()
            verification = self._verify_action(
                before_screenshot, self._visual_state._last_screenshot
            )

            return ScrollResult(
                success=success,
                element=None,
                scroll_amount=float(amount),
                verification=verification,
                error=error_msg if not success else None,
            )

        @self.mcp.tool()
        def type_text(text: str, target: Optional[str] = None) -> TypeResult:
            """Type text, optionally clicking a target element first."""
            logger.info(f"Tool: type_text '{text[:20]}...' (target: {target})")
            self._visual_state.update()  # Update state first

            element = None
            # Click target if specified
            if target:
                logger.info(f"Clicking target '{target}' before typing...")
                # Call the click_element tool/logic (potential issue noted before remains)
                click_result = click_element(target, click_type="single")
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
                time.sleep(0.2)  # Pause after click

            before_screenshot = self._visual_state._last_screenshot
            logger.info(f"Attempting to type text: '{text[:20]}...'")
            success = False
            error_msg = None
            try:
                # --- Use InputController ---
                success = self._controller.type_text(text)
                if not success:
                    error_msg = "InputController failed to type text."
            except Exception as type_e:
                logger.error(f"Typing action failed: {type_e}", exc_info=True)
                success = False
                error_msg = f"Exception during typing: {type_e}"

            time.sleep(0.5)  # Wait for UI reaction
            self._visual_state.update()
            verification = self._verify_action(
                before_screenshot, self._visual_state._last_screenshot
            )

            return TypeResult(
                success=success,
                element=element,
                text_entered=text if success else "",
                verification=verification,
                error=error_msg if not success else None,
            )

        @self.mcp.tool()
        def press_key(key_info: str) -> InteractionResult:
            """
            Press a key or key combination described by a string (e.g., "Enter", "Cmd+C").
            """
            logger.info(f"Tool: press_key '{key_info}'")
            # No visual state update needed before simple key press usually
            before_screenshot = (
                self._visual_state._last_screenshot
            )  # Still capture for verification
            success = False
            error_msg = None
            try:
                # --- Use InputController's parsing method ---
                success = self._controller.execute_key_string(key_info)
                if not success:
                    error_msg = (
                        f"InputController failed to execute key string: {key_info}"
                    )
            except Exception as press_e:
                logger.error(
                    f"Key press action failed for '{key_info}': {press_e}",
                    exc_info=True,
                )
                success = False
                error_msg = f"Exception during key press for '{key_info}': {press_e}"

            time.sleep(0.5)  # Wait for UI reaction
            self._visual_state.update()  # Update after action
            verification = self._verify_action(
                before_screenshot, self._visual_state._last_screenshot
            )

            return InteractionResult(
                success=success,
                element=None,
                context={"key_info": key_info},
                verification=verification,
                error=error_msg if not success else None,
            )

    # --- Made verification synchronous ---
    def _verify_action(
        self, before_image, after_image, element_bounds=None, action_description=None
    ) -> Optional[ActionVerification]:
        """Verify action success (basic pixel diff implementation)."""
        logger.debug("Verifying action using pixel difference...")
        if not before_image or not after_image:
            logger.warning("Cannot verify action, missing before or after image.")
            # Return a failure verification object instead of None
            return ActionVerification(
                success=False,
                confidence=0.0,
                changes_detected=[],
                before_state=None,
                after_state=None,
            )

        try:
            diff_image = compute_diff(before_image, after_image)
            diff_array = np.array(diff_image)
            change_threshold = 30
            min_changed_pixels = 50
            changes = 0
            total_pixels_in_roi = diff_array.size if diff_array.size > 0 else 1

            if element_bounds and self.screen_dimensions:
                img_width, img_height = self.screen_dimensions
                x0 = max(0, int(element_bounds[0] * img_width))
                y0 = max(0, int(element_bounds[1] * img_height))
                x1 = min(
                    img_width, int((element_bounds[0] + element_bounds[2]) * img_width)
                )
                y1 = min(
                    img_height,
                    int((element_bounds[1] + element_bounds[3]) * img_height),
                )

                if x1 > x0 and y1 > y0:
                    roi = diff_array[y0:y1, x0:x1]
                    if roi.size > 0:
                        changes = np.sum(roi > change_threshold)
                        total_pixels_in_roi = roi.size
                    else:
                        changes = 0
                else:
                    logger.warning(
                        f"Invalid bounds {element_bounds} resulted in invalid ROI. Checking whole image."
                    )
                    changes = np.sum(diff_array > change_threshold)
            else:
                changes = np.sum(diff_array > change_threshold)

            success = bool(changes > min_changed_pixels)
            confidence = (
                min(1.0, changes / max(1, total_pixels_in_roi * 0.001))
                if success
                else 0.0
            )
            logger.info(
                f"Action verification: Changed pixels={changes}, Success={success}, Confidence={confidence:.2f}"
            )

            # Convert images to bytes only if needed downstream
            before_bytes, after_bytes = None, None
            # if SAVE_IMAGES or need_bytes_downstream:
            #     with io.BytesIO() as buf: before_image.save(buf, format="PNG"); before_bytes = buf.getvalue()
            #     with io.BytesIO() as buf: after_image.save(buf, format="PNG"); after_bytes = buf.getvalue()

            return ActionVerification(
                success=success,
                before_state=before_bytes,
                after_state=after_bytes,
                changes_detected=[element_bounds] if element_bounds else [],
                confidence=float(confidence),
            )
        except Exception as e:
            logger.error(f"Error during action verification: {e}", exc_info=True)
            return ActionVerification(
                success=False,
                confidence=0.0,
                changes_detected=[],
                before_state=None,
                after_state=None,
            )

    async def start(self, host: str = "127.0.0.1", port: int = 8000):
        """Start MCP server."""
        logger.info(f"Starting OmniMCP server on {host}:{port}")
        # FastMCP.serve is async
        await self.mcp.serve(host=host, port=port)


if __name__ == "__main__":
    # Allows running the MCP server directly: python -m omnimcp.omnimcp
    try:
        server = OmniMCP()
        # Start the FastMCP server loop using asyncio.run()
        asyncio.run(server.start(host="0.0.0.0", port=8000))  # Listen on all interfaces
    except RuntimeError as init_error:
        logger.critical(f"OmniMCP Server initialization failed: {init_error}")
        sys.exit(1)
    except KeyboardInterrupt:
        logger.info("OmniMCP Server stopped by user.")
    except Exception as main_e:
        logger.critical(
            f"Unexpected error starting OmniMCP server: {main_e}", exc_info=True
        )
        sys.exit(1)
