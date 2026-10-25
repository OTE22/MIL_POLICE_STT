"""Canonical, escaped HTML renderer. Preview, HTML download and PDF share these bytes."""
import base64
import re
from html import escape
from pathlib import Path
from app.services.report_html import CATALOGUE

ASSETS = Path(__file__).resolve().parents[1] / "assets" / "report_print"


def render(document, session, *, issued=False, version=None, number=None, highlight=False):
    def name(identifier):
        link = next((i for i in session.investigators if str(i.investigator_id) == str(identifier)), None)
        return " ".join(v for v in [link.investigator.rank, link.investigator.full_name] if v) if link else ""
    def row(content, marker="", classes=""):
        return f'<tr class="{classes}"><td class="margin-marker">{marker}</td><td class="statement-text">{content}</td></tr>'
    sections = []
    for block in document["blocks"]:
        template = CATALOGUE["note"] if block["type"] == "note" else CATALOGUE
        labels = {f["key"]: f["label"] for f in template["fields"]}
        values = {**block["values"]}
        values["investigator_name"] = values.get("investigator_name") or name(document.get("investigator_id"))
        values["clerk_name"] = values.get("clerk_name") or name(document.get("clerk_id"))
        def field(key):
            value = values.get(key, "").strip()
            return f'<span class="variable{ "" if value else " missing" }">{escape(value or "[" + labels.get(key, key) + "]")}</span>'
        def clause(key):
            return re.sub(r"\{([a-z_]+)\}", lambda m: field(m[1]), escape(template["clauses"].get(key, "")))
        if block["type"] == "note":
            content = row(clause("body"), "ملاحظة:", "note-body")
        else:
            content = row(clause("heading"), classes="statement-heading") + row(clause("identity"), "س.ج")
            if block["identity_checked"]:
                content += row(clause("identity_check"))
            for entry in block["entries"]:
                q, a = escape(entry["question"]), escape(entry["answer"])
                content += row((f'<p><b>س:</b> {q}</p>' if q else "") + f'<p><b>ج:</b> {a}</p>', "س.ج")
            if block["attestation_confirmed"]:
                content += row(clause("attestation"))
        signature = ('<div>' + field("statement_signature_role") + '<div class="signature-space"></div></div>') if block["type"] == "statement" else ""
        signature += '<div>كاتب عدلي<br>' + field("clerk_name") + '<div class="signature-space"></div></div>'
        signature += '<div>' + clause("place_date") + '<div>المحقق: ' + field("investigator_name") + '</div><div class="signature-space"></div></div>'
        content += row(f'<div class="signature-row{ " note-signature-row" if block["type"] == "note" else "" }">{signature}</div>', classes="statement-signatures")
        sections.append('<section data-block-id="' + escape(str(block['id']), quote=True) + '" class="statement-block"><table class="statement-table"><colgroup><col class="marker-col"><col></colgroup><tbody>' + content + '</tbody></table></section>')
    fonts = ""
    licenses = ""
    for family, filename in [("IBM Plex Sans Arabic", "IBMPlexSansArabic-Regular.woff2"), ("Inter", "InterVariable.woff2")]:
        data = base64.b64encode((ASSETS / filename).read_bytes()).decode()
        fonts += f"@font-face{{font-family:'{family}';src:url(data:font/woff2;base64,{data})}}"
    for path in ASSETS.glob("*-LICENSE.txt"):
        licenses += path.read_text(encoding="utf-8").replace("-->", "")
    label = f"محضر صادر — {number or session.session_number} — الإصدار {version}" if issued else "مسودة محضر"
    title = escape(document["subject"] or session.title)
    css = (ASSETS / "report.css").read_text(encoding="utf-8")
    return ('<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            '<meta http-equiv="Content-Security-Policy" content="default-src \'none\';style-src \'unsafe-inline\';font-src data:;img-src data:;base-uri \'none\';form-action \'none\'">'
            f'<title>{escape(label)} — {title}</title><!--{licenses}--><style>{fonts}{css}</style></head>'
            f'<body class="{ "highlight-fields" if highlight else "" }"><main class="report-paper"><header class="report-meta"><div>{escape(label)}</div>'
            f'<h1>{title}</h1><p>الجلسة: {escape(session.session_number)}</p><p>المحقق: {escape(name(document.get("investigator_id")))}</p></header>'
            + "".join(sections) + '</main></body></html>')


def pdf_from_html(html):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, args=["--disable-dev-shm-usage", "--no-sandbox"])
        try:
            page = browser.new_page()
            page.route("**/*", lambda route: route.abort())
            page.set_content(html, wait_until="load", timeout=30000)
            page.evaluate("document.fonts.ready")
            return page.pdf(format="A4", print_background=True, prefer_css_page_size=True)
        finally:
            browser.close()
