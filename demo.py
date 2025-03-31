# demo.py

"""
Multi-step demo using VisualState (real screenshot/parser/mapper)
and Core LLM Planner, but still using Simulation for state transitions.
"""

from typing import List
import argparse
import os
import time
import asyncio
import sys  # For sys.exit

# Import necessary components
from omnimcp.omniparser.client import (
    OmniParserClient,
)  # Needed to init VisualState indirectly
from omnimcp.omnimcp import VisualState  # Handles screenshot, parse, map
from omnimcp.core import plan_action_for_ui  # The LLM planner
from omnimcp.synthetic_ui import draw_highlight
from omnimcp.utils import (
    logger,
    MouseController,
    KeyboardController,
)  # Added controllers and coord helper
from omnimcp.config import config

# --- Configuration ---
OUTPUT_DIR = "demo_output_real_planner"
SAVE_IMAGES = True
MAX_STEPS = 6


async def run_real_planner_demo(
    user_goal: str = "Open a browser and check the weather",
):
    """Runs the demo integrating real perception->planning->action."""
    logger.info("--- Starting OmniMCP Demo: Real Perception -> Planner -> ACTION ---")
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # 1. Initialize Client, State Manager, and Controllers
    if not config.ANTHROPIC_API_KEY:
        logger.error("ANTHROPIC_API_KEY not found in config. Cannot run planner.")
        return False
    logger.info("Initializing OmniParserClient, VisualState, and Controllers...")
    try:
        parser_client = OmniParserClient(
            server_url=config.OMNIPARSER_URL, auto_deploy=(not config.OMNIPARSER_URL)
        )
        visual_state = VisualState(parser_client=parser_client)
        mouse_controller = MouseController()
        keyboard_controller = KeyboardController()
        logger.success(
            f"Client, VisualState, Controllers initialized. Parser URL: {parser_client.server_url}"
        )
    except Exception as e:
        logger.error(f"Initialization failed: {e}", exc_info=True)
        return False

    # 2. Use the provided User Goal
    logger.info(f"User Goal: '{user_goal}'")

    action_history: List[str] = []
    goal_achieved = False

    # --- Main Loop ---
    for step in range(MAX_STEPS):
        logger.info(f"\n--- Step {step + 1}/{MAX_STEPS} ---")
        step_start_time = time.time()

        # 3. Get CURRENT REAL State (Screenshot -> Parse -> Map)
        logger.info("Getting current screen state...")
        try:
            await visual_state.update()
            if not visual_state.elements:
                logger.warning(
                    f"No elements mapped from screen state at step {step + 1}. Trying again or stopping?"
                )
                # Optionally add a retry or break condition here
                if step > 0:  # Don't stop on first step necessarily
                    logger.error("Failed to get elements after first step. Stopping.")
                    break
                else:  # Allow maybe one failure on init
                    time.sleep(1)
                    continue  # Skip to next iteration hoping UI stabilizes
            # Use the latest real state
            current_image = visual_state._last_screenshot
            current_elements = visual_state.elements
            logger.info(
                f"Current state captured with {len(current_elements)} elements."
            )
        except Exception as e:
            logger.error(f"Failed to get visual state: {e}", exc_info=True)
            break  # Stop loop if state update fails

        # Save current state image
        current_state_img_path = os.path.join(OUTPUT_DIR, f"step_{step}_state.png")
        if SAVE_IMAGES and current_image:
            try:
                current_image.save(current_state_img_path)
                logger.info(f"Saved current state to {current_state_img_path}")
            except Exception as save_e:
                logger.warning(f"Could not save step state image: {save_e}")

        # 4. Plan Next Action using LLM Planner
        logger.info("Planning action with LLM...")
        try:
            llm_plan, target_element_from_plan = (
                plan_action_for_ui(  # Note: plan_action_for_ui returns element obj too
                    elements=current_elements,
                    user_goal=user_goal,
                    action_history=action_history,
                )
            )
            logger.info(f"LLM Reasoning: {llm_plan.reasoning}")
            logger.info(
                f"LLM Proposed Action: {llm_plan.action} on Element ID: {llm_plan.element_id}"
            )
            if llm_plan.text_to_type:
                logger.info(f"Text to Type: '{llm_plan.text_to_type}'")
            logger.info(f"LLM Goal Complete Assessment: {llm_plan.is_goal_complete}")

            # Ensure we have the target element object
            target_element = next(
                (el for el in current_elements if el.id == llm_plan.element_id), None
            )
            if target_element is None and not llm_plan.is_goal_complete:
                logger.error(
                    f"LLM chose element ID {llm_plan.element_id}, but it wasn't found. Stopping."
                )
                break

        except Exception as plan_e:
            logger.error(f"Error during LLM planning: {plan_e}", exc_info=True)
            break

        # 5. Check for Goal Completion BEFORE acting
        if llm_plan.is_goal_complete:
            logger.success("LLM determined the goal is achieved!")
            goal_achieved = True
            break  # Exit loop if goal achieved

        # Ensure we have a target element if goal not complete
        if target_element is None:
            logger.error(
                f"LLM did not indicate goal complete, but target element {llm_plan.element_id} is missing. Stopping."
            )
            break

        # 6. Visualize Planned Action
        if SAVE_IMAGES and current_image:
            highlight_img_path = os.path.join(OUTPUT_DIR, f"step_{step}_highlight.png")
            try:
                highlighted_image = draw_highlight(
                    current_image, target_element, plan=llm_plan
                )
                highlighted_image.save(highlight_img_path)
                logger.info(f"Saved highlighted action to {highlight_img_path}")
            except Exception as draw_e:
                logger.warning(f"Could not save highlight image: {draw_e}")

        # Record action for history BEFORE execution
        action_desc = f"Step {step + 1}: Planned {llm_plan.action}"
        if llm_plan.text_to_type:
            action_desc += f" '{llm_plan.text_to_type[:20]}...'"
        action_desc += (
            f" on Element ID {target_element.id} ('{target_element.content[:30]}...')"
        )
        action_history.append(action_desc)

        # --- 7. Execute REAL Action ---
        logger.info(
            f"Executing action: {llm_plan.action} on element {target_element.id}"
        )
        action_success = False
        try:
            if visual_state.screen_dimensions is None:
                logger.error("Cannot execute action: screen dimensions unknown.")
                break

            screen_w, screen_h = visual_state.screen_dimensions
            # Calculate center absolute coordinates for clicks
            abs_x = int(
                (target_element.bounds[0] + target_element.bounds[2] / 2) * screen_w
            )
            abs_y = int(
                (target_element.bounds[1] + target_element.bounds[3] / 2) * screen_h
            )

            if llm_plan.action == "click":
                mouse_controller.move(abs_x, abs_y)
                time.sleep(0.1)  # Small pause
                mouse_controller.click()
                action_success = True
                logger.success(f"Executed click at ({abs_x}, {abs_y})")
            elif llm_plan.action == "type":
                if llm_plan.text_to_type is not None:
                    # Click target first to focus (optional but often needed)
                    logger.info(
                        f"Clicking element {target_element.id} before typing..."
                    )
                    mouse_controller.move(abs_x, abs_y)
                    time.sleep(0.1)
                    mouse_controller.click()
                    time.sleep(0.2)  # Wait after click
                    # Type the text
                    logger.info(f"Typing text: '{llm_plan.text_to_type[:20]}...'")
                    keyboard_controller.type(llm_plan.text_to_type)
                    action_success = True
                    logger.success("Executed type action.")
                else:
                    logger.warning("LLM planned 'type' action but provided no text.")
                    action_success = False  # Treat as failure if no text
            elif llm_plan.action == "scroll":
                # Basic scroll implementation (adjust direction/amount as needed)
                scroll_amount = 5  # Example: Scroll down 5 units
                scroll_x, scroll_y = 0, -scroll_amount
                logger.info(f"Scrolling down by {scroll_amount} units...")
                mouse_controller.scroll(scroll_x, scroll_y)
                action_success = True
                logger.success("Executed scroll action.")
            else:
                logger.warning(f"Action type '{llm_plan.action}' not implemented.")
                action_success = False

            if not action_success:
                logger.error("Action execution step failed.")
                # Decide if loop should break on action failure
                # break

        except Exception as exec_e:
            logger.error(f"Error during action execution: {exec_e}", exc_info=True)
            break  # Stop loop on execution error

        # --- REMOVED SIMULATION BLOCK ---

        # Wait for UI to settle after action before next state capture
        time.sleep(1.5)  # Increased wait time after real action
        logger.info(f"Step {step + 1} duration: {time.time() - step_start_time:.2f}s")
        # Loop continues, will call visual_state.update() at the start of the next iteration

    # --- End of Loop ---
    logger.info("\n--- Demo Finished ---")
    if goal_achieved:
        logger.success("Overall goal marked as achieved by LLM during execution.")
    elif step == MAX_STEPS - 1:
        logger.warning(
            f"Reached maximum steps ({MAX_STEPS}) without goal completion flag being set."
        )
    else:
        logger.error("Execution stopped prematurely (check logs).")

    # Save final state (which will be the last simulated state)
    final_state_img_path = os.path.join(OUTPUT_DIR, "final_state.png")
    if SAVE_IMAGES and current_image:
        try:
            current_image.save(final_state_img_path)
            logger.info(f"Saved final simulated state to {final_state_img_path}")
        except Exception as save_e:
            logger.warning(f"Could not save final state image: {save_e}")

    logger.info(
        "Reminder: Run 'python omnimcp/omniparser/server.py stop' to shut down the EC2 instance if it was deployed."
    )

    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Run OmniMCP demo with a specific goal."
    )
    parser.add_argument(
        "user_goal",
        nargs="?",
        default=None,
        help="The natural language goal (optional).",
    )
    args = parser.parse_args()
    cli_goal = args.user_goal

    if not config.ANTHROPIC_API_KEY:
        print("ERROR: ANTHROPIC_API_KEY not found. Exiting.")
        sys.exit(1)

    # --- WARNING ---
    print("\n" + "=" * 50)
    print(" WARNING: This script will take control of your mouse and keyboard!")
    print(" Please ensure no sensitive information is visible.")
    print(" To stop execution, move your mouse to a screen corner or press Ctrl+C.")
    print("=" * 50 + "\n")
    # Add a countdown
    for i in range(5, 0, -1):
        print(f"Starting in {i}...", end="\r")
        time.sleep(1)
    print("Starting now!       ")
    # --- END WARNING ---

    # Run the async main function
    success = False
    if cli_goal:
        logger.info(f"Using user goal from command line: '{cli_goal}'")
        # Pass goal to the async function correctly
        success = asyncio.run(run_real_planner_demo(user_goal=cli_goal))
    else:
        logger.info("No goal provided on command line, using default goal.")
        # Call without user_goal kwarg to use the function's default
        success = asyncio.run(run_real_planner_demo())

    if not success:
        sys.exit(1)
