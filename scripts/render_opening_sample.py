"""Synthetic first-page and long-document artifacts; never reads investigation data."""
import json
import sys
from pathlib import Path
sys.path.insert(0, "/app/tests")
sys.path.insert(0, "/app")
from test_report_opening import example
from app.services.report_document import render, pdf_from_html

out = Path("/artifacts/report-opening")
out.mkdir(exist_ok=True)
session, document = example()
document["closing"] = {"text": "نظم وختم هذا التحقيق بصورته الحاضرة ووقع من قبلنا نحن والكاتب العدلي، للتفضل بالاطلاع.",
                       "location": "مكتب التحقيق التجريبي", "date": "2026-10-27"}
for variant in ("short", "long"):
    if variant == "long":
        entry = document["blocks"][0]["entries"][0]
        document["blocks"][0]["entries"] = [{**entry, "id": str(i), "answer": "نص تجريبي لاختبار امتداد الإفادة دون قص الكلمات أو التوقيع. " * 15} for i in range(25)]
    html = render(document, session)
    (out / f"{variant}.html").write_text(html, encoding="utf-8")
    (out / f"{variant}.pdf").write_bytes(pdf_from_html(html))
print(json.dumps({"result": "PASS", "artifacts": str(out)}))
