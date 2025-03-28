# omnimcp/core.py
from typing import List, Tuple, Literal
from PIL import Image

# Corrected Pydantic import
from pydantic import BaseModel, Field, field_validator, ValidationInfo

from .types import UIElement
from .utils import render_prompt, logger
from .completions import call_llm_api, T  # Import TypeVar T

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

    # Example validation using the imported decorator and ValidationInfo
    @field_validator("text_to_type")
    def check_text_to_type(cls, v: str | None, info: ValidationInfo) -> str | None:
        # info.data contains the model fields already processed
        if info.data.get("action") == "type" and v is None:
            logger.warning(
                "Action is 'type' but 'text_to_type' is missing. LLM might need better prompting."
            )
            # Depending on strictness, you could raise ValueError here
        elif info.data.get("action") != "type" and v is not None:
            logger.warning(
                f"Action is '{info.data.get('action')}' but 'text_to_type' was provided. Will be ignored by most actions."
            )
            # Depending on strictness, you could set v to None or raise ValueError
        return v


# --- Prompt Template ---

PROMPT_TEMPLATE = """
You are an expert UI automation assistant. Your task is to determine the next best action to take on a user interface (UI) to achieve a given user goal.

**User Goal:**
{{ user_goal }}

**Current UI Elements:**
Here is a list of UI elements currently visible on the screen. Each element has an ID, type, content (text label or value), and location (bounds).

```
{% for element in elements %}
{{ element.to_prompt_repr() }}
{% endfor %}
```

**Instructions:**
1.  **Analyze:** Carefully review the user goal and the available UI elements.
2.  **Reason:** Think step-by-step (provide your reasoning in the `reasoning` field) about how to progress towards the user goal using one of the available elements. Consider the element types and content.
    * If the goal involves entering text (e.g., "log in with username 'test'"), identify the correct text field and specify the text to type.
    * If the goal involves clicking a button (e.g., "submit the form"), identify the correct button.
    * If the goal involves selecting an option (e.g., "check the remember me box"), identify the checkbox or radio button.
3.  **Select Action:** Choose the single most appropriate action from: "click", "type", "scroll".
4.  **Select Element:** Identify the `ID` of the single UI element that should be targeted for this action.
5.  **Specify Text (if typing):** If the action is "type", provide the exact text to be typed in the `text_to_type` field. Otherwise, leave it null.
6.  **Format Output:** Respond ONLY with a valid JSON object matching the following structure. Do NOT include any text outside the JSON block.

```json
{
  "reasoning": "Your step-by-step thinking process here...",
  "action": "click | type | scroll",
  "element_id": <ID of the target element>,
  "text_to_type": "<text to enter if action is type, otherwise null>"
}
```
"""

# --- Core Logic Function ---


def plan_action_for_ui(
    elements: List[UIElement], user_goal: str
) -> Tuple[LLMActionPlan, UIElement | None]:
    """
    Uses an LLM to plan the next UI action based on elements and a goal.

    Args:
        elements: List of UIElement objects detected on the screen.
        user_goal: The natural language goal provided by the user.

    Returns:
        A tuple containing:
        - The LLMActionPlan (parsed Pydantic model).
        - The targeted UIElement object, or None if the ID is invalid.
    """
    logger.info(
        f"Planning action for goal: '{user_goal}' with {len(elements)} elements."
    )

    # Prepare the prompt
    prompt = render_prompt(PROMPT_TEMPLATE, user_goal=user_goal, elements=elements)

    # Define the messages for the LLM API
    # Use "system" prompt for overall instructions, "user" for specific request
    # (Anthropic recommends system prompts for instructions)
    system_prompt = "You are an AI assistant. Respond ONLY with valid JSON that conforms to the provided structure. Do not include any explanatory text before or after the JSON block."
    messages = [{"role": "user", "content": prompt}]

    # Call the LLM API with structured output expectation
    try:
        # Pass system prompt separately if supported or prepend to user message if not
        llm_plan = call_llm_api(
            messages, LLMActionPlan, system_prompt=system_prompt
        )  # Assuming call_llm_api handles system prompt
    except (ValueError, Exception) as e:  # Broader catch for API errors too now
        logger.error(f"Failed to get valid action plan from LLM: {e}")
        raise  # Reraise for demo purposes

    # Find the target element from the list using the ID from the plan
    target_element = next((el for el in elements if el.id == llm_plan.element_id), None)

    if target_element:
        logger.info(
            f"LLM planned action: '{llm_plan.action}' on element ID {llm_plan.element_id} ('{target_element.content}')"
        )
    else:
        logger.warning(
            f"LLM planned action on element ID {llm_plan.element_id}, but no such element was found in the input list."
        )

    return llm_plan, target_element


# Small adjustment in call_llm_api might be needed if it doesn't take system_prompt kwarg
# In completions.py, adjust call_llm_api if necessary:
# def call_llm_api(..., system_prompt: str | None = None):
#    ...
#    response = client.messages.create(
#        ...,
#        system=system_prompt, # Add this line
#        messages=messages,
#        ...
#    )
