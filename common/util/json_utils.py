"""Shared JSON parsing utilities for extracting JSON from LLM code-block responses."""

import json
import re
from typing import Any, Dict, List, Optional, Type, Union

from loguru import logger
from pydantic import BaseModel

def parse_llm_json_response(
    llm_response: str,
    output_model: Optional[Type[BaseModel]] = None,
) -> Union[BaseModel, Dict[str, Any], List[Any]]:
    """Extract and parse JSON from LLM response code blocks.

    Finds the last ```json ... ``` block in *llm_response*, validates it,
    and optionally parses it into a Pydantic model.

    Args:
        llm_response: Raw LLM response string containing a JSON code block.
        output_model: Optional Pydantic model class to validate/parse into.

    Returns:
        Parsed JSON data as dict, list, or Pydantic model instance.

    Raises:
        ValueError: If no JSON block found, content is empty, or JSON is invalid.
    """
    matches = re.findall(r'```json(.*?)```', llm_response, re.DOTALL)
    if not matches:
        preview = llm_response[:200] if len(llm_response) > 200 else llm_response
        error_msg = f"No JSON code block found in LLM answer. Response preview: {preview}"
        logger.error(error_msg)
        raise ValueError(error_msg)

    json_str = matches[-1].strip()
    if not json_str:
        preview = llm_response[:200] if len(llm_response) > 200 else llm_response
        error_msg = f"Empty JSON content found in code block. Response preview: {preview}"
        logger.error(error_msg)
        raise ValueError(error_msg)

    try:
        if output_model:
            return output_model.model_validate_json(json_str)
        return json.loads(json_str)
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON format: {e}")
        raise ValueError(f"Invalid JSON format: {e}") from e
    except Exception as e:
        logger.error(f"Failed to parse JSON into model: {e}")
        raise
