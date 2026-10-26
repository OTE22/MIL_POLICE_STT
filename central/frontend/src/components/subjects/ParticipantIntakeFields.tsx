import { useEffect, useId, useState } from "react";
import { http } from "@/api/client";
import type { Subject } from "@/api/types";
import { Alert, Field } from "@/components/ui";

interface Requirement { key: string; label: string; owner: string; applies: string; exceptions: string[] }
let catalogue: Promise<{ fields: Requirement[] }> | null = null;
const labels: Record<string, string> = { UNKNOWN: "غير معلوم", REFUSED: "امتنع عن التصريح", NOT_APPLICABLE: "لا ينطبق" };

export function ParticipantIntakeFields({ subject, onChange }: { subject: Subject; onChange: (value: Subject) => void }) {
  const newPersonId = useId();
  const [fields, setFields] = useState<Requirement[]>([]);
  const [error, setError] = useState(false);
  useEffect(() => {
    catalogue ??= http.get<{ fields: Requirement[] }>("/investigations/participant-requirements");
    void catalogue.then(value => setFields(value.fields)).catch(() => { catalogue = null; setError(true); });
  }, []);
  const applicable = (f: Requirement) => f.applies === "all" || f.applies === "military" && subject.person_type === "MILITARY"
    || f.applies === "civilian" && subject.person_type === "CIVILIAN" || f.applies === "lebanese" && subject.person_type === "CIVILIAN" && subject.nationality_code === "LB" && !subject.is_unregistered;
  const value = (f: Requirement): string => {
    if (f.key === "person_type" && subject.person_type === "UNKNOWN") return "";
    if (f.key === "documents") return subject.documents.length || subject.is_undocumented && subject.undocumented_reason ? "available" : "";
    if (f.key === "occupation_statement") return subject.statement_details?.[f.key] || [subject.rank, subject.unit, subject.department].filter(Boolean).join(" — ");
    if (f.key === "nationality_code") return subject.nationality_code || subject.nationality_name || "";
    return String(f.owner === "statement_details" ? subject.statement_details?.[f.key] ?? "" : subject[f.key as keyof Subject] ?? "");
  };
  const setValue = (key: string, text: string) => {
    const exceptions = { ...subject.field_exceptions }; delete exceptions[key];
    onChange({ ...subject, statement_details: { ...subject.statement_details, [key]: text }, field_exceptions: exceptions });
  };
  const setException = (key: string, status: string, reason?: string) => {
    const exceptions = { ...subject.field_exceptions };
    if (status) exceptions[key] = { status, reason: reason ?? exceptions[key]?.reason ?? "" };
    else delete exceptions[key];
    onChange({ ...subject, field_exceptions: exceptions });
  };
  const visible = fields.filter(applicable).filter(f => f.owner === "statement_details" || !value(f).trim() || subject.field_exceptions?.[f.key]);
  return <section className="intake-fields mt-16" aria-label="بيانات الإفادة المطلوبة">
    <h3>بيانات الإفادة — تُستخدم تلقائياً في المحضر</h3>
    <p className="muted">يمكن حفظ مسودة. قبل بدء الجلسة، أكمل البيانات أو سجّل سبب عدم توفرها.</p>
    {error && <Alert kind="danger">تعذر تحميل متطلبات البيانات. أعد تحميل الصفحة.</Alert>}
    <div className="form-grid">{visible.map(f => {
      const exception = subject.field_exceptions?.[f.key];
      return <div className="field" id={`participant-${subject.participant_key ?? newPersonId}-${f.key}`} key={f.key} tabIndex={-1}>
        {f.owner === "statement_details" ? <Field label={f.label} required>
          <textarea className="textarea" rows={f.key === "occupation_statement" || f.key === "prior_record_statement" ? 2 : 1}
            value={value(f)} disabled={!!exception} maxLength={2000} onChange={e => setValue(f.key, e.target.value)} />
        </Field> : <strong>{f.label} — أكمل الحقل أعلاه أو بيّن سبب عدم توفره</strong>}
        {f.exceptions.length > 0 && (!value(f).trim() || exception) && <>
          <select className="select mt-8" aria-label={`حالة ${f.label}`} value={exception?.status ?? ""} onChange={e => setException(f.key, e.target.value)}>
            <option value="">سأدخل المعلومة</option>{f.exceptions.map(code => <option key={code} value={code}>{labels[code]}</option>)}
          </select>
          {exception && <Field label={`سبب عدم توفر ${f.label}`} required><textarea className="textarea" rows={2} minLength={3} maxLength={2000}
            value={exception.reason} onChange={e => setException(f.key, exception.status, e.target.value)} /></Field>}
        </>}
      </div>;
    })}</div>
  </section>;
}
