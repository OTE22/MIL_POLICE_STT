import { Link } from "react-router-dom";
import { getToken } from "@/api/client";
import type { Investigation } from "@/api/types";
import { useAuth } from "@/lib/auth";
import { formatBytes, formatDate, formatDateTime, formatDuration, formatTime } from "@/lib/format";
import { T, t } from "@/lib/i18n";
import { countryName } from "@/lib/countries";
import { documentSummary, subjectIdentitySummary } from "@/components/subjects/SubjectFields";
import { ParticipantStatementDetails } from "@/components/subjects/ParticipantStatementDetails";
import { Alert, Badge } from "@/components/ui";
import { IconFile, IconUsers, IconFolder } from "@/components/Icons";

/** Opens a protected document scan through an authenticated fetch (token never in a URL). */
async function openDocument(sessionId: string, documentId: string): Promise<void> {
  const res = await fetch(`/api/investigations/${sessionId}/subject-documents/${documentId}/file`, {
    headers: { Authorization: `Bearer ${getToken() ?? ""}` },
  });
  if (!res.ok) return;
  const url = URL.createObjectURL(await res.blob());
  window.open(url, "_blank", "noopener,noreferrer");
  setTimeout(() => URL.revokeObjectURL(url), 60000);
}

export function InvestigationDetails({ session, canViewDocuments }: { session: Investigation; canViewDocuments: boolean }) {
  const { can } = useAuth();
  const canEdit = can("investigations.update");
  return <div className="investigation-details-layout" data-testid="investigation-details">
    <div className="investigation-details-main">
      <div className="card">
        <div className="card-header">
          <div><h3><IconUsers />{T.subjectInfo}<span className="workspace-section-count">{session.subjects.length}</span></h3><p className="workspace-section-hint">هويات المشاركين ووثائقهم وبيانات إفاداتهم في هذه الجلسة.</p></div>
        </div>
        <div className="card-body">
          {session.subjects.length === 0 && <div className="workspace-empty"><IconUsers /><h3>لم تتم إضافة مشاركين بعد</h3><p>أضف بيانات المشاركين من تعديل الجلسة.</p>{canEdit && <Link className="btn" to={`/investigations/${session.id}/edit`}>إضافة المشاركين</Link>}</div>}
          {session.subjects.map((s, i) => (
            <div className="subject-summary" key={s.id ?? i} data-testid="subject-summary">
              <div className="flex between wrap">
                <strong>{s.subject_name || T.unnamed}</strong>
                <span className="flex wrap">
                  <Badge kind={s.person_type === "MILITARY" ? "navy" : s.person_type === "UNKNOWN" ? "amber" : "blue"}>
                    {t(`person_${s.person_type}`)}
                  </Badge>
                  <Badge kind={s.identity_confidence === "VERIFIED" ? "green" : s.identity_confidence === "DOCUMENT_SEEN" ? "blue" : "gray"}>
                    {t(`confidence_${s.identity_confidence}`)}
                  </Badge>
                  {s.is_undocumented && <Badge kind="amber">{T.isUndocumented}</Badge>}
                  {s.is_unregistered && <Badge kind="amber">{T.isUnregistered}</Badge>}
                </span>
              </div>
              <div className="muted small">{subjectIdentitySummary(s)}</div>
              {s.participant_key && <ParticipantStatementDetails sessionId={session.id} participantKey={s.participant_key} />}
              <dl className="dl mt-8">
                {s.person_type === "MILITARY" && (
                  <>
                    {s.security_branch && <div><dt>{T.securityBranch}</dt><dd>{t(`branch_${s.security_branch}`)}</dd></div>}
                    {s.rank && <div><dt>{T.rank}</dt><dd>{s.rank}</dd></div>}
                    {s.military_id && <div><dt>{T.militaryId}</dt><dd className="ltr">{s.military_id}</dd></div>}
                    {s.unit && <div><dt>{T.unit}</dt><dd>{s.unit}</dd></div>}
                    {s.department && <div><dt>{T.department}</dt><dd>{s.department}</dd></div>}
                  </>
                )}
                {s.person_type === "CIVILIAN" && (
                  <>
                    <div><dt>{T.nationality}</dt><dd>{countryName(s.nationality_code, s.nationality_name)}</dd></div>
                    {s.register_number && <div><dt>{T.registerNumber}</dt><dd className="ltr">{s.register_number}</dd></div>}
                    {s.place_of_registration && <div><dt>{T.placeOfRegistration}</dt><dd>{s.place_of_registration}</dd></div>}
                  </>
                )}
                {s.is_undocumented && s.undocumented_reason && (
                  <div><dt>{T.undocumentedReason}</dt><dd>{t(`reason_${s.undocumented_reason}`)}</dd></div>
                )}
                {s.notes && <div><dt>{T.notes}</dt><dd className="muted">{s.notes}</dd></div>}
              </dl>
              <div className="mt-8">
                <dt className="muted small">{T.documents}</dt>
                {s.documents.length === 0 ? (
                  <div className="muted small">{T.noDocuments}</div>
                ) : (
                  <ul className="doc-list">
                    {s.documents.map((d) => (
                      <li key={d.id}>
                        <span>{documentSummary(d)}</span>
                        {d.is_expired && <Badge kind="amber">{T.documentExpired}</Badge>}
                        {d.has_file ? (
                          canViewDocuments ? (
                            <button className="btn btn-sm" type="button" onClick={() => openDocument(session.id, d.id!)}>
                              {T.viewDocumentFile}
                            </button>
                          ) : (
                            <Badge kind="gray">{T.err_forbidden}</Badge>
                          )
                        ) : (
                          <span className="muted small">{T.noFileUploaded}</span>
                        )}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
              {(s.duplicate_of_sessions?.length ?? 0) > 0 && (
                <div className="mt-8">
                  <Alert kind="warning">
                    {T.duplicateDocumentWarning} <span className="mono">{s.duplicate_of_sessions!.join("، ")}</span>
                  </Alert>
                </div>
              )}
            </div>
          ))}
        </div>
      </div>
      <section className="card">
        <div className="card-header"><div><h3><IconFile />التسجيلات<span className="workspace-section-count">{session.recordings.length}</span></h3><p className="workspace-section-hint">الملفات الصوتية المرتبطة بالجلسة وحالة حفظها.</p></div><Link className="btn btn-sm" to="?tab=recording">فتح التسجيل</Link></div>
        {session.recordings.length === 0 ? <div className="workspace-empty"><IconFile /><p>لا توجد تسجيلات مضافة إلى هذه الجلسة بعد.</p></div> : <div className="recording-file-list">{session.recordings.map(recording => <article className="recording-file" key={recording.id}>
          <div className="recording-file-heading"><IconFile /><div><strong><bdi>{recording.original_filename}</bdi></strong><p><span>{formatDuration(recording.duration_seconds)}</span><span>{formatBytes(recording.size_bytes)}</span><span>{formatDateTime(recording.created_at)}</span></p></div>
            <Badge kind={recording.upload_status === "UPLOADED" ? "green" : recording.upload_status === "PENDING" ? "amber" : "gray"}>{recording.upload_status === "UPLOADED" ? "محفوظ مركزياً" : recording.upload_status === "PENDING" ? "بانتظار الرفع" : "الرفع معطّل"}</Badge></div>
          <details className="workspace-disclosure"><summary>بيانات المصدر والتحقق</summary><div>بصمة الملف (SHA-256): <bdi className="mono">{recording.sha256 ?? T.none}</bdi></div></details>
        </article>)}</div>}
      </section>
    </div>
    <aside className="investigation-details-aside" aria-label="معلومات الجلسة والفريق">
      <section className="card"><div className="card-header"><h3><IconFolder />{T.sessionInfo}</h3></div><div className="card-body">
        <dl className="dl">
          <div><dt>{T.location}</dt><dd>{session.location ?? T.none}</dd></div>
          <div><dt>{T.sessionDate}</dt><dd className="num">{formatDate(session.session_date)}</dd></div>
          <div><dt>وقت الجلسة</dt><dd>{formatTime(session.start_time)} — {formatTime(session.end_time)}</dd></div>
          <div><dt>{T.expectedSpeakers}</dt><dd className="num">{session.expected_speaker_count}</dd></div>
          <div><dt>{T.createdBy}</dt><dd>{session.created_by_name ?? T.none}</dd></div>
        </dl>
        {session.description && <div className="mt-16"><span className="muted small">{T.description}</span><p style={{ whiteSpace: "pre-wrap" }}>{session.description}</p></div>}
        {session.speaker_limit_warning && <div className="mt-16"><Alert kind="warning">{T.speakerLimitWarning}</Alert></div>}
        <details className="workspace-disclosure"><summary>تواريخ الإنشاء والتحديث</summary><dl className="dl"><div><dt>{T.createdAt}</dt><dd>{formatDateTime(session.created_at)}</dd></div><div><dt>{T.updatedAt}</dt><dd>{formatDateTime(session.updated_at)}</dd></div></dl></details>
      </div></section>
      <section className="card"><div className="card-header"><h3><IconUsers />{T.investigatorsLabel}<span className="workspace-section-count">{session.investigators.length}</span></h3></div>
        {session.investigators.length === 0 ? <div className="workspace-empty"><p>لم تتم إضافة محققين إلى الجلسة.</p>{canEdit && <Link className="btn btn-sm" to={`/investigations/${session.id}/edit`}>تعيين المحققين</Link>}</div> : <div className="investigator-list">{session.investigators.map(person => <article className="investigator-person" key={person.id}>
          <span className="investigator-avatar"><IconUsers /></span><div><strong>{person.full_name}</strong><p>{[person.rank, person.unit].filter(Boolean).join(" · ") || T.none}</p><p>{T.militaryId}: <bdi>{person.military_id ?? T.none}</bdi></p><Badge kind={person.assignment_role === "LEAD" ? "navy" : "gray"}>{person.assignment_role === "LEAD" ? T.leadInvestigator : T.assistantInvestigator}</Badge></div>
        </article>)}</div>}
      </section>
      {session.notes && <section className="card"><div className="card-header"><h3>{T.notes}</h3></div><div className="card-body" style={{ whiteSpace: "pre-wrap" }}>{session.notes}</div></section>}
    </aside>
  </div>;
}
