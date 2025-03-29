# demo.py
from typing import List
import os
import time

from omnimcp.synthetic_ui import (
    generate_login_screen,
    # generate_logged_in_screen,
    simulate_action,
    draw_highlight,
)
from omnimcp.core import plan_action_for_ui
from omnimcp.utils import logger

# --- Configuration ---
OUTPUT_DIR = "demo_output_multistep"
SAVE_IMAGES = True
MAX_STEPS = 6


def run_multi_step_demo():
    """Runs the multi-step OmniMCP demo using synthetic UI."""
    logger.info("Starting OmniMCP Multi-Step Demo...")
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # 1. Initial State & Goal
    logger.info("Generating initial login screen...")
    # Add save_path to ensure initial image is saved if needed for consistency checks
    image, elements = generate_login_screen(
        save_path=os.path.join(OUTPUT_DIR, "step_0_state_initial.png")
    )
    user_goal = "Log in using username 'testuser' and password 'password123'"
    logger.info(f"User Goal: '{user_goal}'")

    action_history: List[str] = []
    goal_achieved_flag = False  # Use a flag to signal completion after the step runs

    # --- Main Loop ---
    for step in range(MAX_STEPS):
        logger.info(f"\n--- Step {step + 1}/{MAX_STEPS} ---")

        # Save/Show current state *before* planning/highlighting
        current_state_img_path = os.path.join(OUTPUT_DIR, f"step_{step}_state.png")
        if SAVE_IMAGES:
            # Re-save the current state image at the start of each loop iteration
            image.save(current_state_img_path)
            logger.info(f"Saved current state to {current_state_img_path}")
        # else: image.show(title=f"Step {step+1} - Current State")

        # 2. Plan Next Action
        logger.info("Planning action with LLM...")
        try:
            llm_plan, target_element = plan_action_for_ui(
                elements, user_goal, action_history
            )

            logger.info(f"LLM Reasoning: {llm_plan.reasoning}")
            logger.info(
                f"LLM Proposed Action: {llm_plan.action} on Element ID: {llm_plan.element_id}"
            )
            if llm_plan.text_to_type:
                logger.info(f"Text to Type: '{llm_plan.text_to_type}'")
            logger.info(f"LLM Goal Complete Assessment: {llm_plan.is_goal_complete}")

            # 3. Check for Goal Completion Flag (but don't break yet)
            if llm_plan.is_goal_complete:
                logger.info(
                    "LLM flag indicates goal should be complete after this action."
                )
                goal_achieved_flag = True  # Set flag to break after this step

            # Check if target element is valid before proceeding
            # (Even if goal complete, we might need a target for logging/visualization)
            if not target_element:
                logger.error(
                    f"LLM chose an invalid element ID ({llm_plan.element_id}). Stopping execution."
                )
                break

            # 4. Visualize Planned Action (for the action planned in this step)
            highlight_img_path = os.path.join(OUTPUT_DIR, f"step_{step}_highlight.png")
            highlighted_image = draw_highlight(
                image, target_element, color="lime", width=4
            )
            if SAVE_IMAGES:
                highlighted_image.save(highlight_img_path)
                logger.info(f"Saved highlighted action to {highlight_img_path}")
            # else: highlighted_image.show(title=f"Step {step+1} - Action Target")

            # Record action for history *before* simulation changes state
            action_desc = f"Action: {llm_plan.action}"
            if llm_plan.text_to_type:
                action_desc += f" '{llm_plan.text_to_type}'"
            action_desc += (
                f" on Element ID {target_element.id} ('{target_element.content}')"
            )
            action_history.append(action_desc)

            # 5. Simulate Action -> Get New State (ALWAYS run this for the planned step)
            logger.info("Simulating action...")
            # Extract username now in case login is successful in this step
            username = next(
                (
                    el.content
                    for el in elements
                    if el.id == 0 and el.type == "text_field"
                ),
                "User",
            )

            new_image, new_elements = simulate_action(
                image, elements, llm_plan, username_for_login=username
            )

            # Check if state actually changed
            # Simple check: Did the image object or element list reference change?
            # A more robust check might involve image diff or deep element comparison
            state_changed = (id(new_image) != id(image)) or (
                id(new_elements) != id(elements)
            )
            # Add a basic content check for elements as deepcopy might create new list object always
            if not state_changed and len(elements) == len(new_elements):
                # Primitive check if element contents are roughly the same
                if all(
                    e1.to_dict() == e2.to_dict()
                    for e1, e2 in zip(elements, new_elements)
                ):
                    state_changed = False
                else:
                    state_changed = (
                        True  # Content differs even if list object ID didn't
                    )

            image, elements = (
                new_image,
                new_elements,
            )  # Update state regardless for next loop iteration

            if state_changed:
                logger.info(
                    f"State updated for next step. New element count: {len(elements)}"
                )
            else:
                logger.warning(
                    "Simulation did not result in a detectable state change."
                )
                # Decide whether to stop or continue if state doesn't change
                # For now, let's continue but log it. Add 'break' here if needed.

            # 6. NOW check the flag to break *after* simulation
            if goal_achieved_flag:
                logger.success(
                    "Goal completion flag was set, ending loop after simulation."
                )
                break

            # Pause briefly
            time.sleep(1)

        except Exception as e:
            logger.error(f"Error during step {step + 1}: {e}", exc_info=True)
            break  # Stop on error

    # --- End of Loop ---
    logger.info("\n--- Multi-Step Demo Finished ---")
    # Check the flag, not just loop completion condition
    if goal_achieved_flag:
        logger.success("Overall goal marked as achieved by LLM during execution.")
    elif step == MAX_STEPS - 1:
        logger.warning(
            f"Reached maximum steps ({MAX_STEPS}) without goal completion flag being set."
        )
    else:
        logger.error(
            "Execution stopped prematurely (check logs for errors or lack of state change)."
        )

    # Save final state (which is the state *after* the last successful simulation)
    final_state_img_path = os.path.join(OUTPUT_DIR, "final_state.png")
    if SAVE_IMAGES:
        image.save(final_state_img_path)
        logger.info(f"Saved final state to {final_state_img_path}")
    # else: image.show(title="Final State")


if __name__ == "__main__":
    run_multi_step_demo()
