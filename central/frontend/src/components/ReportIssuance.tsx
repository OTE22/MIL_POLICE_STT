import { useEffect, useState } from "react";
import { http, downloadFile } from "@/api/client";
import { useAuth } from "@/lib/auth";
import type { HtmlReportState } from "@/lib/html-report";
import { Alert, Field } from "@/components/ui";

const reasons: Record<string, string> = {
  report_is_final: "المحضر صادر ومحفوظ. التصحيح يتطلب إعادة فتح المسودة.",
  report_subject_required: "أدخل موضوع المحضر", report_investigator_required: "اختر المحقق المسؤول",
  report_no_content: "أضف إفادة أو ملاحظة", report_closing_details_required: "أكمل تاريخ ومكان تنظيم كل إفادة أو ملاحظة",
  report_note_empty: "أكمل نص الملاحظة", report_statement_name_required: "أكمل اسم صاحب الإفادة",
  report_answer_required: "أكمل نصوص الأجوبة", report_identity_documents_required: "حدد الوثائق التي تم التحقق منها",
  report_clerk_required: "اختر الكاتب العدلي قبل تأكيد التلاوة والتوقيع", report_review_required: "راجع المحتوى واحفظ تأكيد المراجعة",
  active_processing_jobs: "انتظر انتهاء جميع مهام المعالجة", original_audio_missing: "لم يكتمل حفظ التسجيلات الأصلية",
  unresolved_processing_failures: "توجد معالجة فاشلة لم تُستكمل بنجاح. أعد محاولة معالجة التسجيل قبل المراجعة أو الإصدار أو الإقفال",
  original_audio_integrity_failed: "أحد التسجيلات الأصلية لا يطابق بصمته المحفوظة. يجب مراجعة سلامة الدليل قبل الإصدار أو الإقفال",
  exactly_one_lead_required: "عيّن محققاً رئيسياً واحداً", reopen_investigation_before_editing: "أعد فتح جلسة التحقيق أولاً",
  participant_details_incomplete: "استكمل بيانات الأشخاص في إعداد الجلسة",
  report_conclusion_required: "أضف خلاصة التحقيق", report_conclusion_incomplete: "أكمل الوقائع والاستنتاج",
  report_responsibilities_required: "أكمل المسؤوليات أو اختر لا يوجد", report_proposals_required: "أكمل الاقتراحات أو اختر لا يوجد",
  report_finding_incomplete: "أكمل نص نتيجة المسؤولية والشخص المعني", report_finding_evidence_required: "اربط كل نتيجة مسؤولية بدليل أو قسم داعم",
  report_responsibility_conflict: "راجع التعارض بين لا يوجد ونتائج المسؤولية", report_proposals_conflict: "راجع التعارض بين لا يوجد ونص الاقتراحات",
  report_dictation_pending: "راجع الإملاءات الصوتية وأدرجها أو استبعدها قبل الإصدار", dictation_audio_missing: "انتظر حفظ تسجيل الإملاء الأصلي",
  dictation_audio_integrity_failed: "تسجيل الإملاء لا يطابق بصمته المحفوظة",
};
export const reportReason = (value: string) => reasons[value] ?? "تحتاج بيانات المحضر أو مصادره إلى مراجعة قبل المتابعة";

const sourceAreas: Record<string, string> = { session: "بيانات الجلسة", subjects: "بيانات المشاركين ووثائقهم", investigators: "المحققون والتكليفات", speakers: "هوية المتحدثين", people: "أسماء الأشخاص", recordings: "الأدلة الصوتية", transcripts: "النص ونسبة الأقوال" };
const sourceFields: Record<string, string> = { title: "الموضوع", location: "المكان", session_date: "التاريخ", start_time: "وقت البدء", end_time: "وقت الانتهاء", subject_name: "الاسم المدوّن", statement_details: "بيانات الإفادة", military_id: "الرقم العسكري", rank: "الرتبة", unit: "الوحدة", department: "القسم", display_name: "اسم العرض", role: "الدور", assignment_role: "التكليف", sha256: "بصمة الدليل", segments_sha256: "مراجعة النص", person_name: "الاسم", full_name: "الاسم", identity_id: "الهوية المرتبطة" };
const sourceValue = (value: unknown) => value == null ? "—" : typeof value === "boolean" ? (value ? "نعم" : "لا") : String(value);

interface Archive { reports: { id: string; report_version: number; report_number: string; created_at: string }[] }
export function ReportIssuance({ sessionId, state, blocked, onState, onStatusChange, canApprove = false }: {
  sessionId: string; state: HtmlReportState; blocked: boolean;
  onState: (state: HtmlReportState) => void; onStatusChange: () => void;
  canApprove?: boolean;
}) {
  const { can } = useAuth();
  const [archive, setArchive] = useState<Archive>({ reports: [] });
  const [reviewed, setReviewed] = useState(false);
  const [ack, setAck] = useState(false);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const base = `/investigations/${sessionId}`;
  const reload = () => http.get<Archive>(`${base}/reports`).then(setArchive);
  useEffect(() => { void reload().catch(() => setMessage("تعذر تحميل سجل الإصدارات")); setReviewed(false); setAck(false); }, [sessionId, state.token, state.source_token]);
  const action = async (path: string, body: object, statusChange = false) => {
    setBusy(true); setMessage("");
    try {
      await http.post(path, { expected_token: state.token, ...body });
      onState(await http.get<HtmlReportState>(`${base}/report/html`));
      await reload();
      if (statusChange) onStatusChange();
      setMessage("تم حفظ الإجراء بنجاح");
    } catch { setMessage("تعذر إتمام الإجراء. تحقق من المتطلبات أو أعد التحميل عند تغيّر البيانات في نافذة أخرى."); }
    finally { setBusy(false); }
  };
  return <section className="card card-body" aria-label="مراجعة المحضر وإصداره">
    <h2>المراجعة والإصدار الرسمي</h2>
    {message && <Alert kind="info">{message}</Alert>}
    {state.sources_changed && <Alert kind="warning">تغيّرت بيانات الجلسة أو هوية المتحدثين أو النص المصدر. النص المحفوظ لم يتغير تلقائياً. راجع الفروق وأعد التعبئة عند الحاجة.</Alert>}
    {state.sources_changed && !!state.source_changes?.length && <details className="mb-16"><summary>التغييرات منذ آخر مراجعة ({state.source_changes.length})</summary>
      <div className="table-wrap"><table><thead><tr><th>المصدر</th><th>البيان</th><th>قبل</th><th>الآن</th></tr></thead><tbody>
        {state.source_changes.map(change => {
          const parts = change.field.split(".");
          return <tr key={change.field}><td>{sourceAreas[parts[0]] ?? "بيانات المصدر"}</td><td>{sourceFields[parts[parts.length - 1]] ?? "تحديث في بيانات المصدر"}</td>
            <td style={{ overflowWrap: "anywhere", whiteSpace: "normal" }}><bdi>{sourceValue(change.before)}</bdi></td><td style={{ overflowWrap: "anywhere", whiteSpace: "normal" }}><bdi>{sourceValue(change.after)}</bdi></td></tr>;
        })}
      </tbody></table></div>
    </details>}
    {state.blocked_reasons.length > 0 && <ul>{state.blocked_reasons.map(value => <li key={value}>{reportReason(value)}</li>)}</ul>}
    {state.status !== "FINAL" && can("reports.generate") && <>
      <button className="btn" disabled={blocked || busy} onClick={() => void action(`${base}/report/html/refresh-sources`, {})}>تحديث مصادر الاستيراد دون تغيير الإفادات المحفوظة</button>
      <label className="checkbox"><input type="checkbox" checked={reviewed} disabled={blocked || busy} onChange={e => setReviewed(e.target.checked)} />راجعت بيانات المحضر ومحتواه ونسبة الأقوال إلى أصحابها</label>
      {state.sources_changed && <label className="checkbox"><input type="checkbox" checked={ack} onChange={e => setAck(e.target.checked)} />راجعت تغييرات المصدر وأؤكد ملاءمة النص المحفوظ</label>}
      <button className="btn" disabled={blocked || busy || !canApprove || !reviewed || (state.sources_changed && !ack)} onClick={() => void action(`${base}/report/html/review`, {
        expected_source_token: state.source_token, content_reviewed: true, acknowledge_source_changes: ack,
      })}>حفظ تأكيد المراجعة</button>
      {can("reports.finalize") && <button className="btn btn-primary" disabled={blocked || busy || !canApprove || state.blocked_reasons.length > 0}
        onClick={() => void action(`${base}/reports`, {}, true)}>إصدار وحفظ HTML وPDF</button>}
    </>}
    {state.status === "FINAL" && can("reports.generate") && <>
      <Field label="سبب التصحيح وإعادة فتح المسودة"><textarea className="textarea" value={reason} maxLength={2000} onChange={e => setReason(e.target.value)} /></Field>
      <button className="btn" disabled={blocked || busy || reason.trim().length < 3} onClick={() => void action(`${base}/report/reopen`, { reason }, true)}>فتح مسودة تصحيح مع الاحتفاظ بالإصدارات الصادرة</button>
    </>}
    <h3>الإصدارات الصادرة</h3>
    {archive.reports.length === 0 && <p>لا توجد إصدارات HTML/PDF صادرة بعد.</p>}
    {archive.reports.map(report => <div className="flex gap wrap" key={report.id}>
      <span>الإصدار {report.report_version} — <bdi>{report.report_number}</bdi></span>
      {(["html", "pdf"] as const).map(format => <button className="btn" key={format} onClick={() => void downloadFile(`${base}/reports/${report.id}/file?format=${format}`, `report-v${report.report_version}.${format}`).catch(() => setMessage("تعذر تنزيل الملف"))}>{format.toUpperCase()}</button>)}
      <button className="btn" onClick={() => void http.get<{ ok: boolean }>(`${base}/reports/${report.id}/verify`).then(value => setMessage(value.ok ? "الملفات سليمة وتطابق البصمات المحفوظة" : "فشل التحقق: أحد الملفات مفقود أو معدّل")).catch(() => setMessage("تعذر التحقق"))}>التحقق من سلامة الملفات</button>
    </div>)}
  </section>;
}
