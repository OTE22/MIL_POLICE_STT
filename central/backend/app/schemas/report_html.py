"""Only typed text and references enter; HTML and source snapshots are not accepted."""
from __future__ import annotations

import re
import uuid
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from app.services.report_html import CATALOGUE, FIELDS, NOTE_FIELDS


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StatementEntry(StrictModel):
    id: uuid.UUID
    question: str = Field(default="", max_length=20000)
    answer: str = Field(default="", max_length=40000)
    source_block_ids: list[uuid.UUID] = Field(default_factory=list, max_length=500)


class StatementBlock(StrictModel):
    id: uuid.UUID
    type: Literal["statement"]
    speaker_id: uuid.UUID | None = None
    values: dict[str, str] = Field(default_factory=dict, max_length=len(FIELDS))
    identity_checked: bool = False
    attestation_confirmed: bool = False
    entries: list[StatementEntry] = Field(default_factory=list, max_length=500)

    @field_validator("values")
    @classmethod
    def valid_values(cls, values):
        if set(values) - FIELDS or any(len(v) > 10000 for v in values.values()):
            raise ValueError("Unknown or oversized field")
        return values


class NoteBlock(StrictModel):
    id: uuid.UUID
    type: Literal["note"]
    values: dict[str, str] = Field(default_factory=dict, max_length=len(NOTE_FIELDS))

    @field_validator("values")
    @classmethod
    def valid_values(cls, values):
        if set(values) - NOTE_FIELDS or any(len(v) > (40000 if k == "note_text" else 10000) for k, v in values.items()):
            raise ValueError("Unknown or oversized note field")
        return values


ReportBlock = Annotated[StatementBlock | NoteBlock, Field(discriminator="type")]


class HtmlReportDocument(StrictModel):
    revision: Literal["statement-html-1"] = CATALOGUE["revision"]
    subject: str = Field(default="", max_length=500)
    investigator_id: uuid.UUID | None = None
    blocks: list[ReportBlock] = Field(default_factory=list, max_length=500)

    @model_validator(mode="after")
    def bounded_unique_content(self):
        identifiers = [str(b.id) for b in self.blocks] + [str(e.id) for b in self.blocks if b.type == "statement" for e in b.entries]
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("Duplicate block or entry ID")
        text = self.model_dump_json()
        if len(text) > 2_000_000 or re.search(r"[\u202a-\u202e\u2066-\u2069]", text):
            raise ValueError("Invalid or oversized document")
        return self


class HtmlReportUpdate(StrictModel):
    expected_token: str = Field(pattern=r"^[a-f0-9]{64}$")
    document: HtmlReportDocument
