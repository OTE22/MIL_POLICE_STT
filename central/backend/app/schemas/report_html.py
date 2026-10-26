"""Only typed text and references enter; HTML and source snapshots are not accepted."""
from __future__ import annotations

import re
import uuid
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from app.services.report_html import CATALOGUE, FIELDS, NOTE_FIELDS


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReportReferences(StrictModel):
    participants: list[uuid.UUID] = Field(default_factory=list, max_length=100)
    recordings: list[uuid.UUID] = Field(default_factory=list, max_length=100)
    documents: list[uuid.UUID] = Field(default_factory=list, max_length=100)
    blocks: list[uuid.UUID] = Field(default_factory=list, max_length=100)


class StatementEntry(StrictModel):
    id: uuid.UUID
    question: str = Field(default="", max_length=20000)
    answer: str = Field(default="", max_length=40000)
    source_block_ids: list[uuid.UUID] = Field(default_factory=list, max_length=500)


class StatementBlock(StrictModel):
    id: uuid.UUID
    type: Literal["statement"]
    speaker_id: uuid.UUID | None = None
    participant_key: uuid.UUID | None = None
    identity_id: uuid.UUID | None = None
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
    references: ReportReferences = Field(default_factory=ReportReferences)
    template_id: uuid.UUID | None = None
    template_values: dict[str, str] = Field(default_factory=dict, max_length=20)
    values: dict[str, str] = Field(default_factory=dict, max_length=len(NOTE_FIELDS))

    @field_validator("values")
    @classmethod
    def valid_values(cls, values):
        if set(values) - NOTE_FIELDS or any(len(v) > (40000 if k == "note_text" else 10000) for k, v in values.items()):
            raise ValueError("Unknown or oversized note field")
        return values

    @field_validator("template_values")
    @classmethod
    def valid_template_values(cls, values):
        if any(len(k) > 60 or len(v) > 4000 for k, v in values.items()):
            raise ValueError("Oversized note variable")
        return values


class ResponsibilityFinding(StrictModel):
    id: uuid.UUID
    participant_key: uuid.UUID | None = None
    unidentified_subject: str = Field(default="", max_length=1000)
    text: str = Field(default="", max_length=40000)
    references: ReportReferences = Field(default_factory=ReportReferences)


class ConclusionBlock(StrictModel):
    id: uuid.UUID
    type: Literal["conclusion"]
    values: dict[str, str] = Field(default_factory=dict, max_length=7)
    responsibility_mode: Literal["UNREVIEWED", "FINDINGS", "NONE"] = "UNREVIEWED"
    proposal_mode: Literal["UNREVIEWED", "TEXT", "NONE"] = "UNREVIEWED"
    findings: list[ResponsibilityFinding] = Field(default_factory=list, max_length=100)
    references: ReportReferences = Field(default_factory=ReportReferences)

    @field_validator("values")
    @classmethod
    def valid_values(cls, values):
        keys = {"facts", "inference", "proposals", "closing_date", "closing_location", "investigator_name", "clerk_name"}
        if set(values) - keys or any(len(value) > 40000 for value in values.values()):
            raise ValueError("Unknown or oversized conclusion field")
        return values


ReportBlock = Annotated[StatementBlock | NoteBlock | ConclusionBlock, Field(discriminator="type")]


class HtmlReportDocument(StrictModel):
    session_id: uuid.UUID | None = None
    revision: Literal["statement-html-1", "investigation-html-2"] = "investigation-html-2"
    subject: str = Field(default="", max_length=500)
    investigator_id: uuid.UUID | None = None
    clerk_id: uuid.UUID | None = None
    blocks: list[ReportBlock] = Field(default_factory=list, max_length=500)

    @model_validator(mode="after")
    def bounded_unique_content(self):
        if sum(b.type == "conclusion" for b in self.blocks) > 1:
            raise ValueError("Only one investigation conclusion is permitted")
        identifiers = [str(b.id) for b in self.blocks] + [str(e.id) for b in self.blocks if b.type == "statement" for e in b.entries]
        identifiers += [str(f.id) for b in self.blocks if b.type == "conclusion" for f in b.findings]
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("Duplicate block or entry ID")
        text = self.model_dump_json()
        if len(text) > 2_000_000 or re.search(r"[\u202a-\u202e\u2066-\u2069]", text):
            raise ValueError("Invalid or oversized document")
        return self


class HtmlReportUpdate(StrictModel):
    expected_token: str = Field(pattern=r"^[a-f0-9]{64}$")
    document: HtmlReportDocument


class StatementSelection(StrictModel):
    participant_key: uuid.UUID | None = None
    identity_id: uuid.UUID | None = None
    speaker_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def one_selection(self):
        if sum(value is not None for value in (self.participant_key, self.identity_id, self.speaker_id)) != 1:
            raise ValueError("Select one session participant or speaker")
        return self


class NoteTemplateCreate(StrictModel):
    title: str = Field(min_length=1, max_length=150)
    body: str = Field(min_length=1, max_length=10000)

    @field_validator("title", "body")
    @classmethod
    def nonempty(cls, value):
        if not value.strip():
            raise ValueError("Empty template")
        from app.services.note_templates import validate_body
        return validate_body(value.strip())
