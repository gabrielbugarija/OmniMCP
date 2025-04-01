# omnimcp/core.py
from typing import List, Tuple, Optional

import platform

# Assuming these imports are correct
from .types import UIElement
from .utils import (
    render_prompt,
    logger,
)  # Assuming render_prompt handles template creation
from .completions import call_llm_api
from .types import LLMActionPlan


PROMPT_TEMPLATE = """
You are an expert UI automation assistant. Your task is to determine the single next best action to take on a user interface (UI) to achieve a given user goal, and assess if the goal is already complete.

**Operating System:** {{ platform }}

**User Goal:**
{{ user_goal }}

**Previous Actions Taken:**
{% if action_history %}
{% for action_desc in action_history %}
- {{ action_desc }}
{% endfor %}
{% else %}
- None
{% endif %}

**Current UI Elements:**
Here is a list of UI elements currently visible on the screen (showing first 50 if many).

```
{% for element in elements %}
{{ element.to_prompt_repr() }}
{% endfor %}
```

**Instructions:**
1.  **Analyze:** Review the user goal, previous actions, and the current UI elements. Check if the goal is already achieved based on the current state.
2.  **Reason:** If the goal is not complete, explain your step-by-step plan.
3.  **App Launch Sequence Logic:**
    * If the goal requires an application (like 'calculator') that is *not* visible, and the previous action was *not* pressing the OS search key ("Cmd+Space" or "Win"), then the next action is to press the OS search key: `action: "press_key"`, `key_info: "Cmd+Space"` (or "Win" depending on OS).
    * **IMPORTANT:** If the previous action *was* pressing the OS search key, AND a search input field is now visible in the **Current UI Elements**, then the next action is to type the application name: `action: "type"`, `text_to_type: "Calculator"` (or the specific app name needed), `element_id: <ID of search input field, if available, otherwise null>`.
    * If the previous action was typing the application name into search, the next action is to press Enter: `action: "press_key"`, `key_info: "Enter"`.
4.  **General Action Selection:**
    * If not launching an app, identify the most relevant visible UI element to interact with next (click, type). Choose `action: "click"` or `action: "type"` and provide the correct `element_id`.
    * If typing into a field, set `text_to_type`. Otherwise, it must be null.
    * Use `action: "scroll"` (e.g., `key_info: "down"`) if necessary to find elements, setting other fields to null.
    * For any `press_key` action, `element_id` and `text_to_type` must be null. Provide the key name/combo in `key_info`.
5.  **Goal Completion:** If the goal is fully achieved, set `is_goal_complete: true`. Otherwise, set `is_goal_complete: false`.
6.  **Output Format:** Respond ONLY with a valid JSON object matching the structure below. Do NOT include ```json markdown.

```json
{
  "reasoning": "Your step-by-step thinking process here...",
  "action": "click | type | scroll | press_key",
  "element_id": <ID of target element, or null>,
  "text_to_type": "<text to enter if action is type, otherwise null>",
  "key_info": "<key or shortcut if action is press_key, otherwise null>",
  "is_goal_complete": true | false
}
```
"""


# --- Core Logic Function plan_action_for_ui (remains the same as previous version) ---
# Includes the temporary debug logging for elements on step 2
def plan_action_for_ui(
    elements: List[UIElement],
    user_goal: str,
    action_history: List[str] | None = None,
    # Add step parameter for conditional logging (adjust call in demo.py)
    step: int = 0,
) -> Tuple[LLMActionPlan, Optional[UIElement]]:
    """
    Uses an LLM to plan the next UI action based on elements, goal, and history.
    """
    action_history = action_history or []
    logger.info(
        f"Planning action for goal: '{user_goal}' with {len(elements)} elements. History: {len(action_history)} steps."
    )

    MAX_ELEMENTS_IN_PROMPT = 50
    if len(elements) > MAX_ELEMENTS_IN_PROMPT:
        logger.warning(
            f"Too many elements ({len(elements)}), truncating to {MAX_ELEMENTS_IN_PROMPT} for prompt."
        )
        elements_for_prompt = elements[:MAX_ELEMENTS_IN_PROMPT]
    else:
        elements_for_prompt = elements

    # --- Temporary logging to inspect elements ---
    # Log elements specifically for the step *after* the first Cmd+Space
    if step == 1:  # Note: Step index starts at 0 in the demo loop
        try:
            elements_repr = [el.to_prompt_repr() for el in elements_for_prompt[:10]]
            logger.debug(f"Elements for planning (Step {step + 1}): {elements_repr}")
        except Exception as log_e:
            logger.warning(f"Could not log elements representation: {log_e}")
    # --- End temporary logging ---

    prompt = render_prompt(
        PROMPT_TEMPLATE,
        user_goal=user_goal,
        elements=elements_for_prompt,
        action_history=action_history,
        platform=platform.system(),
    )

    system_prompt = "You are an AI assistant. Respond ONLY with valid JSON that conforms to the provided structure. Do not include any explanatory text before or after the JSON block."
    messages = [{"role": "user", "content": prompt}]

    try:
        llm_plan = call_llm_api(messages, LLMActionPlan, system_prompt=system_prompt)
    except (ValueError, Exception) as e:
        logger.error(f"Failed to get valid action plan from LLM: {e}")
        raise

    target_element = None
    if llm_plan.element_id is not None:
        target_element = next(
            (el for el in elements if el.id == llm_plan.element_id), None
        )

    # Logging Logic
    if llm_plan.is_goal_complete:
        logger.info("LLM determined the goal is complete.")
    elif llm_plan.action in ["click", "type"]:
        if target_element:
            logger.info(
                f"LLM planned action: '{llm_plan.action}' on element ID {llm_plan.element_id} ('{target_element.content[:30]}...')"
            )
        elif llm_plan.action == "click":  # Click always needs a target
            logger.warning(
                f"LLM planned 'click' on element ID {llm_plan.element_id}, but no such element was found."
            )
        # else: Typing without element_id might be okay (e.g., search bar)

    else:  # press_key or scroll
        action_details = f"'{llm_plan.action}'"
        if llm_plan.key_info:
            action_details += f" with key_info: '{llm_plan.key_info}'"
        logger.info(
            f"LLM planned action: {action_details} (no specific element target)"
        )

    return llm_plan, target_element
