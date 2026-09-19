"""What every Arabic-formalization provider must offer, and the prompt they all share.

The report code never talks to a model. It talks to `ArabicFormalizationService`, which
talks to a provider, which owns the runtime. That seam is what lets development use the
hosted NVIDIA catalogue while production runs strictly on local hardware, without a single
line of report logic knowing the difference.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

# Fixed, controlled, and deliberately narrow. The model is an Arabic LANGUAGE editor: it may
# change how a sentence is said and nothing about what it says. Every "MUST NOT" here exists
# because the output goes into an official investigation file.
FUSHA_SYSTEM_PROMPT = """أنت محرّر لغوي عربي لمحاضر التحقيق الرسمية.

حوّل النص العامي اللبناني المعطى إلى عربية فصحى واضحة.

يجب أن تحافظ حرفياً على:
- أسماء الأشخاص
- الرتب
- الجهات والمؤسسات
- الأماكن
- التواريخ
- الأوقات
- الأرقام والكميات
- النفي
- عدم اليقين والتشكيك
- نسبة القول إلى قائله
- التسلسل الزمني
- الوقائع كما وردت

يُمنع منعاً باتاً أن:
- تلخّص
- تختلق وقائع
- تحذف وقائع
- تستنتج وقائع غير مذكورة
- تحسم التناقضات
- تقوّي الاتهام
- تضعّف الإفادة
- تغيّر قائل الكلام
- تخترع أسماء أو أماكن أو تواريخ
- تضيف مصطلحات أو استنتاجات قانونية

أعد النص المصاغ بالفصحى فقط، بلا مقدمات ولا شروح ولا تعليقات."""

# Some chat models emit a reasoning block. We neither ask for it nor keep it: only the final
# Arabic text is ever stored or shown (spec: no hidden reasoning in an official record).
_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


class FormalizationUnavailable(Exception):
    """No approved provider can serve this request. Never fatal - the operator types it."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class FormalizationResult:
    """A SUGGESTION plus the provenance that makes it auditable. Never an approval."""

    suggested_text: str
    provider: str
    runtime: str
    model: str
    temperature: float
    source_text_hash: str
    generated_at: datetime

    def provenance(self) -> dict:
        """What gets stored on the Q&A block. No key, no prompt, no reasoning."""
        return {
            "provider": self.provider,
            "runtime": self.runtime,
            "model": self.model,
            "temperature": self.temperature,
            "source_text_hash": self.source_text_hash,
            "generated_at": self.generated_at.isoformat(),
        }


@dataclass(frozen=True)
class ProviderInfo:
    """What /api/llm/capabilities may safely say about the resolved runtime."""

    provider: str  # "nvidia_nim" | "local" | "none"
    runtime: str  # "nim" | "ollama" | "none"
    execution: str  # "cloud" | "cpu" | "gpu" | "none"
    model: str | None
    resolved_profile: str | None = None
    fallback_reason: str | None = None
    gpu_count: int | None = None
    vram_gb: float | None = None
    system_ram_gb: float | None = None


class LLMProvider(Protocol):
    """A runtime that can complete a chat prompt. Implementations must never log the key."""

    def info(self) -> ProviderInfo: ...

    def available(self) -> bool: ...

    def complete(
        self, *, system: str, user: str, temperature: float, max_tokens: int, timeout: float
    ) -> str: ...


def source_hash(text: str) -> str:
    """Ties a suggestion to the exact text it was made for - so a later edit invalidates it."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def clean_model_text(raw: str) -> str:
    """Strip reasoning blocks and chat scaffolding; keep the Arabic and nothing else."""
    text = _THINK_BLOCK.sub("", raw or "")
    text = text.strip()
    # Models sometimes wrap the answer in quotes or a code fence despite the instruction.
    if text.startswith("```"):
        lines = [line for line in text.splitlines() if not line.strip().startswith("```")]
        text = "\n".join(lines).strip()
    if len(text) >= 2 and text[0] in "\"«“" and text[-1] in "\"»”":
        text = text[1:-1].strip()
    return text


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
