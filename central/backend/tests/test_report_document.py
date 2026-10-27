"""The server renderer owns previews and issuance, including escaping and print fonts."""
from copy import deepcopy
from types import SimpleNamespace
from app.services.report_document import render
from app.services.report_html import CATALOGUE


def test_print_prose_flows_soft_breaks_preserves_paragraphs_and_escapes():
    from app.services.report_document import prose
    assert prose("السطر الأول\nتكملة العبارة\n\nفقرة جديدة") == "السطر الأول تكملة العبارة<br><br>فقرة جديدة"
    assert prose("one\r\ntwo\r\n\r\nthree") == "one two<br><br>three"
    assert prose('<script>\n& text') == '&lt;script&gt; &amp; text'


def test_document_edit_targets_closing_and_clean_margins():
    from test_report_opening import example
    from app.schemas.report_html import HtmlReportDocument
    from app.services.report_finalize import content_blockers
    import re
    session, document = example()
    document['closing'] = {'text': 'نظم وختم هذا التحقيق <script> & للتفضل بالاطلاع.',
                           'location': 'مكتب التحقيق', 'date': '2026-10-27'}
    HtmlReportDocument.model_validate(document)
    html = render(document, session, highlight=True)
    assert 'data-edit-key="answer:' in html and 'data-edit-key="question:' in html
    assert 'data-edit-key="closing:text"' in html
    assert '<script>' not in html and '&lt;script&gt;' in html
    assert html.index('data-block-id="closing"') > html.index('data-block-id="' + document['blocks'][0]['id'])
    margins = re.findall(r'<td class="margin-marker">(.*?)</td>', html, re.S)
    assert document['subject'] not in ''.join(margins)
    assert 'س/ج' in ''.join(margins) and '<b>س:</b>' in html and '<b>ج:</b>' in html
    assert document['subject'] in html  # retained in the opening narrative
    assert 'data-edit-key=' not in render(document, session, issued=True)
    assert 'report_closing_details_required' not in content_blockers(session, {**document, 'blocks': []})
    document['closing']['date'] = None
    assert 'report_closing_details_required' in content_blockers(session, document)
    document['blocks'][0]['entries'][0]['question'] = '  '
    standalone = render(document, session)
    assert 'س/ج' in standalone and '<b>ج:</b>' not in standalone and '<b>س:</b>' not in standalone
    assert document['blocks'][0]['entries'][0]['answer'] in standalone


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
