import { Link } from "react-router-dom";
import type { Investigation } from "@/api/types";
import { Alert } from "@/components/ui";

export function IntakeReadiness({ session }: { session: Investigation }) {
  const state = session.intake_readiness;
  if (!state || state.ready || ["CLOSED", "ARCHIVED"].includes(session.workflow_state)) return null;
  const groups = new Map<string, typeof state.issues>();
  for (const issue of state.issues) {
    const key = issue.participant_key || "session";
    groups.set(key, [...(groups.get(key) ?? []), issue]);
  }
  return <Alert kind="warning"><h2>استكمال بيانات الأشخاص</h2>
    <p>يمكن حفظ مسودة. أكمل البيانات المطلوبة قبل بدء تسجيل جديد أو تجهيز المحضر.</p>
    <details open><summary>بيانات تحتاج الاستكمال ({state.issues.length})</summary>{[...groups].map(([key, issues]) => <section key={key} className="mt-16">
      <h3>{issues[0].person_name || "بيانات الجلسة"}</h3><ul>{issues.map(item =>
        <li key={item.target}><Link to={`/investigations/${session.id}/edit#${item.target}`}>{item.label}{item.code === "participant_exception_conflict" ? " — راجع التعارض بين القيمة والاستثناء" : ""}</Link></li>)}</ul>
    </section>)}</details>
    <Link className="btn mt-8" to={`/investigations/${session.id}/edit`}>استكمال البيانات</Link>
  </Alert>;
}
