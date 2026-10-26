"""The server renderer owns previews and issuance, including escaping and print fonts."""
from copy import deepcopy
from types import SimpleNamespace
from app.services.report_document import render
from app.services.report_html import CATALOGUE


def test_server_renderer_preserves_order_escapes_input_and_embeds_fonts():
    session = SimpleNamespace(session_number="TEST-HTML", title="Report", investigators=[])
    first = {"id": "one", "type": "statement", "values": {"statement_name": "First"},
             "identity_checked": False, "attestation_confirmed": False,
             "entries": [{"id": "entry-one", "question": "Where?", "answer": '<script>alert("test")</script> & text'}]}
    note = {"id": "two", "type": "note", "values": {"note_text": "ملاحظة اختبار", "note_date": "2026-10-25"}}
    second = {**deepcopy(first), "id": "three", "values": {"statement_name": "Second"}}
    document = {"revision": CATALOGUE["revision"], "subject": "HTML", "investigator_id": None,
                "clerk_id": None, "blocks": [first, note, second]}
    original = deepcopy(document)
    html = render(document, session)
    assert html.index('data-block-id="one"') < html.index('data-block-id="two"') < html.index('data-block-id="three"')
    assert "<script>" not in html and "&lt;script&gt;" in html
    assert "ملاحظة اختبار" in html and "مسودة" in html
    assert "IBM Plex Sans Arabic" in html and "Inter" in html and "data:font/woff2;base64," in html
    assert 'dir="rtl"' in html and "Content-Security-Policy" in html
    assert CATALOGUE["clauses"]["attestation"] not in html
    assert document == original


def test_long_bilingual_document_generates_paginated_pdf():
    import re
    from app.services.report_document import pdf_from_html
    session = SimpleNamespace(session_number="TEST-PAGINATION", title="Pagination", investigators=[])
    document = {"revision": CATALOGUE["revision"], "subject": "مراجعة الأدلة / Evidence review",
                "investigator_id": None, "clerk_id": None, "blocks": [{
                    "id": "long-statement", "type": "statement", "identity_checked": False,
                    "attestation_confirmed": False, "values": {"statement_name": "اسم صاحب الإفادة"},
                    "entries": [{"id": f"entry-{index}", "question": f"السؤال {index} / Question {index}",
                                 "answer": "إفادة واضحة قابلة للقراءة. Reviewed evidence remains traceable. " * 8}
                                for index in range(40)]}]}
    pdf = pdf_from_html(render(document, session))
    assert pdf.startswith(b"%PDF")
    assert len(re.findall(rb"/Type\s*/Page\b", pdf)) >= 3
