# demo.py
"""
**To Run This:**

1.  **Save Files:** Place these files in the correct locations within your `omnimcp` project structure. Create `__init__.py` files in `omnimcp/` and `omnimcp/omniparser/` if they don't exist.
2.  **Install Dependencies:** Make sure you have `anthropic`, `pydantic`, `pillow`, `loguru`, `jinja2`, `python-dotenv` (add `python-dotenv>=1.0.0` to `pyproject.toml` dependencies if needed) installed (`pip install -e .` in the project root should handle this based on `pyproject.toml`).
3.  **Set API Key:** Create a `.env` file in the project root directory with your Anthropic API key:
    ```.env
    ANTHROPIC_API_KEY=your_anthropic_api_key_here
    ```
    Or set it as an environment variable.
4.  **Run:** Execute the demo script from the project's root directory:
    ```bash
    python demo.py
    ```

This implementation provides the core loop: generating a UI state (mocked), defining a goal, using an LLM with structured output (including reasoning) to plan an action, and visualizing the result by highlighting the target element. It's focused, uses existing utilities, and is achievable within a short timeframe.
"""

import os
from omnimcp.synthetic_ui import generate_login_screen, draw_highlight
from omnimcp.core import plan_action_for_ui
from omnimcp.utils import logger  # Use the configured logger

# --- Configuration ---
OUTPUT_DIR = "demo_output"
SAVE_IMAGES = True  # Set to False to just show image


def run_demo():
    """Runs the simplified OmniMCP demo."""
    logger.info("Starting OmniMCP Demo...")
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # 1. Generate Synthetic UI (Mock OmniParser)
    logger.info("Generating synthetic login screen...")
    img_path = os.path.join(OUTPUT_DIR, "login_screen.png") if SAVE_IMAGES else None
    image, elements = generate_login_screen(save_path=img_path)
    logger.info(f"Generated UI with {len(elements)} elements.")
    if SAVE_IMAGES:
        logger.info(f"Saved base image to {img_path}")
    else:
        image.show(title="Original UI")  # Show image if not saving

    # 2. Define User Goal
    user_goal = "Log in using username 'testuser' and password 'password123'"
    # user_goal = "Click the forgot password link"
    # user_goal = "Check the 'Remember Me' box"
    logger.info(f"User Goal: '{user_goal}'")

    # 3. Plan Action using LLM (Core Logic)
    logger.info("Planning action with LLM...")
    try:
        llm_plan, target_element = plan_action_for_ui(elements, user_goal)

        logger.info("--- LLM Action Plan ---")
        logger.info(f"Reasoning: {llm_plan.reasoning}")
        logger.info(f"Action: {llm_plan.action}")
        logger.info(f"Target Element ID: {llm_plan.element_id}")
        if llm_plan.text_to_type:
            logger.info(f"Text to Type: '{llm_plan.text_to_type}'")
        logger.info("-----------------------")

        if not target_element:
            logger.error("LLM chose an invalid element ID. Cannot visualize target.")
            return

        # 4. Visualize Result
        logger.info(
            f"Highlighting target element (ID: {target_element.id}) on image..."
        )
        highlighted_image = draw_highlight(image, target_element, color="lime", width=4)

        # Save or show the highlighted image
        highlight_img_path = os.path.join(OUTPUT_DIR, "login_screen_highlighted.png")
        if SAVE_IMAGES:
            highlighted_image.save(highlight_img_path)
            logger.info(f"Saved highlighted image to {highlight_img_path}")
        else:
            highlighted_image.show(
                title=f"Target: {llm_plan.action} on Element {target_element.id}"
            )

    except Exception as e:
        logger.error(f"Demo failed: {e}", exc_info=True)

    logger.info("Demo finished.")


if __name__ == "__main__":
    # Ensure you have ANTHROPIC_API_KEY set in your environment or a .env file
    # Example: export ANTHROPIC_API_KEY='your_key_here'
    # Or create a .env file in the project root:
    # ANTHROPIC_API_KEY=your_key_here
    run_demo()
