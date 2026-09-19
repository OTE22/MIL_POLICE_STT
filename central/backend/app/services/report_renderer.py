"""Filling the official Word template — and refusing to open one we do not trust.

The organisation owns the layout: letterhead, fonts, RTL styles, the هامش column, signature
blocks, page borders, headers and footers all live in a real .docx authored in Word. This
module only substitutes Jinja placeholders inside it.

Two rules shape the code:

* **StrictUndefined at render.** A silently blank field in an official document is worse
  than a loud error. Safe to be strict because `build_context` emits every catalogued key
  (empty string / empty list when absent), so StrictUndefined can only fire on a template
  typo — which activation already catches with a dry run.
* **Sandboxed Jinja over a plain-dict context.** The template is admin-supplied content, so
  it never gets attribute access to ORM objects or Python internals.
"""

from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass

from docxtpl import DocxTemplate
from jinja2 import StrictUndefined
from jinja2.exceptions import TemplateError, UndefinedError
from jinja2.sandbox import SandboxedEnvironment

from app.services.report_storage import InvalidDocxError, sniff_docx

# The placeholder catalogue: exactly what a template may use. Anything else in the template
# is a typo or an attempt to reach further, and activation refuses it.
SCALAR_PLACEHOLDERS = {
    "report_number",
    "case_subject",
    "report_date",
    "report_time",
    "report_datetime",
    "investigation_location",
    "session_number",
    "session_title",
    "session_date",
    "session_status",
    "investigator_name",
    "investigator_rank",
    "investigator_unit",
    "subject_name",
    "subject_rank",
    "subject_person_type",
    "subject_nationality",
    "intro_text",
    "closing_text",
    "transcript_source_label",
    "generated_at",
    "generated_by_name",
    "report_version",
    "template_version",
    "template_notice",
    "qa_count",
    "recording_count",
}
LIST_PLACEHOLDERS = {
    "qa_blocks",        # {question, answer, question_speaker, answer_speaker, index, ...}
    "investigators",    # {name, rank, reference}
    "subjects",         # {name, rank, reference, person_type}
    "recordings",       # {index, filename, included, duration, transcript_id}
    "speakers",         # {label, name, role, resolved, reference}
    "excluded_blocks",  # what was left out, so exclusion is visible on the document
    "edits",            # human corrections quoted by the report
}
ALLOWED_PLACEHOLDERS = SCALAR_PLACEHOLDERS | LIST_PLACEHOLDERS

# The dialogue loop is the whole point of a dynamic محضر: one template must print 5 or 300
# questions. A template without it cannot carry the interview.
REQUIRED_PLACEHOLDERS = {"qa_blocks"}

# Word "field codes" ({ DATE }, { PAGE } inside fldChar runs) refresh when the document is
# opened, so a printed page can differ from the archived bytes. Warned about, not refused:
# page numbering is a legitimate use in a footer.
FIELD_CODE_MARKER = "fldChar"


def _field_code_parts(data: bytes) -> list[str]:
    """Which document parts carry Word field codes.

    Must look INSIDE the archive: a .docx stores its XML deflated, so searching the raw
    bytes for "fldChar" silently never matches - which is exactly how this warning came to
    be dead on arrival.
    """
    found = []
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            for name in zf.namelist():
                if not name.startswith("word/") or not name.endswith(".xml"):
                    continue
                if FIELD_CODE_MARKER in zf.read(name).decode("utf-8", "ignore"):
                    found.append(name.split("/")[-1])
    except (zipfile.BadZipFile, OSError):
        return []
    return found


@dataclass
class TemplateValidation:
    ok: bool
    message: str
    used_placeholders: list[str]
    warnings: list[str]


class RenderError(Exception):
    def __init__(self, code: str, detail: str | None = None):
        super().__init__(code)
        self.code = code
        self.detail = detail


def _environment() -> SandboxedEnvironment:
    """Sandboxed, strict, and autoescaping — the template is untrusted admin content."""
    return SandboxedEnvironment(undefined=StrictUndefined, autoescape=True)


# XML 1.0 forbids most control characters; a stray one from a transcript would corrupt the
# document rather than merely look wrong.
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def sanitize(value):
    """Make one context value safe to place in OOXML, without changing what it says."""
    if isinstance(value, str):
        return _CONTROL_CHARS.sub("", value)
    if isinstance(value, dict):
        return {k: sanitize(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [sanitize(v) for v in value]
    return value


def sample_context() -> dict:
    """A shape-complete context for the dry run: every catalogued key, plausible values.

    Shape-complete is what makes StrictUndefined safe at render time - if a template renders
    against this, the only way it can fail later is a key that is not in the catalogue, and
    validation has already rejected those.
    """
    qa = [
        {
            "index": 1,
            "number": "١",
            "question": "ما اسمك الكامل؟",
            "answer": "علي عباس",
            "question_speaker": "المحقق",
            "answer_speaker": "علي عباس",
            "recording": "التسجيل ١",
            "time_range": "00:01:05 - 00:01:12",
            "edited": False,
        }
    ]
    return {
        **{key: f"[{key}]" for key in SCALAR_PLACEHOLDERS},
        "qa_count": len(qa),
        "recording_count": 1,
        "report_version": 1,
        "template_version": 1,
        "qa_blocks": qa,
        "investigators": [{"name": "علي عباس", "rank": "رائد"}],
        "subjects": [
            {"name": "وليد الايوبي", "rank": "", "person_type": "عسكري"}
        ],
        "recordings": [
            {"index": 1, "filename": "interview.wav", "included": True, "duration": "00:12:30", "transcript_id": "…"}
        ],
        "speakers": [
            {"label": "SPEAKER_00", "name": "علي عباس", "role": "محقق", "resolved": True}
        ],
        "excluded_blocks": [{"index": 2, "reason": "اختبار الميكروفون", "excerpt": "تجربة"}],
        "edits": [{"index": 1, "editor": "علي عباس", "edited_at": "2026-08-29 10:00", "excerpt": "…"}],
    }


def _undeclared(template: DocxTemplate, env: SandboxedEnvironment) -> set[str]:
    return set(template.get_undeclared_template_variables(env))


def validate_template(data: bytes) -> TemplateValidation:
    """Everything that must be true before a template may become the active official form.

    Order matters: structure first (a zip bomb must never reach the XML parser), then Jinja
    syntax, then the placeholder catalogue, then a real dry render.
    """
    warnings: list[str] = []
    try:
        sniff_docx(data)
    except InvalidDocxError as exc:
        return TemplateValidation(False, f"template_{exc.code}", [], warnings)

    parts = _field_code_parts(data)
    if parts:
        # Legitimate for page numbering; worth saying out loud because such a field updates
        # when the document is OPENED, so a printed page can differ from the archived bytes.
        warnings.append(f"field_codes_present: {', '.join(sorted(set(parts)))}")

    env = _environment()
    try:
        template = DocxTemplate(io.BytesIO(data))
        used = _undeclared(template, env)
    except TemplateError as exc:
        return TemplateValidation(False, f"template_jinja_error: {exc}", [], warnings)
    except Exception as exc:  # malformed OOXML that got past the zip checks
        return TemplateValidation(False, f"template_unreadable: {exc}", [], warnings)

    unknown = sorted(used - ALLOWED_PLACEHOLDERS)
    if unknown:
        return TemplateValidation(False, f"template_unknown_placeholders: {', '.join(unknown)}", sorted(used), warnings)

    missing = sorted(REQUIRED_PLACEHOLDERS - used)
    if missing:
        return TemplateValidation(False, f"template_missing_placeholders: {', '.join(missing)}", sorted(used), warnings)

    try:
        # A real render, on a real template object - the only way to catch a {%tr%} in the
        # wrong place or a loop that breaks the table.
        probe = DocxTemplate(io.BytesIO(data))
        probe.render(sample_context(), env)
    except UndefinedError as exc:
        return TemplateValidation(False, f"template_undefined_at_render: {exc}", sorted(used), warnings)
    except Exception as exc:
        return TemplateValidation(False, f"template_render_failed: {exc}", sorted(used), warnings)

    return TemplateValidation(True, "template_valid", sorted(used), warnings)


def render(template_bytes: bytes, context: dict) -> bytes:
    """Produce the .docx. The context must already be complete - see build_context."""
    # Previously approved layouts may still contain retired placeholders. They render
    # empty during the transition; no reference values are read, generated or stored.
    # New templates must use the current catalogue and omit these fields.
    context = {**context, "investigator_reference": "", "subject_reference": ""}
    for collection in ("investigators", "subjects", "speakers"):
        context[collection] = [{**row, "reference": ""} for row in context.get(collection, [])]
    context["qa_blocks"] = [
        {**row, "question_speaker_reference": "", "answer_speaker_reference": ""}
        for row in context.get("qa_blocks", [])
    ]
    env = _environment()
    try:
        template = DocxTemplate(io.BytesIO(template_bytes))
        template.render(sanitize(context), env)
    except UndefinedError as exc:
        raise RenderError("report_template_undefined_field", str(exc)) from exc
    except TemplateError as exc:
        raise RenderError("report_template_invalid", str(exc)) from exc
    out = io.BytesIO()
    template.save(out)
    return out.getvalue()
