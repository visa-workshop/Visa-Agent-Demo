"""OpenAI client wrapper for the Visa Disputes AI agent system.

Provides a centralized client for making OpenAI API calls with structured
JSON responses, retry logic, and consistent error handling.
"""

import json
import logging
import os
import time
from typing import Any

from openai import APIConnectionError, APITimeoutError, OpenAI, RateLimitError

logger = logging.getLogger(__name__)

_client: OpenAI | None = None

_MAX_RETRIES = 3
_RETRY_BASE_DELAY = 1.0  # seconds
_RETRYABLE_EXCEPTIONS = (APIConnectionError, APITimeoutError, RateLimitError)


def get_client() -> OpenAI:
    """Return a singleton OpenAI client instance.

    Raises:
        RuntimeError: If OPENAI_API_KEY is not set.
    """
    global _client
    if _client is not None:
        return _client

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "OPENAI_API_KEY environment variable is required. "
            "This application uses OpenAI to process disputes according to Visa rules."
        )
    _client = OpenAI(api_key=api_key)
    return _client


def chat_json(
    system_prompt: str,
    user_prompt: str,
    *,
    model: str = "gpt-4o-mini",
    temperature: float = 0.1,
    max_tokens: int = 2000,
) -> dict[str, Any]:
    """Send a chat completion request and parse the response as JSON.

    Args:
        system_prompt: The system message providing context and instructions.
        user_prompt: The user message with the specific request.
        model: OpenAI model to use.
        temperature: Sampling temperature (low = more deterministic).
        max_tokens: Maximum tokens in the response.

    Returns:
        Parsed JSON dict from the model response.

    Raises:
        RuntimeError: If the API call fails or response cannot be parsed.
    """
    client = get_client()
    last_exception: Exception | None = None

    for attempt in range(_MAX_RETRIES):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=temperature,
                max_tokens=max_tokens,
                response_format={"type": "json_object"},
            )

            content = response.choices[0].message.content
            if content is None:
                raise RuntimeError("OpenAI returned empty response")

            result: dict[str, Any] = json.loads(content)
            return result
        except _RETRYABLE_EXCEPTIONS as exc:
            last_exception = exc
            delay = _RETRY_BASE_DELAY * (2 ** attempt)
            logger.warning(
                "OpenAI API call failed (attempt %d/%d): %s. Retrying in %.1fs",
                attempt + 1, _MAX_RETRIES, exc, delay,
            )
            time.sleep(delay)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Failed to parse OpenAI response as JSON: {exc}") from exc

    raise RuntimeError(
        f"OpenAI API call failed after {_MAX_RETRIES} attempts: {last_exception}"
    )


def chat_text(
    system_prompt: str,
    user_prompt: str,
    *,
    model: str = "gpt-4o-mini",
    temperature: float = 0.1,
    max_tokens: int = 2000,
) -> str:
    """Send a chat completion request and return the text response.

    Args:
        system_prompt: The system message providing context and instructions.
        user_prompt: The user message with the specific request.
        model: OpenAI model to use.
        temperature: Sampling temperature.
        max_tokens: Maximum tokens in the response.

    Returns:
        Text content from the model response.

    Raises:
        RuntimeError: If the API call fails.
    """
    client = get_client()
    last_exception: Exception | None = None

    for attempt in range(_MAX_RETRIES):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=temperature,
                max_tokens=max_tokens,
            )

            content = response.choices[0].message.content
            if content is None:
                raise RuntimeError("OpenAI returned empty response")

            return content
        except _RETRYABLE_EXCEPTIONS as exc:
            last_exception = exc
            delay = _RETRY_BASE_DELAY * (2 ** attempt)
            logger.warning(
                "OpenAI API call failed (attempt %d/%d): %s. Retrying in %.1fs",
                attempt + 1, _MAX_RETRIES, exc, delay,
            )
            time.sleep(delay)

    raise RuntimeError(
        f"OpenAI API call failed after {_MAX_RETRIES} attempts: {last_exception}"
    )
