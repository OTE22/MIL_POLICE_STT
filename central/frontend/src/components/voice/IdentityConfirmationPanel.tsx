import { useState } from "react";
import { ApiError, http } from "@/api/client";
import type { BiometricCheck } from "@/api/types";
import { Alert, Badge, Field } from "@/components/ui";
import { formatDateTime } from "@/lib/format";
import { errorMessage } from "@/lib/i18n";
import { printGroupLabel } from "@/lib/voice-review";

export function IdentityConfirmationPanel({ result, selected, canManage, disabled, onBusy, onStale, onSaved }: {
  result: BiometricCheck; selected: string[]; canManage: boolean; disabled: boolean;
  onBusy: (busy: boolean) => void; onStale: () => void; onSaved: () => Promise<void>;
}) {
  const [reason, setReason] = useState("");
  const [reopen, setReopen] = useState<string | null>(null);
  const [reopenReason, setReopenReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const rows = result.groups.flatMap(g => g.prints);
  const name = (id: string) => {
    const index = rows.findIndex(r => r.enrollment_id === id);
    return index >= 0 ? `العينة ${index + 1} — ${printGroupLabel(result, id)}` : `بصمة غير فعالة أو محذوفة (${id})`;
  };
  const save = async (confirmationId?: string) => {
    onBusy(true); setError(null); setNotice(null);
    const base = `/voice-enrollments/people/${result.identity_id}/identity-confirmations`;
    try {
      if (confirmationId) await http.post(`${base}/${confirmationId}/reopen`, { reason: reopenReason.trim() });
      else await http.post(base, { reason: reason.trim(), prints: selected.map(id => ({
        enrollment_id: id, expected_updated_at: rows.find(r => r.enrollment_id === id)?.updated_at,
      })) });
      setReason(""); setReopen(null); setReopenReason("");
      setNotice(confirmationId ? "أُعيد فتح المراجعة وحُفظ السبب في السجل." : "تم تأكيد وحدة الهوية للعينات المحددة وحفظ القرار.");
      await onSaved();
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        onStale(); setError(err.code === "voice_confirmation_exists" ? "هذه العينات مؤكدة مسبقاً. أعد الفحص لعرض التأكيد." : "تغيرت حالة المراجعة أو إحدى العينات. أعد الفحص قبل المتابعة.");
      } else setError(err instanceof ApiError ? errorMessage(err.code) : "تعذر حفظ القرار. حاول مجدداً.");
    } finally { onBusy(false); }
  };
  return <section className="mt-8" aria-label="تأكيد وحدة الهوية" data-testid="identity-confirmations">
    <h4>تأكيد وحدة الهوية</h4>
    <p className="muted small">تأكيد بشري بأن العينات المحددة تخص «{result.person_name}». يشمل الاختيار عينات من المجموعة نفسها أو من مجموعات مختلفة؛ تبقى المقارنات الآلية والبصمات الأصلية محفوظة.</p>
    {error && <Alert kind="danger">{error}</Alert>}
    {notice && <Alert kind="success">{notice}</Alert>}
    {canManage && selected.length >= 2 && <div className="card card-body mt-8" data-testid="identity-confirmation-form">
      <strong>العينات المحددة ({selected.length})</strong>
      <ul>{selected.map(id => <li key={id}>{name(id)}</li>)}</ul>
      <Field label="سبب تأكيد وحدة الهوية" required><textarea className="input" value={reason} onChange={e => setReason(e.target.value)} maxLength={2000} disabled={disabled} /></Field>
      <button className="btn btn-primary" disabled={disabled || !reason.trim() || selected.length > 100} onClick={() => void save()}>تأكيد أن العينات للشخص نفسه</button>
    </div>}
    {(result.identity_confirmations ?? []).length === 0 && <p className="muted">لا توجد تأكيدات يدوية مسجلة. حدّد عينتين أو أكثر للمراجعة.</p>}
    {(result.identity_confirmations ?? []).map((confirmation, i) => <article className="card card-body mt-8" key={confirmation.id} data-testid="identity-confirmation">
      <div className="flex gap wrap"><strong>مجموعة تأكيد يدوي {i + 1}</strong><Badge kind={confirmation.status === "ACTIVE" ? "green" : "amber"}>
        {confirmation.status === "ACTIVE" ? "نفس الشخص — مؤكّد يدوياً" : confirmation.status === "STALE" ? "تغيّرت العينات — تحتاج إعادة مراجعة" : "أُعيد فتح المراجعة"}
      </Badge></div>
      <p className="muted small">{confirmation.reviewer_name ?? "مستخدم محذوف"} · {formatDateTime(confirmation.created_at)}</p>
      <p style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{confirmation.reason}</p>
      <details><summary>العينات والمجموعات الأصلية ({confirmation.enrollment_ids.length})</summary>
        <ul>{confirmation.enrollment_ids.map(id => <li key={id} style={{ overflowWrap: "anywhere" }}>{name(id)}</li>)}</ul>
      </details>
      {confirmation.reopened_at && <p style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>إعادة فتح المراجعة: {confirmation.reopened_by_name ?? "مستخدم محذوف"} · {formatDateTime(confirmation.reopened_at)}<br />{confirmation.reopened_reason}</p>}
      {canManage && confirmation.status !== "REOPENED" && <button className="btn btn-sm mt-8" disabled={disabled} onClick={() => { setReopen(confirmation.id); setReopenReason(""); }}>إعادة فتح المراجعة</button>}
      {reopen === confirmation.id && <div className="mt-8">
        <Field label="سبب إعادة فتح المراجعة" required><textarea className="input" maxLength={2000} value={reopenReason} onChange={e => setReopenReason(e.target.value)} disabled={disabled} /></Field>
        <button className="btn btn-primary" disabled={disabled || !reopenReason.trim()} onClick={() => void save(confirmation.id)}>تأكيد إعادة الفتح</button>
        <button className="btn" disabled={disabled} onClick={() => setReopen(null)}>إلغاء</button>
      </div>}
    </article>)}
    <p className="muted small">التأكيد خاص بالعينات المحددة وقت المراجعة. إضافة بصمة جديدة لا تؤكدها تلقائياً، وتعديل بصمة مشمولة أو تعطيلها يستدعي إعادة المراجعة.</p>
  </section>;
}
