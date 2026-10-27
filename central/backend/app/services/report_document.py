"""Canonical, escaped HTML renderer. Preview, HTML download and PDF share these bytes."""
import base64
import re
from html import escape
from pathlib import Path
from app.services.report_html import CATALOGUE

ASSETS = Path(__file__).resolve().parents[1] / "assets" / "report_print"


def prose(value):
    """Reflow soft line breaks for print; retain deliberate blank-line paragraphs.

    This changes presentation only, never the stored transcription or report text.
    Escape each paragraph before inserting the renderer-owned line breaks.
    """
    paragraphs = re.split(r"\n\s*\n", value.replace("\r\n", "\n").replace("\r", "\n"))
    return "<br><br>".join(escape(re.sub(r"\s+", " ", paragraph).strip()) for paragraph in paragraphs)


def render(document, session, *, issued=False, version=None, number=None, highlight=False):
    def editable_text(value, key, label):
        # Only allowlisted narrative fields are exposed to the document editor.
        attrs = (f' data-edit-key="{escape(key, quote=True)}" data-edit-value="{escape(value, quote=True)}"'
                 f' aria-label="{escape(label, quote=True)}"') if highlight and not issued else ""
        return f'<span{attrs} class="report-prose">{prose(value) or ("" if issued else "[" + escape(label) + "]")}</span>'
    def name(identifier):
        link = next((i for i in session.investigators if str(i.investigator_id) == str(identifier)), None)
        return " ".join(v for v in [link.investigator.rank, link.investigator.full_name] if v) if link else ""
    def row(content, marker="", classes="", target=""):
        return f'<tr class="{classes}" data-field="{escape(target, quote=True)}"><td class="margin-marker">{marker}</td><td class="statement-text">{content}</td></tr>'
    sections = []
    from app.services import report_opening
    official = document.get("revision") == report_opening.REVISION
    table_start = '<table class="statement-table"><colgroup><col class="marker-col"><col></colgroup>'
    if official:
        sections.append('<section class="statement-block narrative-block">' + table_start + report_opening.render(document, session, name))
    narrative_open = official
    for block in document["blocks"]:
        template = CATALOGUE["note"] if block["type"] == "note" else CATALOGUE
        labels = {f["key"]: f["label"] for f in template["fields"]}
        labels.update(facts="الوقائع", inference="الاستنتاج", proposals="الاقتراحات")
        values = {**block["values"]}
        values["investigator_name"] = values.get("investigator_name") or name(document.get("investigator_id"))
        values["clerk_name"] = values.get("clerk_name") or name(document.get("clerk_id"))
        def field(key):
            value = values.get(key, "").strip()
            if issued and not value:
                return ""
            narrative = key in {"note_text", "facts", "inference", "proposals"}
            if narrative:
                content = prose(value) if block["type"] == "note" and block.get("template_id") else editable_text(values.get(key, ""), "value:" + key, labels.get(key, key))
            else:
                content = escape(value or "[" + labels.get(key, key) + "]")
            return f'<span data-field="{escape(key, quote=True)}" class="variable{ "" if value else " missing" }">{content}</span>'
        def clause(key):
            return re.sub(r"\{([a-z_]+)\}", lambda m: field(m[1]), escape(template["clauses"].get(key, "")))
        if block["type"] == "conclusion":
            content = row(field("facts"), "١ ـ الوقائع:", "conclusion-body", "facts")
            content += row(field("inference"), "٢ ـ الاستنتاج:", "conclusion-body", "inference")
            findings = []
            for finding in block["findings"]:
                person = next((p for p in session.subjects if str(p.participant_key) == str(finding.get("participant_key"))), None)
                subject_name = finding.get("subject_snapshot") or (person.subject_name if person else finding["unidentified_subject"])
                findings.append('<p data-field="finding:' + escape(str(finding["id"]), quote=True) + '"><b>' + escape(subject_name or "[الشخص المعني]") + '</b>: ' + editable_text(finding["text"], "finding:" + str(finding["id"]), "نتيجة المسؤولية") + '</p>')
            responsibility_text = "لا يوجد" if block["responsibility_mode"] == "NONE" else "".join(findings) or "[المسؤوليات قيد الاستكمال]"
            content += row(responsibility_text, "٣ ـ المسؤوليات:", "conclusion-body", "responsibilities")
            content += row("لا يوجد" if block["proposal_mode"] == "NONE" else field("proposals"), "٤ ـ الاقتراحات:", "conclusion-body", "proposals")
        elif block["type"] == "note":
            prefix = ("بتاريخ " + field("note_date")) if values.get("note_date") else ""
            if values.get("note_time"):
                prefix += " الساعة " + field("note_time")
            content = row((prefix + "، " if prefix else "") + field("note_text"), "ملاحظة:", "note-body")
        else:
            heading = clause("heading") if values.get("statement_rank") or values.get("statement_service_number") else "إفادة " + field("statement_name")
            content = row(heading, classes="statement-heading") + row(clause("identity"))
            if block["identity_checked"]:
                content += row(clause("identity_check"))
            for entry in block["entries"]:
                q = editable_text(entry["question"], "question:" + str(entry["id"]), "السؤال")
                a = editable_text(entry["answer"], "answer:" + str(entry["id"]), "نص الإفادة / الجواب")
                content += row((f'<p><b>س:</b> {q}</p>' if entry["question"] else "") + f'<p>{a}</p>', "", "qa-row", "answer-" + str(entry["id"]))
            if block["attestation_confirmed"]:
                content += row(clause("attestation"))
        signature = ('<div>' + field("statement_signature_role") + '<div class="signature-space"></div></div>') if block["type"] == "statement" else ""
        if block["type"] != "conclusion":
            signature += '<div>كاتب عدلي<br>' + field("clerk_name") + '<div class="signature-space"></div></div>'
        signature += '<div>' + clause("place_date") + '<div>المحقق: ' + field("investigator_name") + '</div><div class="signature-space"></div></div>'
        content += row(f'<div class="signature-row{ " note-signature-row" if block["type"] == "note" else "" }">{signature}</div>', classes="statement-signatures")
        selectable = ' tabindex="0" role="button" aria-label="تعديل القسم"' if highlight else ""
        if official:
            if block["type"] == "conclusion" or not narrative_open:
                if narrative_open:
                    sections.append('</table></section>')
                sections.append('<section class="statement-block ' + ('conclusion-block' if block["type"] == "conclusion" else 'narrative-block') + '">' + table_start + '<thead><tr><th>هامش</th><th>' + ('خلاصة تحقيق عدلي' if block["type"] == "conclusion" else 'محضر تحقيق عدلي') + '</th></tr></thead>')
                narrative_open = True
            sections.append('<tbody' + selectable + ' data-block-id="' + escape(str(block['id']), quote=True) + '">' + content + '</tbody>')
            if block["type"] == "conclusion":
                sections.append('</table></section>')
                narrative_open = False
        else:
            sections.append('<section' + selectable + ' data-block-id="' + escape(str(block['id']), quote=True) + '" class="statement-block ' + block["type"] + '-block">' + table_start + '<thead><tr><th>هامش</th><th>' + ("خلاصة تحقيق عدلي" if block["type"] == "conclusion" else "محضر تحقيق عدلي") + '</th></tr></thead><tbody>' + content + '</tbody></table></section>')
    closing = document.get("closing")
    if closing:
        if not narrative_open:
            sections.append('<section class="statement-block narrative-block">' + table_start)
            narrative_open = True
        signatures = ('<div class="signature-row note-signature-row"><div>كاتب عدلي<br>' + escape(name(document.get("clerk_id"))) +
                      '<div class="signature-space"></div></div><div>المحقق<br>' + escape(name(document.get("investigator_id"))) +
                      '<div class="signature-space"></div></div></div>')
        content = row(editable_text(closing.get("text", ""), "closing:text", "ختام المحضر"), classes="note-body")
        content += row('<div>' + escape(closing.get("location") or "") + ' — ' + escape(str(closing.get("date") or "")) + '</div>' + signatures, classes="statement-signatures")
        sections.append('<tbody class="report-closing" data-block-id="closing">' + content + '</tbody>')
    if narrative_open:
        sections.append('</table></section>')
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
            + (f'<p>رقم المحضر: {escape(session.session_number)}</p></header>' if official else f'<h1>محضر تحقيق عدلي</h1><p>موضوع القضية: {title}</p><p>رقم المحضر: {escape(session.session_number)}</p><p>المحقق: {escape(name(document.get("investigator_id")))}</p></header>')
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
            return page.pdf(format="A4", print_background=True, prefer_css_page_size=True,
                            display_header_footer=True, header_template="<span></span>",
                            footer_template='<div style="font-size:10px;width:100%;text-align:center;color:#222"><span class="pageNumber"></span> / <span class="totalPages"></span></div>')
        finally:
            browser.close()
