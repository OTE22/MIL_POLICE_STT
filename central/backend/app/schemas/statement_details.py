"""Optional facts as recorded for a participant in ONE session."""
import re
from pydantic import BaseModel, ConfigDict, Field, field_validator

DETAIL_KEYS = {"father_name", "mother_name", "birth_year", "birth_place", "district",
               "residence", "phone", "family_status", "education", "occupation_statement", "prior_record_statement"}


def validate_details(values):
    if set(values) - DETAIL_KEYS or any(len(v) > 2000 or re.search(r"[\u202a-\u202e\u2066-\u2069]", v) for v in values.values()):
        raise ValueError("Invalid statement details")
    if any(v.strip() in {"غير معلوم", "امتنع عن التصريح", "لا ينطبق"} for v in values.values()):
        raise ValueError("Record unavailable details as field exceptions with a reason")
    year = values.get("birth_year", "").strip()
    if year:
        from datetime import date
        if not year.isdecimal() or not 1800 <= int(year) <= date.today().year:
            raise ValueError("Invalid birth year")
    return values


class StatementDetailsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_token: str = Field(pattern=r"^[a-f0-9]{64}$")
    values: dict[str, str] = Field(default_factory=dict, max_length=len(DETAIL_KEYS))
    _validate = field_validator("values")(validate_details)
