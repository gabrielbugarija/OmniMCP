# omnimcp/core.py
from typing import List, Tuple, Literal
from pydantic import BaseModel, Field, field_validator, ValidationInfo


from .types import UIElement
from .utils import render_prompt, logger
from .completions import call_llm_api, format_chat_messages  # Import TypeVar T

# --- Pydantic Schema for LLM Output ---


class LLMActionPlan(BaseModel):
    """Defines the structured output expected from the LLM for action planning."""

    reasoning: str = Field(
        ...,
        description="Step-by-step thinking process to connect the user goal to the chosen UI element and action. Explain the choice.",
    )
    action: Literal["click", "type", "scroll"] = Field(
        ..., description="The type of interaction to perform on the element."
    )
    element_id: int = Field(
        ...,
        description="The unique ID of the target UI element from the provided list.",
    )
    text_to_type: str | None = Field(
        None,
        description="The text to type into the element, ONLY if the action is 'type'.",
    )
    is_goal_complete: bool = Field(
        ...,
        description="Set to true if the user's overall goal is fully achieved given the current UI state, otherwise false.",
    )  # New field

    @field_validator("text_to_type")
    def check_text_to_type(cls, v: str | None, info: ValidationInfo) -> str | None:
        if info.data.get("action") == "type" and v is None:
            logger.warning("Action is 'type' but 'text_to_type' is missing.")
        elif info.data.get("action") != "type" and v is not None:
            logger.warning(
                f"Action is '{info.data.get('action')}' but 'text_to_type' was provided."
            )
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
2.  **Check Completion:** Based ONLY on the current UI elements, determine if the original user goal has already been fully achieved. Set `is_goal_complete` accordingly (true/false).
3.  **Reason (if goal not complete):** If the goal is not complete, think step-by-step (in the `reasoning` field) about the single best *next* action to progress towards the goal. Consider the element types, content, and previous actions.
4.  **Select Action & Element (if goal not complete):** Choose the most appropriate action ("click", "type", "scroll") and the `ID` of the target UI element for that single next step. If the goal is already complete, you can choose a dummy action like 'click' on a harmless element (e.g., static text if available, or ID 0) or default to 'click' ID 0, but focus on setting `is_goal_complete` correctly.
5.  **Specify Text (if typing):** If the action is "type", provide the exact text in `text_to_type`. Otherwise, leave it null.
6.  **Format Output:** Respond ONLY with a valid JSON object matching the structure below.

```json
{
  "reasoning": "Your step-by-step thinking process here...",
  "action": "click | type | scroll",
  "element_id": <ID of the target element>,
  "text_to_type": "<text to enter if action is type, otherwise null>",
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
