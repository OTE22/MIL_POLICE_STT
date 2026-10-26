import { useEffect, useState } from "react";
import { http } from "@/api/client";
import { agentApi } from "@/api/agent";
import type { ProcessingToken } from "@/api/types";
import type { HtmlReportState } from "@/lib/html-report";
import { Recorder, type PendingAudio } from "@/components/recording/Recorder";
import { Alert, Field } from "@/components/ui";

export interface DictationTarget { block: string; field: string; label: string }
interface Dictation { id: string; block_id: string; field: string; status: string; machine_text: string; audio_ready: boolean;
  current_text: string | null; text_token: string | null; destination_changed: boolean; job_status: string; error: string | null }

export function ReportDictation({ sessionId, target, disabled, flush, onState, onClose, onBusy }: {
  sessionId: string; target: DictationTarget | null; disabled: boolean; flush: () => Promise<HtmlReportState>;
  onState: (state: HtmlReportState) => void; onClose: () => void; onBusy: (busy: boolean) => void;
}) {
  const path = `/investigations/${sessionId}/report/dictations`;
  const [pending, setPending] = useState<PendingAudio | null>(null);
  const [rows, setRows] = useState<Dictation[]>([]);
  const [texts, setTexts] = useState<Record<string, string>>({});
  const [modes, setModes] = useState<Record<string, "APPEND" | "REPLACE">>({});
  const [busy, setBusy] = useState(false);
  const [capturing, setCapturing] = useState(false);
  const [error, setError] = useState("");
  const [issued, setIssued] = useState<ProcessingToken | null>(null);
  useEffect(() => { if (target) document.querySelector(".report-dictation")?.scrollIntoView({ block: "start", behavior: "smooth" }); }, [target]);
  const refresh = () => http.get<Dictation[]>(path).then(setRows);
  useEffect(() => {
    void refresh().catch(() => setError("تعذر تحميل الإملاءات المحفوظة. أعد المحاولة."));
    const timer = window.setInterval(() => { void refresh().catch(() => undefined); }, 2500);
    return () => window.clearInterval(timer);
  }, [path]);
  const act = async (fn: () => Promise<void>) => {
    setBusy(true); onBusy(true); setError("");
    try { await fn(); await refresh(); }
    catch (err) { setError(`تعذر إتمام الإملاء. احتُفظ بالتسجيل والنص للمحاولة مجدداً. ${err instanceof Error ? err.message : ""}`); }
    finally { setBusy(false); onBusy(false); }
  };
  const submit = () => act(async () => {
    if (!pending || !target) return;
    const caps = await agentApi.capabilities();
    if (!(caps as typeof caps & { report_dictation?: boolean }).report_dictation) throw new Error("حدّث الوكيل المحلي لدعم الإملاء");
    const state = await flush();
    const token = issued ?? await http.post<ProcessingToken>(path, { expected_token: state.token, block_id: target.block, field: target.field,
      original_filename: pending.filename, mime_type: pending.mimeType, size_bytes: pending.blob.size, source: pending.source });
    setIssued(token);
    try { await agentApi.submitJob(token.processing_token, pending.blob, pending.filename); }
    catch (error) {
      // The upload can succeed while its response is lost. Reconcile the exact signed job.
      const existing = await agentApi.job(token.job_id).catch(() => null);
      if (!existing || existing.recording_id !== token.recording_id || existing.session_id !== sessionId || existing.purpose !== "REPORT_DICTATION") throw error;
    }
    setPending(null); setIssued(null); onClose();
  });
  const unresolved = rows.filter(r => !["ACCEPTED", "DISMISSED"].includes(r.status));
  if (!target && !unresolved.length && !error) return null;
  return <section className="card card-body report-dictation" aria-label="إملاء المحقق">
    <h3>إملاء المحقق {target ? `— ${target.label}` : "— نصوص تنتظر المراجعة"}</h3>
    <p>سجّل، ثم راجع النص قبل إدراجه. هذا الإملاء لا يدخل في إفادات الأشخاص أو قائمة المتحدثين.</p>
    {error && <Alert kind="danger">{error}<button className="btn" onClick={() => void refresh().then(() => setError("")).catch(() => undefined)}>إعادة المحاولة</button></Alert>}
    {target && <>
      <Recorder microphoneOnly disabled={disabled || busy} pending={pending} onCapturingChange={setCapturing} onReady={audio => { setPending(audio); if (!audio) setIssued(null); }} />
      <div className="flex gap wrap"><button className="btn btn-primary" disabled={!pending || busy || disabled} onClick={() => void submit()}>تحويل التسجيل إلى نص</button>
        <button className="btn" disabled={busy || capturing} onClick={() => { if (!pending || window.confirm("هل تريد ترك التسجيل غير المرسل؟")) { setPending(null); setIssued(null); onClose(); } }}>إغلاق التسجيل</button></div>
    </>}
    {unresolved.map(row => <div className="dictation-review" key={row.id}>
      <strong>{({ note_text: "ملاحظة", facts: "الوقائع", inference: "الاستنتاج", proposals: "الاقتراحات" } as Record<string, string>)[row.field] ?? "المسؤوليات"}</strong>
      {row.status === "READY" ? <>
        <details><summary>النص الآلي الأصلي</summary><p className="preserve-lines">{row.machine_text || "لم يُكتشف كلام واضح."}</p></details>
        <Field label="راجع النص وعدّله قبل الإدراج"><textarea className="textarea" rows={5} value={texts[row.id] ?? row.machine_text} onChange={e => setTexts(v => ({ ...v, [row.id]: e.target.value }))} /></Field>
        {row.destination_changed && <Alert kind="warning">تغيّر الحقل منذ بدء التسجيل. راجع نصه الحالي قبل الإدراج.</Alert>}
        <details open={row.destination_changed}><summary>النص الحالي في المحضر</summary><p className="preserve-lines">{row.current_text ?? "أزيل القسم الأصلي؛ النص المحوّل محفوظ هنا للنسخ أو الاستبعاد."}</p></details>
        <Field label="طريقة الإدراج"><select className="select" value={modes[row.id] ?? "APPEND"} onChange={e => setModes(v => ({ ...v, [row.id]: e.target.value as "APPEND" | "REPLACE" }))}>
          <option value="APPEND">إضافة إلى نهاية النص الحالي</option><option value="REPLACE">استبدال النص الحالي بعد المراجعة</option></select></Field>
        {!row.audio_ready && <p role="status">جارٍ حفظ التسجيل الأصلي؛ سيُتاح الإدراج عند اكتمال المزامنة.</p>}
        <button className="btn btn-primary" disabled={disabled || busy || !row.audio_ready || !row.text_token || !(texts[row.id] ?? row.machine_text).trim()}
          onClick={() => void act(async () => {
            const state = await flush();
            const next = await http.post<HtmlReportState>(`${path}/${row.id}/accept`, { expected_token: state.token,
              expected_text_token: row.text_token, text: texts[row.id] ?? row.machine_text, mode: modes[row.id] ?? "APPEND" });
            onState(next);
          })}>إدراج النص المراجع</button>
      </> : <p role="status">{row.job_status === "FAILED" ? "فشلت المعالجة. التسجيل محفوظ لدى الوكيل؛ راجع حالة النماذج أو أعد المزامنة." : "جارٍ معالجة الإملاء ومزامنته…"}</p>}
      <button className="btn" disabled={disabled || busy} onClick={() => {
        const reason = window.prompt("سبب استبعاد هذا الإملاء (يُحفظ في سجل التدقيق):");
        if (reason && reason.trim().length >= 3) void act(async () => { await http.post(`${path}/${row.id}/dismiss`, { reason }); });
      }}>استبعاد الإملاء مع حفظ السبب</button>
    </div>)}
  </section>;
}
