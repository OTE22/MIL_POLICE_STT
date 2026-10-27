"""Fixed first-page wording, transcribed from reference PDF pages 12 and 54.

Session date/time/location and assigned profiles remain canonical; only referral
facts and explicit confirmations belong to the editable opening.
"""
from html import escape

REVISION = "investigation-html-3"
OATH = "والله العظيم إني أقوم بواجبي بكل أمانة وإخلاص وأحفظ سر التحقيق"
FIELDS = {"referral_number": "رقم الإحالة", "referral_date": "تاريخ الإحالة", "referral_authority": "الجهة المحيلة"}


def blockers(session, document):
    opening = document.get("opening") or {}
    reasons = []
    if any(not str(opening.get(key) or "").strip() for key in FIELDS):
        reasons.append("report_opening_referral_required")
    if not all(getattr(session, key, None) for key in ("session_date", "start_time", "location")):
        reasons.append("report_opening_session_required")
    if not document.get("clerk_id") or document.get("clerk_id") == document.get("investigator_id"):
        reasons.append("report_opening_clerk_required")
    if not opening.get("oath_confirmed") or not opening.get("uniform_confirmed"):
        reasons.append("report_opening_confirmation_required")
    investigator = next((i.investigator for i in session.investigators if str(i.investigator_id) == str(document.get("investigator_id"))), None)
    clerk = next((i.investigator for i in session.investigators if str(i.investigator_id) == str(document.get("clerk_id"))), None)
    if not getattr(investigator, "unit", None) or not getattr(clerk, "military_id", None):
        reasons.append("report_opening_profiles_required")
    return reasons


def render(document, session, name):
    opening = document.get("opening") or {}
    def value(text, label):
        return escape(str(text)) if text else '<span class="missing">[' + label + ']</span>'
    date = getattr(session, "session_date", None)
    time = getattr(session, "start_time", None)
    days = ["الاثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد"]
    months = ["كانون الثاني", "شباط", "آذار", "نيسان", "أيار", "حزيران", "تموز", "آب", "أيلول", "تشرين الأول", "تشرين الثاني", "كانون الأول"]
    date_text = f"{days[date.weekday()]} الواقع في {date.day} من شهر {months[date.month - 1]} سنة {date.year}" if date else None
    time_text = time.strftime("%H:%M") if time else None
    investigator = next((i.investigator for i in session.investigators if str(i.investigator_id) == str(document.get("investigator_id"))), None)
    clerk = next((i.investigator for i in session.investigators if str(i.investigator_id) == str(document.get("clerk_id"))), None)
    unit = getattr(investigator, "unit", None)
    clerk_number = getattr(clerk, "military_id", None)
    oath = ('الذي اتخذناه كاتباً عدلياً بعد أن قمنا بتحليفه اليمين القانونية لمرة واحدة فقط على الشكل التالي: «' + OATH + '»') if opening.get("oath_confirmed") else '<span class="missing">[تأكيد تعيين الكاتب العدلي وتحليفه اليمين بعد حصولهما فعلياً]</span>'
    uniform = "والمرتدون اللباس العسكري" if opening.get("uniform_confirmed") else '<span class="missing">[تأكيد ارتداء اللباس العسكري]</span>'
    paragraphs = [
        'في الساعة ' + value(time_text, "ساعة الافتتاح") + ' من يوم ' + value(date_text, "تاريخ الجلسة"),
        'نحن ' + value(name(document.get("investigator_id")), "المحقق") + ' الضابط العدلي العسكري في ' + value(unit, "وحدة المحقق") + ' والمصحوبون بـ' + value(name(document.get("clerk_id")), "الكاتب العدلي") + ' رقم ' + value(clerk_number, "الرقم العسكري للكاتب") + '، ' + oath,
        uniform + ' نثبت أنه في الساعة والتاريخ المذكورين أعلاه اجتمعنا في ' + value(getattr(session, "location", None), "مكان الجلسة") + ' واستناداً للإحالة رقم ' + value(opening.get("referral_number"), FIELDS["referral_number"]) + ' تاريخ ' + value(opening.get("referral_date"), FIELDS["referral_date"]) + ' الصادرة عن ' + value(opening.get("referral_authority"), FIELDS["referral_authority"]) + ' والمتعلقة بإجراء تحقيق عدلي حول ' + value(document.get("subject"), "موضوع القضية") + '، باشرنا التحقيق على الشكل التالي:',
    ]
    return ('<tbody class="opening-body" data-block-id="opening"><tr class="opening-heading"><td class="official-heading">الجمهورية اللبنانية<br>وزارة الدفاع الوطني<br>الشرطة العسكرية</td><td><h1>محضر تحقيق عدلي</h1></td></tr>'
            '<tr><td class="margin-marker">مخفر</td><td class="statement-text opening-text">' + ''.join('<p>' + p + '</p>' for p in paragraphs) + '</td></tr></tbody>')
