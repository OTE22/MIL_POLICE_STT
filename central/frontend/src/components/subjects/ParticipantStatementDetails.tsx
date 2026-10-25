import { useEffect, useState } from "react";
import { ApiError, http } from "@/api/client";
import { Alert, Field, Loading } from "@/components/ui";
import { useAuth } from "@/lib/auth";

interface DetailsState {
  token: string; session_id: string; participant_key: string; values: Record<string, string>;
  fields: { key: string; label: string; multiline?: boolean }[];
}

export function ParticipantStatementDetails({ sessionId, participantKey }: { sessionId: string; participantKey: string }) {
  const { can } = useAuth();
  const [state, setState] = useState<DetailsState | null>(null);
  const [values, setValues] = useState<Record<string, string>>({});
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState(false);
  const path = `/investigations/${sessionId}/participants/${participantKey}/statement-details`;
  const dirty = !!state && JSON.stringify(values) !== JSON.stringify(state.values);
  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    void http.get<DetailsState>(path).then(result => { if (!cancelled) { setState(result); setValues(result.values); } })
      .catch(() => { if (!cancelled) setError("تعذر تحميل بيانات صاحب الإفادة."); });
    return () => { cancelled = true; };
  }, [path, open]);
  useEffect(() => {
    const warn = (e: BeforeUnloadEvent) => { if (dirty) { e.preventDefault(); e.returnValue = ""; } };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);
  async function save() {
    if (!state) return;
    setBusy(true); setError(""); setNotice("");
    try {
      const result = await http.put<DetailsState>(path, { expected_token: state.token, values });
      setState(result); setValues(result.values); setNotice("حُفظت البيانات لهذه الجلسة. تُعبّأ تلقائياً عند اختيار الشخص في إفادة جديدة.");
    } catch (err) {
      setError(err instanceof ApiError && err.status === 409 ? "تغيّرت البيانات في نافذة أخرى. احتفظ بتعديلاتك وأعد فتح القسم للمراجعة." : "تعذر حفظ بيانات صاحب الإفادة.");
    } finally { setBusy(false); }
  }
  return <div className="html-field-group mt-16">
    <button className="btn" type="button" aria-expanded={open} onClick={() => {
      if (open && dirty && !window.confirm("هناك بيانات غير محفوظة. هل تريد إغلاق القسم وإلغاء تعديلاتك؟")) return;
      setOpen(!open); setError(""); setNotice(""); if (open) setState(null);
    }}>بيانات صاحب الإفادة في هذه الجلسة {open ? "−" : "+"}</button>
    {open && <>
      <p className="small muted">الشخص نفسه يمكن أن يشارك في جلسات مختلفة؛ بيانات إفادته وأجوبته وملاحظات كل جلسة تبقى مستقلة. احفظ التعديلات قبل مغادرة هذا التبويب.</p>
      {error && <Alert kind="danger">{error}</Alert>}{notice && <Alert kind="info">{notice}</Alert>}
      {!state ? <Loading /> : <><div className="form-grid">{state.fields.map(field => <Field key={field.key} label={field.label} full={field.multiline}>
        <textarea className="textarea" rows={field.multiline ? 3 : 1} maxLength={2000} disabled={busy || !can("investigations.update")}
          value={values[field.key] || ""} onChange={e => { setValues(v => ({ ...v, [field.key]: e.target.value })); setNotice(""); }} />
      </Field>)}</div><button className="btn btn-primary mt-8" disabled={busy || !dirty || !can("investigations.update")} onClick={() => void save()}>حفظ بيانات صاحب الإفادة</button></>}
    </>}
  </div>;
}
