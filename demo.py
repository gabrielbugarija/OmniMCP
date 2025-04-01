# demo.py
"""
OmniMCP Demo: Real Perception -> LLM Planner -> Real Action Execution.
Saves detailed debug images for each step in timestamped directories.
"""

import platform
import os
import time
import sys
import datetime  # Import datetime
from typing import List, Optional

from PIL import Image
import fire

# Import necessary components from the project
from omnimcp.omniparser.client import OmniParserClient
from omnimcp.omnimcp import VisualState
from omnimcp.core import plan_action_for_ui, LLMActionPlan
from omnimcp.input import InputController
from omnimcp.utils import (
    logger,
    denormalize_coordinates,
    take_screenshot,
    draw_bounding_boxes,  # Import the new drawing function
    get_scaling_factor,
    draw_action_highlight,
)
from omnimcp.config import config
from omnimcp.types import UIElement


# --- Configuration ---
# OUTPUT_DIR is now dynamically created per run
# SAVE_IMAGES = True # Always save images in this version
MAX_STEPS = 10


def run_real_planner_demo(
    user_goal: str = "Open calculator and compute 5 * 9",
):
    """
    Runs the main OmniMCP demo loop: Perception -> Planning -> Action.
    Saves detailed debug images to images/{timestamp}/ folder.

    Args:
        user_goal: The natural language goal for the agent to achieve.

    Returns:
        True if the goal was achieved or max steps were reached without critical error,
        False otherwise.
    """
    run_timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    run_output_dir = os.path.join("images", run_timestamp)
    os.makedirs(run_output_dir, exist_ok=True)
    logger.info("--- Starting OmniMCP Demo ---")
    logger.info(f"Saving outputs to: {run_output_dir}")

    scaling_factor = get_scaling_factor()
    logger.info(f"Using display scaling factor: {scaling_factor}")

    # 1. Initialize Client, State Manager, and Controller
    if not config.ANTHROPIC_API_KEY:
        logger.error("ANTHROPIC_API_KEY not found in config. Cannot run planner.")
        return False  # Indicate failure
    logger.info("Initializing OmniParserClient, VisualState, and InputController...")
    try:
        parser_client = OmniParserClient(
            server_url=config.OMNIPARSER_URL, auto_deploy=(not config.OMNIPARSER_URL)
        )
        visual_state = VisualState(parser_client=parser_client)
        controller = InputController()
        logger.success(
            f"Client, VisualState, Controller initialized. Parser URL: {parser_client.server_url}"
        )
    except ImportError as e:
        logger.error(
            f"Initialization failed due to missing dependency: {e}. Is pynput or pyobjc installed?"
        )
        return False
    except Exception as e:
        logger.error(f"Initialization failed: {e}", exc_info=True)
        return False

    # 2. User Goal
    logger.info(f"User Goal: '{user_goal}'")

    action_history: List[str] = []
    goal_achieved = False
    # Tracks if loop broke due to error vs completing/reaching max steps
    final_step_success = True
    last_step_completed = -1  # Track the index of the last fully completed step

    # --- Main Loop ---
    for step in range(MAX_STEPS):
        logger.info(f"\n--- Step {step + 1}/{MAX_STEPS} ---")
        step_start_time = time.time()
        # Use 1-based index for user-friendly filenames
        step_img_prefix = f"step_{step + 1}"

        # 3. Get CURRENT REAL State (Screenshot -> Parse -> Map)
        logger.info("Getting current screen state...")
        current_image: Optional[Image.Image] = None
        current_elements: List[UIElement] = []
        try:
            visual_state.update()  # Synchronous update
            current_elements = visual_state.elements or []
            current_image = visual_state._last_screenshot

            if not current_image:
                logger.error("Failed to get screenshot for current state. Stopping.")
                final_step_success = False
                break  # Exit loop

            logger.info(
                f"Current state captured with {len(current_elements)} elements."
            )

            # Save Raw State Image
            raw_state_path = os.path.join(
                run_output_dir, f"{step_img_prefix}_state_raw.png"
            )
            try:
                current_image.save(raw_state_path)
                logger.info(f"Saved raw state to {raw_state_path}")
            except Exception as save_e:
                logger.warning(f"Could not save raw state image: {save_e}")

            # Save Parsed State Image (with bounding boxes)
            parsed_state_path = os.path.join(
                run_output_dir, f"{step_img_prefix}_state_parsed.png"
            )
            try:
                # Ensure draw_bounding_boxes is available
                img_with_boxes = draw_bounding_boxes(
                    current_image, current_elements, color="lime", show_ids=True
                )
                img_with_boxes.save(parsed_state_path)
                logger.info(f"Saved parsed state visualization to {parsed_state_path}")
            except NameError:
                logger.warning(
                    "draw_bounding_boxes function not found, cannot save parsed state image."
                )
            except Exception as draw_e:
                logger.warning(f"Could not save parsed state image: {draw_e}")

        except Exception as e:
            logger.error(f"Failed to get visual state: {e}", exc_info=True)
            final_step_success = False
            break  # Stop loop if state update fails

        # 4. Plan Next Action using LLM Planner
        logger.info("Planning action with LLM...")
        llm_plan: Optional[LLMActionPlan] = None
        target_element: Optional[UIElement] = None
        try:
            llm_plan, target_element = plan_action_for_ui(
                elements=current_elements,
                user_goal=user_goal,
                action_history=action_history,
                step=step,  # Pass 0-based step index for conditional logging
            )
            logger.info(f"LLM Reasoning: {llm_plan.reasoning}")
            logger.info(f"LLM Goal Complete Assessment: {llm_plan.is_goal_complete}")

        except Exception as plan_e:
            logger.error(f"Error during LLM planning: {plan_e}", exc_info=True)
            final_step_success = False
            break  # Stop loop if planning fails

        # 5. Check for Goal Completion BEFORE acting
        if llm_plan.is_goal_complete:
            logger.success("LLM determined the goal is achieved!")
            goal_achieved = True
            last_step_completed = step  # Mark this step as completed before breaking
            break  # Exit loop successfully

        # 6. Validate Target Element (Ensure click has a target)
        if llm_plan.action == "click" and target_element is None:
            logger.error(
                f"Action 'click' requires element ID {llm_plan.element_id}, but it was not found in the current state. Stopping."
            )
            final_step_success = False
            break  # Stop loop if required element is missing

        # 7. Visualize Planned Action (Highlight Target OR Annotate Action)
        if llm_plan and current_image:  # Check if we have a plan and image
            highlight_img_path = os.path.join(
                run_output_dir, f"{step_img_prefix}_action_highlight.png"
            )
            try:
                # Call the function - it handles None element internally
                highlighted_image = draw_action_highlight(
                    current_image,
                    target_element,  # Pass element (can be None)
                    plan=llm_plan,
                    color="red",
                    width=3,
                )
                highlighted_image.save(highlight_img_path)
                logger.info(f"Saved action visualization to {highlight_img_path}")
            except Exception as draw_e:
                logger.warning(f"Could not save action visualization image: {draw_e}")

        # Record action for history BEFORE execution
        action_desc = f"Step {step + 1}: Planned {llm_plan.action}"
        if target_element:
            action_desc += (
                f" on ID {target_element.id} ('{target_element.content[:30]}...')"
            )
        if llm_plan.text_to_type:
            action_desc += f" Text='{llm_plan.text_to_type[:20]}...'"
        if llm_plan.key_info:
            action_desc += f" Key='{llm_plan.key_info}'"
        action_history.append(action_desc)
        logger.debug(f"Added to history: {action_desc}")

        # 8. Execute REAL Action using InputController
        logger.info(f"Executing action: {llm_plan.action}...")
        action_success = False
        try:
            if visual_state.screen_dimensions is None:
                # Should not happen if screenshot was taken, but safety check
                raise RuntimeError("Cannot execute action: screen dimensions unknown.")
            # screen_w/h are physical pixel dimensions from screenshot
            screen_w, screen_h = visual_state.screen_dimensions

            if llm_plan.action == "click":
                if target_element:  # Validation already done
                    # Denormalize to get PHYSICAL PIXEL coordinates for center
                    abs_x, abs_y = denormalize_coordinates(
                        target_element.bounds[0],
                        target_element.bounds[1],
                        screen_w,
                        screen_h,
                        target_element.bounds[2],
                        target_element.bounds[3],
                    )
                    # Convert to LOGICAL points for pynput controller
                    logical_x = int(abs_x / scaling_factor)
                    logical_y = int(abs_y / scaling_factor)
                    logger.info(
                        f"Converted physical click ({abs_x},{abs_y}) to logical ({logical_x},{logical_y}) using factor {scaling_factor}"
                    )
                    action_success = controller.click(
                        logical_x, logical_y, click_type="single"
                    )
                # No else needed, already validated above

            elif llm_plan.action == "type":
                if llm_plan.text_to_type is not None:
                    if target_element:  # Click if target specified
                        # Denormalize to get PHYSICAL PIXEL coordinates for center
                        abs_x, abs_y = denormalize_coordinates(
                            target_element.bounds[0],
                            target_element.bounds[1],
                            screen_w,
                            screen_h,
                            target_element.bounds[2],
                            target_element.bounds[3],
                        )
                        # Convert to LOGICAL points for pynput controller
                        logical_x = int(abs_x / scaling_factor)
                        logical_y = int(abs_y / scaling_factor)
                        logger.info(
                            f"Clicking element {target_element.id} at logical ({logical_x},{logical_y}) before typing..."
                        )
                        clicked_before_type = controller.click(logical_x, logical_y)
                        if not clicked_before_type:
                            logger.warning(
                                "Failed to click target element before typing, attempting to type anyway."
                            )
                        # Allow time for focus to shift after click
                        time.sleep(0.2)
                    else:
                        # No target element specified (e.g., typing into Spotlight after Cmd+Space)
                        logger.info(
                            "No target element specified for type action, assuming focus is correct."
                        )

                    # Typing uses its own pynput method
                    action_success = controller.type_text(llm_plan.text_to_type)
                else:
                    logger.error(
                        "Type planned but text_to_type is null."
                    )  # Should be caught by Pydantic

            elif llm_plan.action == "press_key":
                if llm_plan.key_info:
                    action_success = controller.execute_key_string(llm_plan.key_info)
                else:
                    logger.error(
                        "Press_key planned but key_info is null."
                    )  # Should be caught by Pydantic

            elif llm_plan.action == "scroll":
                # Basic scroll, direction might be inferred crudely from reasoning
                # Scroll amount units depend on pynput/OS, treat as steps/lines
                scroll_dir = llm_plan.reasoning.lower()
                scroll_amount_steps = 3  # Scroll N steps/lines
                scroll_dy = (
                    -scroll_amount_steps
                    if "down" in scroll_dir
                    else scroll_amount_steps
                    if "up" in scroll_dir
                    else 0
                )
                scroll_dx = (
                    -scroll_amount_steps
                    if "left" in scroll_dir
                    else scroll_amount_steps
                    if "right" in scroll_dir
                    else 0
                )

                if scroll_dx != 0 or scroll_dy != 0:
                    action_success = controller.scroll(scroll_dx, scroll_dy)
                else:
                    logger.warning(
                        "Scroll planned, but direction unclear or zero amount. Skipping scroll."
                    )
                    action_success = True  # No action needed counts as success here

            else:
                # Should not happen if LLM plan validation works
                logger.warning(
                    f"Action type '{llm_plan.action}' execution not implemented."
                )
                action_success = False

            # Check action result and break loop if failed
            if action_success:
                logger.success("Action executed successfully.")
            else:
                logger.error(
                    f"Action '{llm_plan.action}' execution failed or was skipped."
                )
                final_step_success = False
                break  # Stop loop if low-level action failed

        except Exception as exec_e:
            # Catch unexpected errors during execution block
            logger.error(f"Error during action execution: {exec_e}", exc_info=True)
            final_step_success = False
            break  # Stop loop on execution error

        # Mark step as completed successfully before proceeding
        last_step_completed = step

        # Wait for UI to settle after the action
        time.sleep(1.5)  # Adjust as needed
        logger.info(f"Step {step + 1} duration: {time.time() - step_start_time:.2f}s")

    # --- End of Loop ---
    logger.info("\n--- Demo Finished ---")
    if goal_achieved:
        logger.success("Overall goal marked as achieved by LLM.")
    # Check if loop completed all steps successfully OR broke early due to goal achieved
    elif final_step_success and (last_step_completed == MAX_STEPS - 1 or goal_achieved):
        if not goal_achieved:  # Means max steps reached
            logger.warning(
                f"Reached maximum steps ({MAX_STEPS}) without goal completion."
            )
        # If goal_achieved is True, success message already printed
    else:
        # Loop broke early due to an error
        logger.error(
            f"Execution stopped prematurely after Step {last_step_completed + 1} due to an error."
        )

    # Save the VERY final screen state
    logger.info("Capturing final screen state...")
    final_image = take_screenshot()
    if final_image:
        final_state_img_path = os.path.join(run_output_dir, "final_state.png")
        try:
            final_image.save(final_state_img_path)
            logger.info(f"Saved final screen state to {final_state_img_path}")
        except Exception as save_e:
            logger.warning(f"Could not save final state image: {save_e}")

    logger.info(f"Debug images saved in: {run_output_dir}")
    logger.info(
        "Reminder: Run 'python -m omnimcp.omniparser.server stop' to shut down the EC2 instance if deployed."
    )

    # Return True if goal was achieved, or if max steps were reached without error
    return goal_achieved or (
        final_step_success and last_step_completed == MAX_STEPS - 1
    )


if __name__ == "__main__":
    if not config.ANTHROPIC_API_KEY:
        print("ERROR: ANTHROPIC_API_KEY missing.")
        sys.exit(1)

    print("\n" + "=" * 60)
    print(" WARNING: This script WILL take control of your mouse and keyboard!")
    print(f"          TARGET OS: {platform.system()}")
    print(" Please ensure no sensitive information is visible on screen.")
    print(" To stop execution manually: Move mouse RAPIDLY to a screen corner")
    print("                           OR press Ctrl+C in the terminal.")
    print("=" * 60 + "\n")
    for i in range(5, 0, -1):
        print(f"Starting in {i}...", end="\r")
        time.sleep(1)
    print("Starting now!              ")

    try:
        # Use fire to handle CLI arguments for run_real_planner_demo
        fire.Fire(run_real_planner_demo)
        # Assume success if fire completes without raising an exception here
        sys.exit(0)
    except KeyboardInterrupt:
        logger.warning("Execution interrupted by user (Ctrl+C).")
        sys.exit(1)
    except Exception:
        logger.exception("An unexpected error occurred during the demo execution.")
        sys.exit(1)
