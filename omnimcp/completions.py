# omnimcp/completions.py
import json
import time
from typing import Dict, List, Type, TypeVar
import anthropic
from pydantic import BaseModel, ValidationError
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_random_exponential,
)

from .config import config  # Assuming config has ANTHROPIC_API_KEY
from .utils import logger  # Reuse logger from utils

# Check for API key
if not config.ANTHROPIC_API_KEY:
    raise ValueError("ANTHROPIC_API_KEY not found in environment or .env file.")

# Initialize Anthropic client
client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

# Type variable for the Pydantic response model
T = TypeVar("T", bound=BaseModel)

# Define specific exceptions we might want to retry on differently
RETRYABLE_ERRORS = (
    anthropic.RateLimitError,
    anthropic.APIConnectionError,
    anthropic.InternalServerError,
)

MAX_RETRIES = 3
DEFAULT_MODEL = "claude-3-haiku-20240307"  # Or use Opus/Sonnet if needed


@retry(
    retry=retry_if_exception_type(RETRYABLE_ERRORS),
    wait=wait_random_exponential(min=1, max=30),
    stop=stop_after_attempt(MAX_RETRIES),
    before_sleep=lambda retry_state: logger.warning(
        f"LLM API Error (Attempt {retry_state.attempt_number}/{MAX_RETRIES}): "
        f"{retry_state.outcome.exception()}. Retrying...",
    ),
)
def call_llm_api(
    messages: List[Dict[str, str]],
    response_format: Type[T],
    model: str = DEFAULT_MODEL,
    temperature: float = 0.1,  # Lower temperature for more deterministic output
    system_prompt: str | None = None,  # <-- Add system_prompt argument here
) -> T:
    """
    Calls the Anthropic API, expecting a JSON response conforming to the pydantic model.

    Args:
        messages: List of message dictionaries (system prompt, user message).
        response_format: The Pydantic model class for the expected JSON structure.
        model: The Anthropic model to use.
        temperature: The sampling temperature.
        system_prompt: Optional system prompt string. <-- Added description

    Returns:
        An instance of the response_format Pydantic model.

    Raises:
        anthropic.APIError: If a non-retryable API error occurs.
        ValueError: If the response is not valid JSON or doesn't match the schema.
        Exception: After exceeding retry attempts for retryable errors.
    """
    logger.debug(
        f"Calling Anthropic API (model: {model}) with {len(messages)} messages."
    )
    if system_prompt:
        logger.debug(
            f"System Prompt: {system_prompt[:100]}..."
        )  # Log beginning of system prompt
    start_time = time.time()

    try:
        response = client.messages.create(
            model=model,
            messages=messages,
            system=system_prompt,  # <-- Pass system_prompt to the API call
            max_tokens=1024,  # Adjust as needed
            temperature=temperature,
        )

        duration_ms = int((time.time() - start_time) * 1000)
        logger.debug(f"LLM API call completed in {duration_ms}ms.")

        # Extract the text content
        if not response.content:
            logger.error("Received empty content list from API.")
            raise ValueError("LLM response content is empty.")
        response_text = response.content[0].text.strip()
        logger.debug(f"Raw LLM response text:\n{response_text}")

        # Clean potential markdown code fences
        if response_text.startswith("```json"):
            response_text = response_text[7:]
        if response_text.endswith("```"):
            response_text = response_text[:-3]
        response_text = response_text.strip()

        # Parse and validate the JSON response using the Pydantic model
        try:
            parsed_response = response_format.model_validate_json(response_text)
            logger.info(
                f"Successfully parsed LLM response into {response_format.__name__}."
            )
            return parsed_response
        except ValidationError as e:
            logger.error(
                f"Failed to validate LLM JSON response against schema {response_format.__name__}."
            )
            logger.error(f"Validation Errors: {e}")
            logger.error(f"Raw response was: {response_text}")
            raise ValueError(
                f"LLM response did not match the expected format: {e}"
            ) from e
        except json.JSONDecodeError as e:
            logger.error("Failed to decode LLM response as JSON.")
            logger.error(f"Raw response was: {response_text}")
            raise ValueError(f"LLM response was not valid JSON: {e}") from e

    except RETRYABLE_ERRORS as e:
        logger.warning(f"Encountered retryable API error: {type(e).__name__} - {e}")
        raise
    except anthropic.APIError as e:
        logger.error(f"Non-retryable Anthropic API error: {type(e).__name__} - {e}")
        raise
    except Exception as e:
        logger.error(
            f"Unexpected error during LLM API call: {type(e).__name__} - {e}",
            exc_info=True,
        )
        raise


def format_chat_messages(messages: List[Dict[str, str]]) -> str:
    """Format chat messages in a readable way that preserves formatting."""
    result = []

    for msg in messages:
        role = msg.get("role")
        content = msg.get("content")

        # Add a separator line
        result.append("=" * 80)
        result.append(f"ROLE: {role}")
        result.append("-" * 80)
        result.append(content)

    result.append("=" * 80)
    return "\n".join(result)
