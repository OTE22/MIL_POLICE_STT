import { Link } from "react-router-dom";
import type { Investigation, Transcript } from "@/api/types";
import { IconCheck, IconChevronLeft, IconClock, IconFile, IconMic, IconUsers } from "@/components/Icons";
import { formatDuration } from "@/lib/format";

/** Navigation guidance describes available work; it never marks human review as complete. */
export function InvestigationGuide({ session, transcript }: { session: Investigation; transcript: Transcript | null | undefined }) {
  const pending = transcript?.speakers.filter(speaker => !speaker.identity_id).length ?? 0;
  const processing = session.status === "PROCESSING";
  const hasText = session.has_transcript;
  const next = processing ? "recording" : hasText ? "transcript" : "recording";
  const steps = [
    { key: "details", title: "بيانات الجلسة", description: `${session.subjects.length} مشاركين · ${session.investigators.length} محققين`, Icon: IconUsers },
    { key: "recording", title: "التسجيل والمعالجة", description: processing ? "المعالجة قيد التنفيذ" : `${session.recordings.length} ملفات صوتية`, Icon: IconMic },
    { key: "transcript", title: "مراجعة النص", description: hasText ? "النص متاح للمراجعة" : "بعد معالجة التسجيل", Icon: IconFile },
    { key: "speakers", title: "تحديد المتحدثين", description: transcript ? (pending ? `${pending} عينات بانتظار الهوية` : transcript.speakers.length ? "هويات العينات محددة" : "لا توجد عينات بعد") : "بعد معالجة التسجيل", Icon: IconCheck },
  ];
  return <section className="investigation-guide" data-testid="investigation-guide" aria-label="مسار العمل في الجلسة">
    <div className="investigation-guide-intro"><div><span className="workspace-eyebrow">نظرة عامة</span><h2>كل ما تحتاجه لمتابعة الجلسة</h2>
      <p>{processing ? "التسجيل قيد المعالجة. تابع تقدّمه قبل مراجعة النتائج." : hasText ? "النص المفرغ متاح. راجعه مع التسجيل، ثم تحقّق من هويات المتحدثين." : "راجع بيانات المشاركين، ثم أضف تسجيلاً لبدء تفريغ الجلسة."}</p></div>
      <Link className="btn btn-primary" to={`?tab=${next}`}>{processing ? "متابعة المعالجة" : hasText ? "مراجعة النص المفرغ" : "إضافة تسجيل"}<IconChevronLeft /></Link>
    </div>
    <nav className="investigation-workflow" aria-label="خطوات الجلسة">{steps.map((step, index) => <Link key={step.key} to={`?tab=${step.key}`} className={`investigation-workflow-step ${step.key === next ? "is-next" : ""}`}>
      <span className="workflow-number">{index + 1}</span><div><strong>{step.title}</strong><span>{step.description}</span></div><step.Icon />
    </Link>)}</nav>
    <div className="investigation-guide-footnote"><IconClock /><span>مدة الجلسة: {formatDuration(session.duration_seconds)}</span><span>تبقى بيانات الجلسة والنص والتسجيل متاحة من التبويبات أعلاه.</span></div>
  </section>;
}
