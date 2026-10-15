"""Chat provider module for configuring the OpenRouter chat model."""

from enum import StrEnum
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_openrouter import ChatOpenRouter
from pydantic import BaseModel

from app.infra.settings import get_settings

MAX_TOKENS = 16_000
MAX_RETRIES = 2


class ChatUnavailableError(RuntimeError):
    """Raised when ``OPENROUTER_API_KEY`` is not configured."""


class ModelsEnum(StrEnum):
    """Enum for the supported chat models."""

    NEMOTRON_3_5_LIGHTNING = 'nemotron-3.5-lightning'
    GPT_OSS_120B = 'gpt-oss-120b'
    GPT_6_LUNA = 'gpt-6-luna'
    CLAUDE_HAIKU_5_5 = 'claude-haiku-5.5'


class ModelConfig(BaseModel):
    """Configuration for the chat model."""

    model_id: str
    max_tokens: int = MAX_TOKENS
    config: dict[str, Any] = {}


MODEL_CATALOG: dict[ModelsEnum, ModelConfig] = {
    ModelsEnum.NEMOTRON_3_5_LIGHTNING: ModelConfig(
        model_id='nvidia/nemotron-3.5-lightning:free',
        config={
            'reasoning': {
                'enabled': True,
                'effort': 'high',
                'exclude': False,
            }
        },
    ),
    ModelsEnum.GPT_OSS_120B: ModelConfig(
        model_id='openai/gpt-oss-120b',
        config={
            'reasoning_effort': 'low',
            'openrouter_provider': {
                'order': ['baseten/fp4', 'groq'],
                'sort': 'price',
                'allow_fallbacks': True,
            },
        },
    ),
    ModelsEnum.GPT_6_LUNA: ModelConfig(
        model_id='openai/gpt-6-luna',
        config={
            'reasoning_effort': 'low',
            'openrouter_provider': {
                'order': ['amazon-bedrock/us-east-1'],
                'sort': 'price',
                'allow_fallbacks': True,
            },
        },
    ),
    ModelsEnum.CLAUDE_HAIKU_5_5: ModelConfig(
        model_id='anthropic/claude-haiku-5.5',
        config={
            'reasoning': {'effort': 'low'},
            'openrouter_provider': {
                'order': ['google-vertex/europe'],
                'sort': 'price',
                'allow_fallbacks': True,
            },
        },
    ),
}


DEFAULT_MODEL_ID = ModelsEnum.GPT_6_LUNA


def get_chat(model_id: ModelsEnum = DEFAULT_MODEL_ID) -> BaseChatModel:
    """Return a configured chat model.

    Parameters
    ----------
    model_id : ModelsEnum, optional
        The model to use for the chat model. Defaults to `DEFAULT_MODEL_ID`.

    Returns
    -------
    BaseChatModel
        A configured OpenRouter chat model instance.

    Raises
    ------
    ChatUnavailableError
        If ``OPENROUTER_API_KEY`` is not configured.
    """
    settings = get_settings()
    # An empty OPENROUTER_API_KEY= in .env arrives as an empty secret.
    api_key = (
        settings.openrouter_api_key.get_secret_value()
        if settings.openrouter_api_key
        else ''
    )
    if not api_key:
        raise ChatUnavailableError('OPENROUTER_API_KEY is not configured.')

    model_config: ModelConfig = MODEL_CATALOG[model_id]

    return ChatOpenRouter(
        api_key=api_key,
        max_retries=MAX_RETRIES,
        model=model_config.model_id,
        max_tokens=model_config.max_tokens,
        **model_config.config,
    )


__all__ = (
    'DEFAULT_MODEL_ID',
    'MODEL_CATALOG',
    'ChatUnavailableError',
    'ModelConfig',
    'ModelsEnum',
    'get_chat',
)
