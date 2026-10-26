"""Canonical intake requirements shared by forms, workflow gates and report assembly."""
from datetime import datetime, timezone
import re
from fastapi import HTTPException

REVISION = "participant-intake-1"
DETAIL_FIELDS = [
    ("father_name", "اسم الأب"), ("mother_name", "اسم الأم وشهرتها"),
    ("birth_year", "سنة الولادة"), ("birth_place", "بلدة الولادة"),
    ("district", "قضاء الولادة"), ("residence", "عنوان الإقامة"),
    ("phone", "رقم الهاتف"), ("family_status", "الحالة العائلية والأولاد"),
    ("education", "المستوى التعليمي"), ("occupation_statement", "المهنة أو الرتبة والوحدة والمهمة"),
    ("prior_record_statement", "التصريح عن السوابق"),
]
FIELDS = [
    {"key": key, "label": label, "owner": "statement_details", "applies": "all",
     "exceptions": ["UNKNOWN", "REFUSED"] + (["NOT_APPLICABLE"] if key == "phone" else [])}
    for key, label in DETAIL_FIELDS
] + [
    {"key": key, "label": label, "owner": "participant", "applies": applies,
     "exceptions": ["UNKNOWN", "REFUSED"]}
    for key, label, applies in [
        ("subject_name", "اسم الشخص أو وصفه المسجل", "all"),
        ("security_branch", "الجهاز العسكري", "military"), ("rank", "الرتبة", "military"),
        ("military_id", "الرقم العسكري", "military"), ("unit", "الوحدة", "military"),
        ("nationality_code", "الجنسية", "civilian"),
        ("register_number", "رقم السجل", "lebanese"),
        ("caza_code", "قضاء محل القيد", "lebanese"),
        ("place_of_registration", "محل القيد بالتفصيل", "lebanese"),
        ("documents", "وثائق الهوية أو سبب عدم توفرها", "all"),
    ]
]
FIELDS[11]["exceptions"] = []  # A recorded name/designation remains mandatory.
FIELDS.append({"key": "person_type", "label": "نوع الشخص", "owner": "participant", "applies": "all", "exceptions": ["UNKNOWN"]})
for definition in FIELDS:
    definition.update(required_stage="START", canonical_path=f"subjects.{definition['owner'] + '.' if definition['owner'] == 'statement_details' else ''}{definition['key']}",
                      validation="nonblank_or_reasoned_exception")
BY_KEY = {f["key"]: f for f in FIELDS}
EXCEPTION_LABELS = {"UNKNOWN": "غير معلوم", "REFUSED": "امتنع عن التصريح", "NOT_APPLICABLE": "لا ينطبق"}


def enum_value(value):
    return getattr(value, "value", value)


def applies(field, person):
    kind = enum_value(person.person_type)
    return field["applies"] == "all" or (
        field["applies"] == "military" and kind == "MILITARY"
    ) or (field["applies"] == "civilian" and kind == "CIVILIAN") or (
        field["applies"] == "lebanese" and kind == "CIVILIAN"
        and person.nationality_code == "LB" and not person.is_unregistered
    )


def value_for(person, key):
    if key == "person_type":
        return "" if enum_value(person.person_type) == "UNKNOWN" else enum_value(person.person_type)
    if key == "documents":
        return bool(person.documents) or bool(person.is_undocumented and person.undocumented_reason)
    if key == "occupation_statement":
        explicit = (person.statement_details or {}).get(key, "")
        return explicit or " — ".join(v for v in [person.rank, person.unit, person.department] if v)
    if key == "nationality_code":
        return person.nationality_code or person.nationality_name
    if BY_KEY[key]["owner"] == "statement_details":
        return (person.statement_details or {}).get(key)
    return getattr(person, key, None)


def valid_exception(key, exception):
    return (key in BY_KEY and isinstance(exception, dict)
            and exception.get("status") in BY_KEY[key]["exceptions"]
            and isinstance(exception.get("reason"), str)
            and not re.search(r"[\u202a-\u202e\u2066-\u2069]", exception["reason"])
            and 3 <= len(exception.get("reason", "").strip()) <= 2000)


def stamp_exceptions(incoming, previous, user_id):
    result = {}
    for key, exception in incoming.items():
        if not valid_exception(key, exception):
            raise HTTPException(422, detail={"code": "invalid_field_exception", "field": key})
        value = {"status": exception["status"], "reason": exception["reason"].strip()}
        old = (previous or {}).get(key, {})
        result[key] = old if all(old.get(k) == v for k, v in value.items()) else {
            **value, "by": str(user_id), "at": datetime.now(timezone.utc).isoformat(), "revision": REVISION}
    return result


def participant_issues(person):
    issues = []
    for field in FIELDS:
        if not applies(field, person):
            continue
        value = value_for(person, field["key"])
        present = bool(str(value).strip()) if value is not None and value is not False else False
        exception = (getattr(person, "field_exceptions", None) or {}).get(field["key"])
        if present and not exception:
            continue
        if not present and valid_exception(field["key"], exception):
            continue
        issues.append({"code": "participant_exception_conflict" if present and exception else "participant_field_required", "participant_key": str(person.participant_key),
                       "person_name": person.subject_name, "field": field["key"], "label": field["label"],
                       "target": f"participant-{person.participant_key}-{field['key']}"})
    return issues


def readiness(session):
    issues = []
    for key, label in [("title", "موضوع الجلسة"), ("location", "مكان الجلسة"), ("session_date", "تاريخ الجلسة")]:
        if not str(getattr(session, key, None) or "").strip():
            issues.append({"code": "session_field_required", "participant_key": None,
                           "field": key, "label": label, "target": f"session-{key}"})
    if sum(enum_value(i.assignment_role) == "LEAD" for i in session.investigators) != 1:
        issues.append({"code": "exactly_one_lead_required", "participant_key": None,
                       "field": "investigators", "label": "محقق رئيسي واحد", "target": "session-investigators"})
    for person in session.subjects:
        if not getattr(person, "removed_at", None):
            issues.extend(participant_issues(person))
    return {"revision": REVISION, "ready": not issues, "issues": issues}


def require_ready(session):
    result = readiness(session)
    if not result["ready"]:
        raise HTTPException(409, detail={"code": "participant_details_incomplete", **result})


def report_exception(person, key):
    value = (getattr(person, "field_exceptions", None) or {}).get(key)
    return f"{EXCEPTION_LABELS[value['status']]} ({value['reason']})" if valid_exception(key, value) else ""
