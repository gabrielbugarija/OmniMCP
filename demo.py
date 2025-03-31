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
from omnimcp.synthetic_ui import (
    simulate_action,
    draw_highlight,
)  # Keep simulation and highlight
from omnimcp.utils import logger
from omnimcp.config import config  # To check if keys are set

# --- Configuration ---
OUTPUT_DIR = "demo_output_real_planner"  # New output directory
SAVE_IMAGES = True
MAX_STEPS = 6


async def run_real_planner_demo(
    user_goal: str = "Open a browser and check the weather",
):
    """Runs the demo integrating real perception->planning with simulation."""
    logger.info(
        "--- Starting OmniMCP Demo: Real Perception -> Planner -> Simulation ---"
    )
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # 1. Initialize Client & Visual State
    # Ensure API keys and AWS creds are in .env or environment
    if not config.ANTHROPIC_API_KEY:
        logger.error("ANTHROPIC_API_KEY not found in config. Cannot run planner.")
        sys.exit(1)
    # Client init handles deployment if needed (requires AWS keys)
    logger.info("Initializing OmniParserClient and VisualState...")
    try:
        # Let client handle auto-deploy if URL not specified in .env
        parser_client = OmniParserClient(
            server_url=config.OMNIPARSER_URL, auto_deploy=(not config.OMNIPARSER_URL)
        )
        visual_state = VisualState(parser_client=parser_client)
        logger.success(
            f"Client & VisualState initialized. Parser URL: {parser_client.server_url}"
        )
    except Exception as e:
        logger.error(f"Initialization failed: {e}", exc_info=True)
        sys.exit(1)

    # 2. Use the provided User Goal
    logger.info(f"User Goal: '{user_goal}'")

    action_history: List[str] = []
    goal_achieved = False

    # 3. Get Initial Real State
    logger.info("Getting initial screen state...")
    try:
        await visual_state.update()
        if not visual_state.elements:
            logger.error("Failed to get initial elements from screen. Exiting.")
            sys.exit(1)
        # Use the real screenshot and mapped elements
        current_image = visual_state._last_screenshot
        current_elements = visual_state.elements
        logger.info(f"Initial state captured with {len(current_elements)} elements.")
    except Exception as e:
        logger.error(f"Failed to get initial visual state: {e}", exc_info=True)
        sys.exit(1)

    # --- Main Loop ---
    for step in range(MAX_STEPS):
        logger.info(f"\n--- Step {step + 1}/{MAX_STEPS} ---")
        step_start_time = time.time()

        # Save current state image (real screenshot or simulated from previous step)
        current_state_img_path = os.path.join(OUTPUT_DIR, f"step_{step}_state.png")
        if SAVE_IMAGES and current_image:
            try:
                current_image.save(current_state_img_path)
                logger.info(f"Saved current state to {current_state_img_path}")
            except Exception as save_e:
                logger.warning(f"Could not save step state image: {save_e}")
        # else: current_image.show(title=f"Step {step+1} - Current State")

        # 4. Plan Next Action using LLM Planner
        logger.info("Planning action with LLM...")
        if not current_elements:
            logger.warning("No elements available for planning. Stopping.")
            break
        try:
            llm_plan, target_element = plan_action_for_ui(
                elements=current_elements,  # Use current elements
                user_goal=user_goal,
                action_history=action_history,
            )
            # Log plan details
            logger.info(f"LLM Reasoning: {llm_plan.reasoning}")
            logger.info(
                f"LLM Proposed Action: {llm_plan.action} on Element ID: {llm_plan.element_id}"
            )
            if llm_plan.text_to_type:
                logger.info(f"Text to Type: '{llm_plan.text_to_type}'")
            logger.info(f"LLM Goal Complete Assessment: {llm_plan.is_goal_complete}")

        except Exception as plan_e:
            logger.error(f"Error during LLM planning: {plan_e}", exc_info=True)
            break  # Stop loop on planning error

        # 5. Check for Goal Completion
        if llm_plan.is_goal_complete:
            logger.success("LLM determined the goal is achieved!")
            goal_achieved = True
            # Optionally perform the final action before breaking
            # if target_element: ... simulate ...
            break

        # Check if target element is valid before visualization/simulation
        if target_element is None:
            # Find the element again in the *current* list if needed, plan returns the obj now
            target_element = next(
                (el for el in current_elements if el.id == llm_plan.element_id), None
            )
            if target_element is None:
                logger.error(
                    f"LLM chose element ID {llm_plan.element_id}, but it wasn't found in the current element list. Stopping."
                )
                break

        # 6. Visualize Planned Action on the *current* image
        if SAVE_IMAGES and current_image:
            highlight_img_path = os.path.join(OUTPUT_DIR, f"step_{step}_highlight.png")
            try:
                highlighted_image = draw_highlight(
                    current_image,
                    target_element,
                    plan=llm_plan,  # Pass plan for annotation
                )
                highlighted_image.save(highlight_img_path)
                logger.info(f"Saved highlighted action to {highlight_img_path}")
            except Exception as draw_e:
                logger.warning(f"Could not save highlight image: {draw_e}")
            # else: highlighted_image.show(title=f"Step {step+1} - Action Target")

        # Record action for history
        action_desc = f"Step {step + 1}: Planned {llm_plan.action}"
        if llm_plan.text_to_type:
            action_desc += f" '{llm_plan.text_to_type[:20]}...'"
        action_desc += (
            f" on Element ID {target_element.id} ('{target_element.content[:30]}...')"
        )
        action_history.append(action_desc)

        # 7. Simulate Action -> Get *Simulated* Next State
        # NOTE: This is the step to replace with REAL actions later
        logger.info("Simulating action to generate next state for planning...")
        try:
            # Simulate based on the *current* state before the action
            sim_image, sim_elements = simulate_action(
                current_image, current_elements, llm_plan
            )
            state_changed = id(sim_image) != id(current_image)  # Basic check

            # Update current state variables with SIMULATED results for the next loop iteration
            current_image = sim_image
            current_elements = sim_elements

            if state_changed:
                logger.info(
                    f"Simulated state updated for next step. New element count: {len(current_elements)}"
                )
            else:
                logger.warning(
                    "Simulation did not result in a detectable state change."
                )
                # Decide whether to stop or continue if simulation doesn't change state
                # break # Option: Stop if simulation is stuck

        except Exception as sim_e:
            logger.error(f"Error during simulation: {sim_e}", exc_info=True)
            break  # Stop loop on simulation error

        # Pause briefly?
        time.sleep(1)
        logger.info(f"Step {step + 1} duration: {time.time() - step_start_time:.2f}s")

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
    # Make the positional argument optional, default to None if not given
    parser.add_argument(
        "user_goal",
        nargs="?",  # Allows zero or one argument
        default=None,  # Value if argument is omitted
        help="The natural language goal for the agent (optional, defaults to checking weather).",
    )
    args = parser.parse_args()
    cli_goal = args.user_goal

    # Ensure essential keys are present before starting
    if not config.ANTHROPIC_API_KEY:
        print(
            "ERROR: ANTHROPIC_API_KEY not found in environment or .env file. Exiting."
        )
        sys.exit(1)
    # AWS keys checked during client init if needed

    # Run the async main function
    success = False
    if cli_goal:
        # If goal provided via CLI, pass it to override the function's default
        logger.info(f"Using user goal from command line: '{cli_goal}'")
        success = asyncio.run(run_real_planner_demo(user_goal=cli_goal))
    else:
        # If no goal provided via CLI, call function without the argument
        # so it uses its internal default value.
        logger.info("No goal provided on command line, using default goal.")
        success = asyncio.run(run_real_planner_demo())  # Call without user_goal kwarg

    if not success:
        sys.exit(1)  # Exit with error if demo function indicated failure
