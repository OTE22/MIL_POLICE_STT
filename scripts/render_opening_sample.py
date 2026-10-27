"""Synthetic first-page and long-document artifacts; never reads investigation data."""
import json
import sys
from pathlib import Path
sys.path.insert(0, "/app/tests")
sys.path.insert(0, "/app")
from test_report_opening import example
from app.services.report_document import render, pdf_from_html
from playwright.sync_api import sync_playwright

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
    if variant == "short":
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"])
            page = browser.new_page()
            page.set_content(html)
            page.evaluate("document.fonts.ready")
            page.emulate_media(media="print")
            geometry = page.evaluate("""() => {
              const rect = selector => { const r = document.querySelector(selector).getBoundingClientRect(); return {x:r.x, y:r.y, right:r.right, bottom:r.bottom}; };
              return {date:rect('.closing-dateline'), clerk:rect('.closing-clerk'), investigator:rect('.closing-investigator'),
                text:document.querySelector('.closing-date').textContent, direction:getComputedStyle(document.querySelector('.closing-date')).direction};
            }""")
            assert geometry['date']['right'] <= geometry['clerk']['x']
            assert geometry['date']['y'] == geometry['clerk']['y']
            assert geometry['investigator']['y'] >= geometry['date']['bottom']
            assert geometry['text'] == '27/10/2026' and geometry['direction'] == 'ltr'
            assert page.locator('.margin-marker').evaluate_all("els => els.every(el => getComputedStyle(el).textAlign === 'left')")
            (out / 'closing-date-layout.json').write_text(json.dumps(geometry, indent=2), encoding='utf-8')
            browser.close()
# The conclusion must not share its PDF page with earlier/later report content.
session, separate = example()
separate["blocks"][0]["entries"][0]["answer"] = "BEFORE_CONCLUSION — إفادة تجريبية قبل الخلاصة."
separate["blocks"].extend([
    {"id": "conclusion-layout", "type": "conclusion", "values": {"facts": "CONCLUSION_ONLY — الوقائع التجريبية.",
        "inference": "استنتاج تجريبي.", "closing_location": "مكتب تجريبي", "closing_date": "27/10/2026"},
     "responsibility_mode": "NONE", "proposal_mode": "NONE", "findings": []},
    {"id": "following-note", "type": "note", "values": {"note_text": "AFTER_CONCLUSION — ملاحظة لاحقة للخلاصة.",
        "closing_location": "مكتب تجريبي", "closing_date": "27/10/2026"}},
])
separate["closing"] = {**document["closing"], "text": "REPORT_END — نظم وختم هذا التحقيق، للتفضل بالاطلاع."}
separated_html = render(separate, session)
(out / "separation.html").write_text(separated_html, encoding="utf-8")
(out / "separation.pdf").write_bytes(pdf_from_html(separated_html))
print(json.dumps({"result": "PASS", "artifacts": str(out)}))
