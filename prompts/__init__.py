"""Task-scoped prompt templates with legacy constant compatibility."""

from .loader import PromptTemplate, get_system_prompt, get_user_prompt, load_prompt
from .registry import PROMPT_TASKS, list_prompt_tasks, validate_prompt_registry
from .templates import *  # noqa: F401,F403
