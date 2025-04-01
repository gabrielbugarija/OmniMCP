# demo_synthetic.py

import os
import time
from typing import List, Optional  # Import Any for plan typing

# Import necessary components from the project
from omnimcp.synthetic_ui import (
    generate_login_screen,
    simulate_action,
    draw_highlight,  # Use the original draw_highlight from synthetic_ui
)
from omnimcp.core import plan_action_for_ui, LLMActionPlan  # Import the Pydantic model
from omnimcp.utils import logger  # Assuming logger is configured elsewhere
from omnimcp.types import UIElement  # Import UIElement

# --- Configuration ---
OUTPUT_DIR = "demo_output_multistep"  # Keep original output dir for synthetic demo
SAVE_IMAGES = True
MAX_STEPS = 6  # Keep original max steps for this demo


def run_multi_step_demo():
    """Runs the multi-step OmniMCP demo using synthetic UI and LLM planning."""
    logger.info("--- Starting OmniMCP Multi-Step Synthetic Demo ---")
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # 1. Initial State & Goal
    logger.info("Generating initial login screen...")
    try:
        # Use save_path to ensure initial image is saved
        image, elements = generate_login_screen(
            save_path=os.path.join(OUTPUT_DIR, "step_0_state_initial.png")
        )
    except Exception as e:
        logger.error(f"Failed to generate initial screen: {e}", exc_info=True)
        return

    user_goal = "Log in using username 'testuser' and password 'password123'"
    logger.info(f"User Goal: '{user_goal}'")

    action_history: List[str] = []
    goal_achieved_flag = False  # Use a flag to signal completion after the step runs
    last_step_completed = -1  # Track last successful step index

    # --- Main Loop ---
    for step in range(MAX_STEPS):
        logger.info(f"\n--- Step {step + 1}/{MAX_STEPS} ---")
        step_img_prefix = f"step_{step + 1}"  # Use 1-based index for filenames

        # Save/Show current state *before* planning/highlighting
        current_state_img_path = os.path.join(
            OUTPUT_DIR, f"{step_img_prefix}_state.png"
        )
        if SAVE_IMAGES:
            try:
                image.save(current_state_img_path)
                logger.info(f"Saved current state to {current_state_img_path}")
            except Exception as save_e:
                logger.warning(f"Could not save step state image: {save_e}")

        # 2. Plan Next Action
        logger.info("Planning action with LLM...")
        llm_plan: Optional[LLMActionPlan] = None
        target_element: Optional[UIElement] = None
        try:
            llm_plan, target_element = plan_action_for_ui(
                elements=elements,  # Pass current elements
                user_goal=user_goal,
                action_history=action_history,
                step=step,  # Pass step index
            )

            logger.info(f"LLM Reasoning: {llm_plan.reasoning}")
            logger.info(
                f"LLM Proposed Action: {llm_plan.action} on Element ID: {llm_plan.element_id}"
            )
            if llm_plan.text_to_type:
                logger.info(f"Text to Type: '{llm_plan.text_to_type}'")
            if llm_plan.key_info:
                logger.info(f"Key Info: '{llm_plan.key_info}'")
            logger.info(f"LLM Goal Complete Assessment: {llm_plan.is_goal_complete}")

            # 3. Check for Goal Completion Flag (but don't break loop yet)
            if llm_plan.is_goal_complete:
                logger.info(
                    "LLM flag indicates goal should be complete after this action."
                )
                goal_achieved_flag = (
                    True  # Set flag to break after this step's simulation
                )

            # --- Updated Validation Check ---
            # Validate target element ONLY IF the goal is NOT yet complete AND action requires it
            if not goal_achieved_flag:
                # Click requires a valid target element found in the current state
                if llm_plan.action == "click" and not target_element:
                    logger.error(
                        f"LLM planned 'click' on invalid element ID ({llm_plan.element_id}). Stopping."
                    )
                    break  # Stop if click is impossible

                # Type MIGHT require a target in synthetic demo, depending on simulate_action logic
                # If simulate_action assumes type always targets a field, uncomment below
                # if llm_plan.action == "type" and not target_element:
                #     logger.error(f"LLM planned 'type' on invalid element ID ({llm_plan.element_id}). Stopping.")
                #     break
            # --- End Updated Validation Check ---

            # 4. Visualize Planned Action (uses synthetic_ui.draw_highlight)
            highlight_img_path = os.path.join(
                OUTPUT_DIR, f"{step_img_prefix}_highlight.png"
            )
            if target_element:  # Only draw highlight if element exists
                try:
                    # Pass the llm_plan to the draw_highlight function
                    highlighted_image = draw_highlight(
                        image,
                        target_element,
                        plan=llm_plan,  # Pass the plan object here
                        color="lime",
                        width=4,
                    )
                    if SAVE_IMAGES:
                        highlighted_image.save(highlight_img_path)
                        logger.info(
                            f"Saved highlighted action with text to {highlight_img_path}"
                        )
                except Exception as draw_e:
                    logger.warning(f"Could not save highlight image: {draw_e}")
            else:
                logger.info("No target element to highlight for this step.")

            # Record action for history *before* simulation changes state
            action_desc = f"Action: {llm_plan.action}"
            if llm_plan.text_to_type:
                action_desc += f" '{llm_plan.text_to_type}'"
            if llm_plan.key_info:
                action_desc += f" Key='{llm_plan.key_info}'"  # Add key_info if present
            if target_element:
                action_desc += (
                    f" on Element ID {target_element.id} ('{target_element.content}')"
                )
            action_history.append(action_desc)
            logger.debug(f"Added to history: {action_desc}")

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

            # simulate_action needs to handle the LLMActionPlan type
            new_image, new_elements = simulate_action(
                image, elements, llm_plan, username_for_login=username
            )

            # Basic check if state actually changed
            state_changed = (
                (id(new_image) != id(image))
                or (len(elements) != len(new_elements))
                or any(
                    e1.to_dict() != e2.to_dict()
                    for e1, e2 in zip(elements, new_elements)
                )
            )

            image, elements = new_image, new_elements  # Update state for next loop

            if state_changed:
                logger.info(
                    f"State updated for next step. New element count: {len(elements)}"
                )
            else:
                logger.warning(
                    "Simulation did not result in a detectable state change."
                )

            # Mark step as completed successfully before checking goal flag or pausing
            last_step_completed = step

            # 6. NOW check the flag to break *after* simulation
            if goal_achieved_flag:
                logger.success(
                    "Goal completion flag was set, ending loop after simulation."
                )
                break

            # Pause briefly between steps
            time.sleep(1)

        except Exception as e:
            logger.error(f"Error during step {step + 1}: {e}", exc_info=True)
            break  # Stop on error

    # --- End of Loop ---
    logger.info("\n--- Multi-Step Synthetic Demo Finished ---")
    if goal_achieved_flag:
        logger.success("Overall goal marked as achieved by LLM during execution.")
    elif last_step_completed == MAX_STEPS - 1:
        # Reached end without goal flag, but no error broke the loop
        logger.warning(
            f"Reached maximum steps ({MAX_STEPS}) without goal completion flag being set."
        )
    else:
        # Loop broke early due to error or other condition
        logger.error(
            f"Execution stopped prematurely after Step {last_step_completed + 1} (check logs)."
        )

    # Save final state
    final_state_img_path = os.path.join(OUTPUT_DIR, "final_state.png")
    if SAVE_IMAGES:
        try:
            image.save(final_state_img_path)
            logger.info(f"Saved final state to {final_state_img_path}")
        except Exception as save_e:
            logger.warning(f"Could not save final state image: {save_e}")


if __name__ == "__main__":
    # Add basic check for API key if running this directly
    # (Although synthetic demo doesn't *strictly* need it if core allows planning without it)
    # from omnimcp.config import config # Example if config is needed
    # if not config.ANTHROPIC_API_KEY:
    #    print("Warning: ANTHROPIC_API_KEY not found. LLM planning might fail.")
    run_multi_step_demo()
