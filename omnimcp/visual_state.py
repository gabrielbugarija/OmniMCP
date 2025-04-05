# omnimcp/visual_state.py

"""
Manages the perceived state of the UI using screenshots and OmniParser.
"""

import time
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image
from loguru import logger

# Assuming OmniParserClient is correctly importable from its location
from .omniparser.client import OmniParserClient
from .types import Bounds, UIElement
from .utils import take_screenshot


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
        """Maps the raw JSON output from OmniParser to UIElement objects."""
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
        """Converts a single item from OmniParser result to a UIElement."""
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

            # Validate and clamp bounds (0.0 to 1.0)
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
                    f"Skipping element (id={element_id}) invalid relative bounds: {item.get('content')} - Bounds: ({x:.3f}, {y:.3f}, {w:.3f}, {h:.3f})"
                )
                return None

            x, y = max(0.0, min(1.0, x)), max(0.0, min(1.0, y))
            w, h = max(0.0, min(1.0 - x, w)), max(0.0, min(1.0 - y, h))
            if w <= 0.0 or h <= 0.0:
                logger.warning(
                    f"Skipping element (id={element_id}) zero w/h after clamp: {item.get('content')}"
                )
                return None

            bounds: Bounds = (x, y, w, h)

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
        """Finds the best matching element using basic keyword matching."""
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
            # Simple scoring: 2 points for term in content, 1 for term in type
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
