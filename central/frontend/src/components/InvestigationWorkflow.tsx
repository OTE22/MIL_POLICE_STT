import { useState } from "react";
import { http } from "@/api/client";
import type { Investigation } from "@/api/types";
import { useAuth } from "@/lib/auth";
import { Alert, Field } from "@/components/ui";
export const workflowLabels: Record<string, string> = { DRAFT: "مسودة", IN_PROGRESS: "قيد التحقيق", AWAITING_REVIEW: "بانتظار المراجعة", REVIEWED: "تمت المراجعة", CLOSED: "مقفلة", ARCHIVED: "مؤرشفة" };
const transitions: Record<string, string[]> = { DRAFT: ["IN_PROGRESS", "ARCHIVED"], IN_PROGRESS: ["AWAITING_REVIEW", "ARCHIVED"], AWAITING_REVIEW: ["IN_PROGRESS", "REVIEWED"], REVIEWED: ["IN_PROGRESS", "CLOSED"], CLOSED: ["IN_PROGRESS", "ARCHIVED"], ARCHIVED: ["IN_PROGRESS"] };
export function InvestigationWorkflow({ session, onChange }: { session: Investigation; onChange: (value: Investigation) => void }) {
  const { can } = useAuth();
  const [reason, setReason] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  return <section className="card card-body"><h2>حالة جلسة التحقيق: {workflowLabels[session.workflow_state] ?? workflowLabels.DRAFT}</h2>
    <p>المراجعة والإقفال مستقلان عن انتهاء معالجة التسجيلات.</p>
    <p>مهام المعالجة: نشطة {(session.processing_summary?.REQUESTED ?? 0) + (session.processing_summary?.ACCEPTED ?? 0) + (session.processing_summary?.PROCESSING ?? 0)} · تحتاج إعادة المحاولة {session.unresolved_processing_failures ?? 0} · مكتملة {session.processing_summary?.COMPLETED ?? 0}</p>
    {error && <Alert kind="danger">{error}</Alert>}
    {can("investigations.update") && <><Field label="سبب الانتقال أو إعادة الفتح"><input className="input" value={reason} maxLength={2000} onChange={e => setReason(e.target.value)} /></Field>
      <div className="flex gap wrap">{(transitions[session.workflow_state] ?? []).filter(state =>
        (!["REVIEWED", "CLOSED"].includes(state) || can("reports.finalize")) && (state !== "ARCHIVED" || can("investigations.archive"))).map(state =>
        <button className="btn" key={state} disabled={busy || reason.trim().length < 3} onClick={async () => {
          setBusy(true); setError("");
          try { onChange(await http.post<Investigation>(`/investigations/${session.id}/workflow`, { state, reason, expected_revision: session.revision })); setReason(""); }
          catch { setError("تعذر تغيير الحالة. تحقق من إصدار المحضر وحفظ التسجيلات وانتهاء المهام، أو أعد التحميل عند تغيّر البيانات."); }
          finally { setBusy(false); }
        }}>{state === "IN_PROGRESS" && ["CLOSED", "ARCHIVED"].includes(session.workflow_state) ? "إعادة فتح التحقيق" : workflowLabels[state]}</button>)}</div>
    </>}
  </section>;
}
