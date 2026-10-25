"""Plain-text template definitions, with no filled case data or executable HTML."""
import re
import uuid
from sqlalchemy import select
from app.models import ReportNoteTemplate

PLACEHOLDER = re.compile(r"\{([\w\u0600-\u06ff ]{1,60})\}")


def fields_for(body):
    return list(dict.fromkeys(PLACEHOLDER.findall(body)))


def validate_body(body):
    remainder = PLACEHOLDER.sub("", body)
    if "{" in remainder or "}" in remainder or len(fields_for(body)) > 20 or re.search(r"[\u202a-\u202e\u2066-\u2069]", body):
        raise ValueError("Invalid note placeholders")
    return body


def definition(key, title, body):
    return {"id": str(key), "title": title, "body": body, "fields": fields_for(body)}


BUILTINS = [definition(uuid.uuid5(uuid.NAMESPACE_URL, "mstt-note:" + key), title, body) for key, title, body in [
    ("consultation", "مراجعة جهة", "بعد مراجعة {الجهة} بشخص {الاسم والرتبة} وإطلاعه على {موضوع المراجعة}، تقرر {الإجراء}."),
    ("expert", "تكليف خبير", "تقرر تكليف {الخبير أو الجهة} بإجراء {المهمة المطلوبة} بشأن {الموضوع}، على أن {تعليمات المتابعة}."),
    ("document", "استلام مستند", "استلمنا من {الجهة أو الشخص} {وصف المستند}، وأرفق بالمحضر تحت المرجع {مرجع المستند}.")
]]


def list_templates(db):
    return [*BUILTINS, *[definition(t.id, t.title, t.body) for t in db.scalars(
        select(ReportNoteTemplate).order_by(ReportNoteTemplate.created_at, ReportNoteTemplate.id)).all()]]


def get_template(db, template_id):
    return next((t for t in list_templates(db) if t["id"] == str(template_id)), None)


def render(template, values):
    if set(values) - set(template["fields"]):
        raise ValueError("html_report_unknown_note_variable")
    text = PLACEHOLDER.sub(lambda m: values.get(m[1], "").strip() or f"[{m[1]}]", template["body"])
    if len(text) > 40000:
        raise ValueError("html_report_note_too_long")
    return text
