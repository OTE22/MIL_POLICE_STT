"""Optional Arabic-formalization support for the محضر.

The whole report workflow runs without any of this. When a model IS available it only ever
SUGGESTS wording, which a human then approves, edits or rejects.
"""

from app.services.llm.base import (
    FUSHA_SYSTEM_PROMPT,
    FormalizationResult,
    FormalizationUnavailable,
    LLMProvider,
    ProviderInfo,
    source_hash,
)
from app.services.llm.service import ArabicFormalizationService, resolve_provider

__all__ = [
    "ArabicFormalizationService",
    "FormalizationResult",
    "FormalizationUnavailable",
    "FUSHA_SYSTEM_PROMPT",
    "LLMProvider",
    "ProviderInfo",
    "resolve_provider",
    "source_hash",
]
