"""Only values and requested confirmations enter; identity/time/hash stay server-owned."""
import re
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.services.report_m53 import AUTOMATIC, CONFIRMATIONS, FIELDS


class M53Update(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_token: str = Field(pattern=r"^[a-f0-9]{64}$")
    enabled: bool
    values: dict[str, str] = Field(max_length=60)
    confirmations: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("values")
    @classmethod
    def known_values(cls, values):
        if set(values) - (FIELDS - AUTOMATIC):
            raise ValueError("Unknown or server-owned form field")
        if sum(len(value) for value in values.values()) > 120000:
            raise ValueError("Form is too large")
        for key, value in values.items():
            limit = 20000 if key.startswith("human_") or key == "procedural_decision" else 2000
            if len(value) > limit or re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\u202a-\u202e\u2066-\u2069]", value):
                raise ValueError("Invalid or oversized form field")
        return values

    @field_validator("confirmations")
    @classmethod
    def known_confirmations(cls, values):
        if set(values) - set(CONFIRMATIONS):
            raise ValueError("Unknown confirmation")
        return list(dict.fromkeys(values))
