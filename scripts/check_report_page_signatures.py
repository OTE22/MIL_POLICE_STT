"""Synthetic pagination proof. Render in test container; inspect PDFs on host."""
import json
import re
import sys
from copy import deepcopy
from pathlib import Path

if sys.argv[1] == "render":
    sys.path[:0] = ["/app", "/app/tests"]
    from test_report_opening import example
    from app.services.report_document import render, pdf_from_html

    out = Path("/artifacts/page-signatures")
    out.mkdir(parents=True, exist_ok=True)
    session, original = example()
    session.investigators[0].investigator.full_name = "LEAD_SIGNATURE"
    session.investigators[1].investigator.full_name = "CLERK_SIGNATURE"
    session.subjects = []
    original["blocks"][0]["values"].update(statement_signature_role="SUBJECT_SIGNATURE", closing_date="2026-10-27", closing_location="مكتب الاختبار")
    cases = {}
    cases["short"] = deepcopy(original)
    long = deepcopy(original)
    long["blocks"][0]["entries"] = [{"id": str(i), "question": "سؤال تجريبي", "answer": f"ITEM{i:03d} " + "نص تجريبي للتأكد من بقاء مساحة التوقيع دون تداخل مع الإفادة. " * 9} for i in range(28)]
    cases["statement"] = long
    note = {"id": "long-note", "type": "note", "values": {"note_text": " ".join(f"ITEM{i:03d} " + "ملاحظة تجريبية للتحقق من استمرار النص مع مساحة توقيع الصفحة. " * 5 for i in range(24))}}
    cases["note"] = {**deepcopy(original), "blocks": [note]}
    conclusion = {"id": "long-conclusion", "type": "conclusion", "responsibility_mode": "NONE", "proposal_mode": "NONE", "findings": [], "values": {
        "facts": " ".join(f"ITEM{i:03d} " + "وقائع تجريبية للتحقق من صفحات الخلاصة وتواقيعها. " * 5 for i in range(24)), "inference": "استنتاج تجريبي"}}
    cases["conclusion"] = {**deepcopy(original), "blocks": [conclusion]}
    mixed = deepcopy(original)
    mixed["blocks"] += [deepcopy(note), deepcopy(conclusion), {"id": "last-note", "type": "note", "values": {"note_text": "ملاحظة لاحقة للخلاصة"}}]
    mixed["closing"] = {"text": "نظم وختم هذا التحقيق، للتفضل بالاطلاع.", "location": "مكتب الاختبار", "date": "2026-10-27"}
    cases["mixed"] = mixed
    cases["opening-only"] = {**deepcopy(original), "blocks": []}
    people = deepcopy(original)
    people["blocks"] = []
    for person in ("A", "B"):
        statement = deepcopy(original["blocks"][0])
        statement["id"] = "person-" + person
        statement["values"].update(statement_name="PERSON_" + person, statement_signature_role="SUBJECT_" + person)
        statement["entries"] = [{"id": person, "question": "سؤال تجريبي", "answer": ("PERSON_" + person + "_BODY نص تجريبي للتحقق من بقاء التوقيع مرتبطاً بصاحب الإفادة الصحيح. ") * 90}]
        people["blocks"].append(statement)
    cases["two-people"] = people
    for name, document in cases.items():
        if len(sys.argv) > 2 and name != sys.argv[2]:
            continue
        html = render(document, session)
        # Distinguish the name in the opening narrative from signature labels.
        html = re.sub(r'<tbody class="opening-body".*?</tbody>', lambda m: m[0].replace('LEAD_SIGNATURE', 'OPENING_LEAD').replace('CLERK_SIGNATURE', 'OPENING_CLERK'), html, flags=re.S)
        (out / (name + ".html")).write_text(html, encoding="utf-8")
        (out / (name + ".pdf")).write_bytes(pdf_from_html(html))
        print("rendered", name, flush=True)
else:
    import pymupdf
    out = Path(__file__).resolve().parents[1] / "storage/test-artifacts/page-signatures"
    proof = {}
    for path in sorted(out.glob("*.pdf")):
        document = pymupdf.open(path)
        all_text = ""
        pages = []
        for index, page in enumerate(document):
            text = page.get_text()
            all_text += text
            signatures = page.search_for("LEAD_SIGNATURE")
            assert signatures, (path.name, index + 1, "missing page signature")
            if path.stem == 'two-people':
                for person in ('A', 'B'):
                    if f'PERSON_{person}_BODY' in text:
                        assert f'SUBJECT_{person}' in text, (index + 1, 'wrong person signing area')
            if path.stem in ("short", "statement", "note", "opening-only"):
                assert len(signatures) == 1, (path.name, index + 1, "duplicate signature")
            last = max(rect.y1 for rect in signatures)
            tokens = [word for word in page.get_text("words") if word[4].startswith("ITEM")]
            assert all(word[3] < last for word in tokens), (path.name, index + 1, "content below signature")
            assert last + 40 < page.rect.height - 25, (path.name, index + 1, "insufficient blank signing space")
            pages.append({"page": index + 1, "signature_groups": len(signatures), "last_signature_label_y": round(last, 2)})
            if index in (0, len(document) - 1):
                page.get_pixmap(matrix=pymupdf.Matrix(1.25, 1.25)).save(out / f"{path.stem}-{index + 1}.png")
        count = 28 if path.stem == "statement" else 24 if path.stem in ("note", "conclusion") else 0
        for index in range(count):
            assert all_text.count(f"ITEM{index:03d}") == 1, (path.name, index, "missing or duplicated prose")
        proof[path.stem] = {"pages": len(document), "checks": pages}
    assert len(proof) == 7
    (out / "verification.json").write_text(json.dumps({"result": "PASS", "documents": proof}, indent=2), encoding="utf-8")
    print(json.dumps({"result": "PASS", "pages": {name: value["pages"] for name, value in proof.items()}}))
