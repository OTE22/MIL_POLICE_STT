import { Link } from "react-router-dom";
import { Field } from "./ui";
import type { Investigation } from "@/api/types";
import type { HtmlReportDocument } from "@/lib/html-report";

export function ReportOpeningEditor({ document, session, disabled, onChange }: {
  document: HtmlReportDocument; session: Investigation; disabled: boolean; onChange: (value: HtmlReportDocument) => void;
}) {
  const opening = document.opening ?? {};
  const update = (patch: NonNullable<HtmlReportDocument["opening"]>) => onChange({ ...document, opening: { ...opening, ...patch } });
  return <div className="report-focused-fields" data-testid="report-opening-editor">
    <h3>افتتاح المحضر</h3>
    <p>تظهر هذه المقدمة قبل أول إفادة وفق بنية النموذج المرجعي. العبارات الرسمية ثابتة.</p>
    <dl><dt>تاريخ الجلسة ووقت الافتتاح</dt><dd><bdi>{session.session_date || "غير مكتمل"} — {session.start_time || "غير مكتمل"}</bdi></dd>
      <dt>مكان التحقيق</dt><dd>{session.location || "غير مكتمل"}</dd></dl>
    <Link id="report-field-opening-session_context" to={`/investigations/${session.id}/edit`}>استكمال تاريخ الجلسة ووقتها ومكانها والتكليفات</Link>
    <p id="report-field-opening-profile_context" tabIndex={-1}>يُستخدم المحقق والكاتب العدلي المحددان أعلى الصفحة، مع رتبتهما ووحدة المحقق ورقم الكاتب من سجلاتهما. استكمل البيانات الناقصة في سجل المحقق قبل الإصدار.</p>
    <Field label="رقم الإحالة"><input id="report-field-opening-referral_number" className="input" disabled={disabled} maxLength={200} value={opening.referral_number ?? ""} onChange={e => update({ referral_number: e.target.value })} /></Field>
    <Field label="تاريخ الإحالة"><input id="report-field-opening-referral_date" className="input" type="date" disabled={disabled} value={opening.referral_date ?? ""} onChange={e => update({ referral_date: e.target.value || null })} /></Field>
    <Field label="الجهة المحيلة"><input id="report-field-opening-referral_authority" className="input" disabled={disabled} maxLength={500} value={opening.referral_authority ?? ""} onChange={e => update({ referral_authority: e.target.value })} /></Field>
    <label className="checkbox"><input id="report-field-opening-oath_confirmed" type="checkbox" disabled={disabled || !document.clerk_id || document.clerk_id === document.investigator_id} checked={!!opening.oath_confirmed} onChange={e => update({ oath_confirmed: e.target.checked })} />تم اتخاذ الكاتب كاتباً عدلياً وتحليفه اليمين القانونية فعلياً</label>
    <blockquote>والله العظيم إني أقوم بواجبي بكل أمانة وإخلاص وأحفظ سر التحقيق</blockquote>
    <label className="checkbox"><input id="report-field-opening-uniform_confirmed" type="checkbox" disabled={disabled} checked={!!opening.uniform_confirmed} onChange={e => update({ uniform_confirmed: e.target.checked })} />أؤكد ارتداء اللباس العسكري كما تنص مقدمة النموذج</label>
    <p className="muted">لا تؤكد إجراءً لم يحصل. تبقى المسودة قابلة للحفظ حتى استكمال متطلبات الإصدار.</p>
  </div>;
}
