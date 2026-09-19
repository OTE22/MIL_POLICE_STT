"""Reject retired identity fields instead of silently duplicating people for stale clients."""
from pydantic import BaseModel, model_validator


class PersonInput(BaseModel):
    @model_validator(mode="before")
    @classmethod
    def reject_retired_reference(cls, data):
        if isinstance(data, dict) and ({"reference_number", "person_reference"} & data.keys()):
            raise ValueError("person reference numbers were retired; reload the application and select a person")
        return data
