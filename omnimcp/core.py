# omnimcp/core.py
from typing import List, Tuple, Literal, Optional
from pydantic import BaseModel, Field, field_validator, ValidationInfo


from .types import UIElement
from .utils import render_prompt, logger
from .completions import call_llm_api, format_chat_messages  # Import TypeVar T

# --- Pydantic Schema for LLM Output ---


class LLMActionPlan(BaseModel):
    """Defines the structured output expected from the LLM for action planning."""

    reasoning: str = Field(..., description="Step-by-step thinking process...")
    # Add 'press_key' to the allowed actions
    action: Literal["click", "type", "scroll", "press_key"] = Field(
        ..., description="..."
    )
    # Make element_id optional, default None
    element_id: Optional[int] = Field(
        None,
        description="The ID of the target UI element IF the action is 'click' or 'type'. Must be null for 'press_key' and 'scroll'.",
    )
    text_to_type: Optional[str] = Field(
        None, description="Text to type IF action is 'type'. Must be null otherwise."
    )
    # Add field for key press action
    key_info: Optional[str] = Field(
        None,
        description="Key or shortcut to press IF action is 'press_key' (e.g., 'Enter', 'Cmd+Space', 'Win'). Must be null otherwise.",
    )
    is_goal_complete: bool = Field(
        ..., description="Set to true if the user's overall goal is fully achieved..."
    )

    # Updated Validators
    @field_validator("element_id")
    @classmethod
    def check_element_id(cls, v: Optional[int], info: ValidationInfo) -> Optional[int]:
        action = info.data.get("action")
        if action in ["click", "type"] and v is None:
            # Type might sometimes not need an element_id if typing globally? Revisit if needed.
            # For now, require element_id for click/type.
            raise ValueError(f"element_id is required for action '{action}'")
        if action in ["scroll", "press_key"] and v is not None:
            raise ValueError(f"element_id must be null for action '{action}'")
        return v

    @field_validator("text_to_type")
    @classmethod
    def check_text_to_type(
        cls, v: Optional[str], info: ValidationInfo
    ) -> Optional[str]:
        action = info.data.get("action")
        if action == "type" and v is None:
            # Allow empty string for type, but not None if action is type
            raise ValueError("text_to_type is required for action 'type'")
        if action != "type" and v is not None:
            raise ValueError("text_to_type must be null for actions other than 'type'")
        return v

    @field_validator("key_info")
    @classmethod
    def check_key_info(cls, v: Optional[str], info: ValidationInfo) -> Optional[str]:
        action = info.data.get("action")
        if action == "press_key" and v is None:
            raise ValueError("key_info is required for action 'press_key'")
        if action != "press_key" and v is not None:
            raise ValueError("key_info must be null for actions other than 'press_key'")
        return v


# --- Prompt Template ---

PROMPT_TEMPLATE = """
You are an expert UI automation assistant. Your task is to determine the single next best action to take on a user interface (UI) to achieve a given user goal, and assess if the goal is already complete.

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
Here is a list of UI elements currently visible on the screen.

```
{% for element in elements %}
{{ element.to_prompt_repr() }}
{% endfor %}
```

**Instructions:**
1.  **Analyze:** Review the user goal, previous actions, and the current UI elements.
2.  **Check Completion:** ... set `is_goal_complete` accordingly (true/false).
3.  **Reason (if goal not complete):**
    * If the goal requires a specific application (like a web browser...) that is NOT readily visible... include a plan to launch it first.
    * Think step-by-step...
4.  **Select Action & Element (if goal not complete):**
    * **Prioritize visible elements:** If a relevant element... is visible, choose 'click' or 'type' and its `element_id`.
    * **If needed element/app is not visible:** Plan the sequence to launch it using the OS search. This usually involves:
        * Action: "press_key" with `key_info` specifying the OS search shortcut (e.g., "Cmd+Space", "Win").
        * *Then (in subsequent steps)*: Action: "type" with `text_to_type` specifying the application name (e.g., "Google Chrome").
        * *Then (in subsequent steps)*: Action: "press_key" with `key_info` specifying the 'Enter' key.
    * Choose ONLY the *single next step* in the sequence for the current plan.
    * Other Actions: Use "scroll" if needed to reveal elements (provide `element_id: null`, `key_info: null`, `text_to_type: null`).
    * If the goal is already complete, choose 'click', `element_id: 0`, set `is_goal_complete: true`.
5.  **Specify Text or Key (if applicable):**
    * If action is "type", provide the exact text in `text_to_type` (null otherwise).
    * If action is "press_key", provide the key/shortcut description in `key_info` (e.g., "Enter", "Cmd+Space") (null otherwise).
6.  **Format Output:** Respond ONLY with a valid JSON object matching the structure below.

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

# --- Core Logic Function ---


def plan_action_for_ui(
    elements: List[UIElement],
    user_goal: str,
    action_history: List[str] | None = None,
) -> Tuple[LLMActionPlan, UIElement | None]:
    """
    Uses an LLM to plan the next UI action based on elements, goal, and history.
    """
    action_history = action_history or []
    logger.info(
        f"Planning action for goal: '{user_goal}' with {len(elements)} elements. History: {len(action_history)} steps."
    )

    prompt = render_prompt(
        PROMPT_TEMPLATE,
        user_goal=user_goal,
        elements=elements,
        action_history=action_history,  # Pass history to template
    )

    system_prompt = "You are an AI assistant. Respond ONLY with valid JSON that conforms to the provided structure. Do not include any explanatory text before or after the JSON block."
    messages = [{"role": "user", "content": prompt}]
    logger.debug(f"Sending prompt to LLM:\n{format_chat_messages(messages)}\n---")

    try:
        llm_plan = call_llm_api(messages, LLMActionPlan, system_prompt=system_prompt)
    except (ValueError, Exception) as e:
        logger.error(f"Failed to get valid action plan from LLM: {e}")
        raise

    logger.debug(f"Received LLM response:\n{llm_plan.model_dump_json(indent=2)}\n---")

    # Find the target element even if goal is complete, might be needed for logging/dummy actions
    target_element = next((el for el in elements if el.id == llm_plan.element_id), None)

    if llm_plan.is_goal_complete:
        logger.info("LLM determined the goal is complete.")
    elif target_element:
        logger.info(
            f"LLM planned action: '{llm_plan.action}' on element ID {llm_plan.element_id} ('{target_element.content}')"
        )
    else:
        # Log warning if goal is not complete but element ID is invalid
        logger.warning(
            f"LLM planned action on element ID {llm_plan.element_id}, but no such element was found in the input list."
        )

    return llm_plan, target_element
