from pathlib import Path
import re
ROOT = Path(__file__).resolve().parents[1]
def edit(path, fn):
    p = ROOT / path
    p.write_text(fn(p.read_text(encoding='utf-8')), encoding='utf-8')

edit('central/backend/app/core/permissions.py', lambda s: re.sub(r'    # الرقم المرجعي.*?    "subjects.reference.override":.*?\n', '', s, flags=re.S))
edit('central/backend/app/api/reports.py', lambda s: s.replace('            reference=info.reference,\n', ''))
edit('central/backend/app/schemas/reports.py', lambda s: s.replace('    reference: str | None\n', ''))
edit('central/backend/app/services/report_renderer.py', lambda s: re.sub(r'^.*"(?:investigator_reference|subject_reference|question_speaker_reference|answer_speaker_reference)".*\n', '', re.sub(r', "reference": "[^"]*"', '', s), flags=re.M))
edit('central/backend/app/services/report_dev_template.py', lambda s: s.replace(' — {{ investigator_reference }}', '').replace(' — {{ subject_reference }}', ''))

def translations(s):
    remove = ['referenceNumber','referenceDerived','referencePending','referenceOverride','referenceAssign','referenceUnavailable','referenceOverrideNote','referenceManual','referenceComputedNote','identityChangeCurrent','identityChangeNew','voicePersonReference','voicePersonReferenceHint','identifyNeedsReference']
    for key in remove:
        s = re.sub(r'^  '+key+r':\s*"[^"\n]*",\n', '', s, flags=re.M)
    replace = {
      'cazaHint': 'القضاء ومحل القيد معلومات وصفية عن السجل العائلي.',
      'pickSearchPlaceholder': 'اسم الشخص',
      'pickPersonIncomplete': 'لم يُربط هذا المشارك بسجل شخص بعد. احفظ بيانات الجلسة أولاً.',
      'voiceDuplicateNames': 'يوجد أكثر من شخص بهذا الاسم',
      'voiceConsolidateHint': 'اختر الشخص الصحيح؛ ستُنقل كل البصمات إليه.',
      'identifySearchPlaceholder': 'ابحث باسم الشخص…',
      'err_person_identity_name_mismatch': 'الرقم العسكري مسجّل لشخص باسم مختلف. تحقق من بيانات الشخص.',
    }
    s = s.replace('err_person_reference_name_mismatch:', 'err_person_identity_name_mismatch:')
    for key, text in replace.items():
        s = re.sub(r'(^  '+key+r':\s*)"[^"\n]*"', lambda m: m[1]+'"'+text+'"', s, flags=re.M)
    s = s.replace('وصفي فقط — لا يدخل في احتساب الرقم المرجعي ولا يميّز شخصاً عن آخر.', 'وصفي فقط — يخص السجل العائلي ولا يميّز شخصاً عن آخر.')
    s = s.replace('لا تُنشئ شخصاً ولا رقماً مرجعياً', 'لا تُنشئ سجل شخص')
    s = s.replace('  err_person_identity_name_mismatch:', '  err_participant_identity_required: "أعد تحميل الجلسة قبل الحفظ للحفاظ على هوية المشاركين.",\n  err_participant_identity_change_not_permitted: "لا يمكن استبدال هوية مشارك موجود. أضف الشخص الصحيح كمشارك جديد.",\n  err_person_not_in_session: "أضف الشخص إلى المشاركين في الجلسة قبل ربطه بالمتحدث.",\n  err_identity_not_found: "لم يُعثر على الشخص المحدد. أعد تحميل القائمة.",\n  err_person_identity_name_mismatch:')
    return s
edit('central/frontend/src/lib/i18n.ts', translations)

# This formatter and the preview module existed solely for the removed field.
edit('central/frontend/src/lib/format.ts', lambda s: re.sub(r'/\*\*[^/]*The reference is wrapped.*?\n\}', '', s, flags=re.S))

# Deployed checks still validate profile completeness, but no longer claim it generates a key.
for path in ['deploy/deploy-central.sh', 'deploy/README.md']:
    edit(path, lambda s: s.replace('produce a user\'s الرقم المرجعي', 'record a user\'s service details').replace('these accounts have no الرقم المرجعي and cannot be identified as speakers:', 'these accounts have incomplete service details:').replace("produce the account's الرقم المرجعي (MIL-<الجهاز>-<الرقم>)", "record the account's service details"))
