from copy import deepcopy
from datetime import date, time
from types import SimpleNamespace as NS
import uuid
import pytest
from pydantic import ValidationError
from app.schemas.report_html import HtmlReportDocument
from app.services.report_document import render
from app.services.report_opening import blockers, OATH, REVISION
from app.services.report_html import document_for
from app.models import ReportStatus


def example():
    lead, clerk = str(uuid.uuid4()), str(uuid.uuid4())
    session = NS(session_number="DEV-OPENING-001", title="تحقيق تجريبي", session_date=date(2026, 10, 27),
                 start_time=time(10, 30), location="مكتب التحقيق التجريبي", investigators=[
        NS(investigator_id=lead, investigator=NS(full_name="محقق تجريبي", rank="نقيب", unit="وحدة تجريبية", military_id="DEV-01")),
        NS(investigator_id=clerk, investigator=NS(full_name="كاتب تجريبي", rank="رقيب", unit="وحدة تجريبية", military_id="DEV-02"))])
    document = {"revision": REVISION, "subject": "واقعة افتراضية للاختبار", "investigator_id": lead, "clerk_id": clerk,
                "opening": {"referral_number": "DEV/123", "referral_date": "2026-10-26", "referral_authority": "جهة تجريبية",
                            "oath_confirmed": True, "uniform_confirmed": True}, "blocks": [{
                    "id": str(uuid.uuid4()), "type": "statement", "values": {"statement_name": "شخص تجريبي"},
                    "identity_checked": False, "attestation_confirmed": False,
                    "entries": [{"id": str(uuid.uuid4()), "question": "ما الذي شاهدته؟", "answer": "هذه إفادة تجريبية فقط.", "source_block_ids": []}]}]}
    return session, document


def test_opening_precedes_statement_and_preserves_locked_wording():
    session, document = example()
    before = deepcopy(document)
    html = render(document, session)
    assert html.index('data-block-id="opening"') < html.index('data-block-id="' + document['blocks'][0]['id'])
    assert OATH in html and "باشرنا التحقيق على الشكل التالي:" in html
    assert "وزارة الدفاع الوطني" in html and "الشرطة العسكرية" in html
    assert "DEV/123" in html and "10:30" in html and "تشرين الأول" in html
    assert html.count('<table ') == 1  # opening and first statement flow together
    assert not blockers(session, document)
    assert document == before


def test_unconfirmed_events_are_never_printed_as_facts_and_block_issue():
    session, document = example()
    document["opening"] = {}
    html = render(document, session)
    assert OATH not in html
    assert "والمرتدون اللباس العسكري" not in html
    assert "report_opening_confirmation_required" in blockers(session, document)
    assert "report_opening_referral_required" in blockers(session, document)
    document["opening"] = {"referral_number": "  ", "referral_date": "2026-10-27", "referral_authority": "  "}
    assert "report_opening_referral_required" in blockers(session, document)


def test_opening_schema_escaping_and_canonical_ownership():
    session, document = example()
    document["opening"]["referral_authority"] = '<script>alert(1)</script>'
    assert "&lt;script&gt;" in render(document, session)
    assert "<script>" not in render(document, session)
    HtmlReportDocument.model_validate(document)
    for key in ("location", "session_date", "investigator_name", "oath_text"):
        with pytest.raises(ValidationError):
            HtmlReportDocument.model_validate({**document, "opening": {**document["opening"], key: "override"}})
    with pytest.raises(ValidationError):
        HtmlReportDocument.model_validate({**document, "opening": {"referral_date": "not-a-date"}})


def test_draft_upgrade_preserves_content_and_does_not_upgrade_issued_document():
    _, document = example()
    document.pop("opening")
    document["revision"] = "investigation-html-2"
    draft = NS(session_id=uuid.uuid4(), status=ReportStatus.DRAFT, official_form={"html_report": document})
    before = deepcopy(draft.official_form)
    upgraded = document_for(draft)
    assert upgraded["revision"] == REVISION and upgraded["opening"] == {}
    assert upgraded["blocks"] == document["blocks"] and draft.official_form == before
    draft.status = ReportStatus.FINAL
    assert document_for(draft)["revision"] == "investigation-html-2"
    assert "opening" not in document_for(draft)


def test_opening_save_roundtrip_conflict_and_unknown_fields(client, investigator):
    from test_report_html import _setup, _save
    from conftest import auth
    token, _, _, path, state = _setup(client, investigator)
    _, sample = example()
    closing = {"text": "نظم وختم هذا التحقيق، للتفضل بالاطلاع.", "location": "مكتب التحقيق", "date": "2026-10-27"}
    document = {**state["document"], "opening": sample["opening"], "closing": closing}
    saved = _save(client, token, path, state, document)
    assert saved.status_code == 200, saved.text
    assert saved.json()["document"]["opening"] == sample["opening"]
    assert saved.json()["document"]["closing"] == closing
    assert "report_opening_clerk_required" in saved.json()["blocked_reasons"]
    assert _save(client, token, path, state, document).status_code == 409
    bad = {**document, "opening": {**sample["opening"], "oath_text": "injected"}}
    assert _save(client, token, path, saved.json(), bad).status_code == 422
    assert client.get(path, headers=auth(token)).json()["document"]["opening"] == sample["opening"]
