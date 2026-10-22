import { useEffect, useState } from "react";
import { ApiError, downloadFile, http } from "@/api/client";
import type { M53Catalogue, OfficialReportForm, ReportDraft } from "@/api/types";
import { Alert, Field } from "@/components/ui";
import { errorMessage } from "@/lib/i18n";

export function M53ReportForm({ sessionId, form, editable, blocked, onSaved, onDirtyChange }: {
  sessionId: string; form: OfficialReportForm; editable: boolean; blocked: boolean;
  onSaved: (draft: ReportDraft) => Promise<void>;
  onDirtyChange: (id: string, dirty: boolean) => void;
}) {
  const [catalogue, setCatalogue] = useState<M53Catalogue | null>(null);
  const [values, setValues] = useState(form.values);
  const [enabled, setEnabled] = useState(form.enabled);
  const [flags, setFlags] = useState(form.confirmations);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const serverValues = JSON.stringify(form.values);
  const serverFlags = JSON.stringify(form.confirmations);
  useEffect(() => { setValues(JSON.parse(serverValues)); }, [serverValues]);
  useEffect(() => setEnabled(form.enabled), [form.enabled]);
  useEffect(() => { setFlags(JSON.parse(serverFlags)); }, [serverFlags, form.token]);
  useEffect(() => { void http.get<M53Catalogue>("/report-forms/m53").then(setCatalogue)
    .catch(err => setError(err instanceof ApiError ? errorMessage(err.code) : "تعذر تحميل النموذج")); }, []);
  const valuesDirty = enabled !== form.enabled || Object.keys(values).some(key => values[key] !== (form.values[key] ?? ""));
  const flagsDirty = [...new Set([...Object.keys(flags), ...Object.keys(form.confirmations)])].some(key => !!flags[key] !== !!form.confirmations[key]);
  const dirty = valuesDirty || flagsDirty;
  useEffect(() => { onDirtyChange("m53-form", dirty || busy); }, [dirty, busy, onDirtyChange]);
  useEffect(() => () => onDirtyChange("m53-form", false), [onDirtyChange]);
  useEffect(() => {
    const warn = (event: BeforeUnloadEvent) => { if (dirty) { event.preventDefault(); event.returnValue = ""; } };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);
  const fail = (err: unknown) => setError(err instanceof ApiError ? errorMessage(err.code) : "تعذر إتمام العملية");
  const save = async () => {
    setBusy(true); setError("");
    try {
      const updated = await http.put<ReportDraft>(`/investigations/${sessionId}/report/m53`, {
        expected_token: form.token, enabled, values,
        confirmations: valuesDirty ? [] : Object.keys(flags).filter(key => flags[key]),
      });
      await onSaved(updated);
    } catch (err) { fail(err); } finally { setBusy(false); }
  };
  const change = (key: string, value: string) => {
    setValues(previous => ({ ...previous, [key]: value }));
    setFlags(Object.fromEntries(Object.keys(flags).map(flag => [flag, false])));
  };
  const disabled = !editable || busy || blocked;
  const labels = Object.fromEntries((catalogue?.fields ?? []).map(field => [field.key, field]));
  return <section className="card" data-testid="m53-form" dir="rtl">
    <div className="card-head">صيغة المحضر</div>
    <div className="card-body">
      {error && <Alert kind="danger">{error}</Alert>}
      <Field label="النموذج المستخدم لهذه الجلسة">
        <select className="input" aria-label="النموذج المستخدم لهذه الجلسة" value={enabled ? "m53" : "word"} disabled={disabled}
          onChange={event => { setEnabled(event.target.value === "m53"); setFlags({}); }}>
          <option value="word">قالب Word الفعّال</option>
          <option value="m53">م ٥٣ — النموذج المسطّر بصياغة المصدر</option>
        </select>
      </Field>
      {enabled && <>
        <p className="muted">الصياغة الرسمية وترتيب الأقسام ثابتان. املأ البيانات المتغيرة، وراجع الأسئلة والأجوبة أسفل الصفحة. يتم حفظ PDF وWord عند إصدار المحضر، مع استمرار النص تلقائياً على صفحات إضافية.</p>
        <Alert kind="info">هذا النموذج مخصص لإفادة شخص واحد في المحضر. استخدم التسجيلات والكتل المناسبة، وتحقق من هوية صاحب كل جواب. بيانات الهوية والقرارات لا تُستنتج من التسجيل تلقائياً.</Alert>
        <div className="flex gap wrap mt-8 mb-16">
          <button className="btn" disabled={disabled || !catalogue} onClick={() => {
            setValues(previous => { const next = { ...previous }; for (const [key, value] of Object.entries(form.suggestions)) if (!next[key]) next[key] = value; return next; });
            setFlags({});
          }}>ملء الحقول الفارغة من بيانات الجلسة</button>
          <button className="btn" disabled={busy || dirty || blocked || !form.enabled} onClick={() => void downloadFile(
            `/investigations/${sessionId}/report/m53/preview`, "m53-preview.pdf").catch(fail)}>معاينة PDF المحفوظ</button>
        </div>
        {!catalogue && !error && <p>جارٍ تحميل حقول النموذج…</p>}
        {catalogue?.groups.map((group, i) => <details key={group.title} open={i < 2} className="mb-16">
          <summary style={{ cursor: "pointer", padding: "12px 0", fontWeight: 700 }}>{group.title}</summary>
          <div className="form-grid">
            {group.fields.map(key => <Field key={key} label={labels[key]?.label_ar ?? key} required={labels[key]?.required}
              full={key.startsWith("human_") || key === "procedural_decision"}>
              {key.startsWith("human_") || key === "procedural_decision" ? <textarea className="input" rows={4} aria-label={labels[key]?.label_ar ?? key}
                value={values[key] ?? ""} maxLength={20000} disabled={disabled} onChange={event => change(key, event.target.value)} />
                : <input className="input" aria-label={labels[key]?.label_ar ?? key} aria-required={labels[key]?.required} value={values[key] ?? ""} maxLength={2000} disabled={disabled}
                    onChange={event => change(key, event.target.value)} />}
            </Field>)}
          </div>
        </details>)}
        <details className="mb-16"><summary style={{ cursor: "pointer", padding: "12px 0", fontWeight: 700 }}>الصياغة الثابتة والحقول ضمنها</summary>
          {Object.entries(catalogue?.clauses ?? {}).map(([key, text]) => <p key={key} style={{ lineHeight: 2 }}>
            {text.split(/(\{[a-z_]+\})/g).map((part, index) => part.startsWith("{")
              ? <mark key={index}>{values[part.slice(1, -1)] || `[${labels[part.slice(1, -1)]?.label_ar ?? "يُحسب تلقائياً"}]`}</mark>
              : <span key={index}>{part}</span>)}
          </p>)}
        </details>
        {form.missing_fields.length > 0 && <p className="muted">حقول مطلوبة قبل الإصدار: {form.missing_fields.join("، ")}</p>}
        <details className="mb-16"><summary style={{ cursor: "pointer", padding: "12px 0", fontWeight: 700 }}>تأكيد الوقائع ومراجعة المحتوى</summary>
          <p className="muted">احفظ البيانات أولاً ثم أكّد الوقائع التي حصلت فعلياً. تُحذف العبارات الإجرائية غير المؤكدة من المخرجات. أي تعديل لاحق للبيانات أو نص الإفادة يستلزم مراجعة جديدة. هذه التأكيدات ليست توقيعاً رقمياً.</p>
          {Object.entries(catalogue?.confirmations ?? {}).map(([key, label]) => <label key={key} className="checkbox" style={{ display: "block", marginBottom: 10 }}>
            <input type="checkbox" checked={!!flags[key]} disabled={disabled || valuesDirty} onChange={event => setFlags(previous => ({ ...previous, [key]: event.target.checked }))} /> {label}
          </label>)}
        </details>
      </>}
      {editable && <button className="btn btn-primary" disabled={disabled || !dirty || !catalogue} onClick={() => void save()}>
        {busy ? "جارٍ الحفظ…" : valuesDirty ? "حفظ بيانات النموذج" : "حفظ تأكيدات المراجعة"}
      </button>}
      {valuesDirty && <span className="muted small" style={{ marginInlineStart: 12 }}>تغييرات غير محفوظة — تُراجع بعد الحفظ</span>}
    </div>
  </section>;
}
