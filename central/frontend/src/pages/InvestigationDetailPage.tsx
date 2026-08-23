import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";

import { ApiError, getToken, http } from "@/api/client";
import type { AuditEntry, Investigation, Paged, SessionStatus, Transcript } from "@/api/types";
import { useAuth } from "@/lib/auth";
import { formatBytes, formatDate, formatDateTime, formatDuration, formatTime } from "@/lib/format";
import { AUDIT_ACTIONS, T, errorMessage, t } from "@/lib/i18n";
import { countryName } from "@/lib/countries";
import { documentSummary, subjectIdentitySummary } from "@/components/subjects/SubjectFields";
import { Alert, Badge, Loading, SessionStatusBadge, useToast } from "@/components/ui";
import { IconEdit } from "@/components/Icons";
import { AgentStatusPanel, useAgentStatus } from "@/components/recording/AgentStatus";
import { Recorder, type PendingAudio } from "@/components/recording/Recorder";
import { ProcessingPanel } from "@/components/recording/ProcessingPanel";
import { TranscriptViewer } from "@/components/transcript/TranscriptViewer";
import { SpeakersPanel } from "@/components/transcript/SpeakersPanel";

type Tab = "details" | "recording" | "transcript" | "speakers" | "activity";
const TABS: { key: Tab; label: string }[] = [
  { key: "details", label: T.tabDetails },
  { key: "recording", label: T.tabRecording },
  { key: "transcript", label: T.tabTranscript },
  { key: "speakers", label: T.tabSpeakers },
  { key: "activity", label: T.tabActivity },
];

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

function DetailsTab({ session, canViewDocuments }: { session: Investigation; canViewDocuments: boolean }) {
  return (
    <>
      <div className="card">
        <div className="card-header">
          <h3>{T.sessionInfo}</h3>
        </div>
        <div className="card-body">
          <dl className="dl">
            <div><dt>{T.sessionNumber}</dt><dd className="mono">{session.session_number}</dd></div>
            <div><dt>{T.title}</dt><dd>{session.title}</dd></div>
            <div><dt>{T.status}</dt><dd><SessionStatusBadge status={session.status} /></dd></div>
            <div><dt>{T.location}</dt><dd>{session.location ?? T.none}</dd></div>
            <div><dt>{T.sessionDate}</dt><dd className="num">{formatDate(session.session_date)}</dd></div>
            <div><dt>{T.startTime}</dt><dd className="num">{formatTime(session.start_time)}</dd></div>
            <div><dt>{T.endTime}</dt><dd className="num">{formatTime(session.end_time)}</dd></div>
            <div><dt>{T.duration}</dt><dd>{formatDuration(session.duration_seconds)}</dd></div>
            <div><dt>{T.expectedSpeakers}</dt><dd className="num">{session.expected_speaker_count}</dd></div>
            <div><dt>{T.createdBy}</dt><dd>{session.created_by_name ?? T.none}</dd></div>
            <div><dt>{T.createdAt}</dt><dd className="num">{formatDateTime(session.created_at)}</dd></div>
            <div><dt>{T.updatedAt}</dt><dd className="num">{formatDateTime(session.updated_at)}</dd></div>
          </dl>
          {session.description && (
            <div className="mt-16">
              <dt className="muted small">{T.description}</dt>
              <p style={{ whiteSpace: "pre-wrap" }}>{session.description}</p>
            </div>
          )}
          {session.speaker_limit_warning && (
            <div className="mt-16">
              <Alert kind="warning">{T.speakerLimitWarning}</Alert>
            </div>
          )}
        </div>
      </div>

      <div className="card">
        <div className="card-header">
          <h3>{T.investigatorsLabel}</h3>
        </div>
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>{T.fullName}</th>
                <th>{T.rank}</th>
                <th>{T.militaryId}</th>
                <th>{T.unit}</th>
                <th>{T.assignmentRole}</th>
              </tr>
            </thead>
            <tbody>
              {session.investigators.length === 0 && <tr><td colSpan={5} className="empty">{T.noData}</td></tr>}
              {session.investigators.map((i) => (
                <tr key={i.id}>
                  <td>{i.full_name}</td>
                  <td>{i.rank ?? T.none}</td>
                  <td className="ltr">{i.military_id ?? T.none}</td>
                  <td>{i.unit ?? T.none}</td>
                  <td><Badge kind={i.assignment_role === "LEAD" ? "navy" : "gray"}>{i.assignment_role === "LEAD" ? T.leadInvestigator : T.assistantInvestigator}</Badge></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="card">
        <div className="card-header">
          <h3>{T.subjectInfo}</h3>
        </div>
        <div className="card-body">
          {session.subjects.length === 0 && <div className="muted center">{T.noData}</div>}
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
              <dl className="dl mt-8">
                {s.reference_number && <div><dt>{T.referenceNumber}</dt><dd>{s.reference_number}</dd></div>}
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

      {session.notes && (
        <div className="card">
          <div className="card-header"><h3>{T.notes}</h3></div>
          <div className="card-body" style={{ whiteSpace: "pre-wrap" }}>{session.notes}</div>
        </div>
      )}

      {session.recordings.length > 0 && (
        <div className="card">
          <div className="card-header"><h3>{T.recordedFile}</h3></div>
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>{T.name}</th>
                  <th>{T.duration}</th>
                  <th>الحجم</th>
                  <th>SHA-256</th>
                  <th>{T.status}</th>
                  <th>{T.createdAt}</th>
                </tr>
              </thead>
              <tbody>
                {session.recordings.map((r) => (
                  <tr key={r.id}>
                    <td className="ltr">{r.original_filename}</td>
                    <td>{formatDuration(r.duration_seconds)}</td>
                    <td className="num">{formatBytes(r.size_bytes)}</td>
                    <td className="mono small">{r.sha256 ? `${r.sha256.slice(0, 16)}…` : T.none}</td>
                    <td><Badge kind={r.upload_status === "UPLOADED" ? "green" : r.upload_status === "PENDING" ? "amber" : "gray"}>{r.upload_status === "UPLOADED" ? "محفوظ مركزياً" : r.upload_status === "PENDING" ? "بانتظار الرفع" : "الرفع معطّل"}</Badge></td>
                    <td className="num">{formatDateTime(r.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </>
  );
}

function ActivityTab({ sessionId }: { sessionId: string }) {
  const [data, setData] = useState<Paged<AuditEntry> | null>(null);
  useEffect(() => {
    void http.get<Paged<AuditEntry>>(`/investigations/${sessionId}/activity?page_size=100`).then(setData);
  }, [sessionId]);
  if (!data) return <Loading />;
  return (
    <div className="card">
      <div className="card-header"><h3>{T.tabActivity}</h3></div>
      <div className="card-body">
        <div className="timeline" data-testid="activity">
          {data.items.length === 0 && <div className="muted center">{T.noData}</div>}
          {data.items.map((e) => (
            <div className="tl-item" key={e.id}>
              <div className="when num">{formatDateTime(e.created_at)}</div>
              <div>
                <div className="what">{AUDIT_ACTIONS[e.action] ?? e.action}</div>
                <div className="meta">
                  {e.username ?? T.none}
                  {e.safe_metadata && Object.keys(e.safe_metadata).length > 0 && (
                    <span className="ltr" style={{ marginInlineStart: 8 }}>{JSON.stringify(e.safe_metadata)}</span>
                  )}
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

export function InvestigationDetailPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const toast = useToast();
  const { can } = useAuth();
  const [params, setParams] = useSearchParams();
  const tab = (params.get("tab") as Tab) || "details";
  const [session, setSession] = useState<Investigation | null>(null);
  const [transcript, setTranscript] = useState<Transcript | null | undefined>(undefined);
  const [pending, setPending] = useState<PendingAudio | null>(null);
  const [processingBusy, setProcessingBusy] = useState(false);
  const agent = useAgentStatus();

  const loadTranscript = useCallback(async (hasTranscript: boolean) => {
    if (!id || !hasTranscript) {
      setTranscript(null);
      return;
    }
    try {
      setTranscript(await http.get<Transcript>(`/investigations/${id}/transcript`));
    } catch {
      setTranscript(null);
    }
  }, [id]);

  const load = useCallback(async () => {
    if (!id) return;
    try {
      const s = await http.get<Investigation>(`/investigations/${id}`);
      setSession(s);
      await loadTranscript(s.has_transcript);
    } catch (err) {
      toast.error(err instanceof ApiError ? errorMessage(err.code) : T.err_generic);
      navigate("/investigations");
    }
  }, [id, navigate, toast, loadTranscript]);

  useEffect(() => {
    void load();
  }, [load]);

  const setTab = (next: Tab) => setParams({ tab: next });

  const changeStatus = async (status: SessionStatus) => {
    if (!session) return;
    try {
      setSession(await http.put<Investigation>(`/investigations/${session.id}`, { status }));
      toast.success(T.sessionUpdated);
    } catch (err) {
      toast.error(err instanceof ApiError ? errorMessage(err.code) : T.err_generic);
    }
  };

  if (!session) return <Loading />;

  const onCompleted = () => {
    void load();
    setPending(null);
    toast.success(t("state_COMPLETED"));
  };

  return (
    <>
      <div className="page-header">
        <div>
          <h1>
            {session.title} <span className="muted mono" style={{ fontSize: 15 }}>{session.session_number}</span>
          </h1>
          <p>
            <SessionStatusBadge status={session.status} /> {session.location ? ` — ${session.location}` : ""} {session.session_date ? ` — ${formatDate(session.session_date)}` : ""}
          </p>
        </div>
        <div className="actions">
          {can("investigations.update") && (
            <Link className="btn" to={`/investigations/${session.id}/edit`}>
              <IconEdit /> {T.edit}
            </Link>
          )}
          {can("investigations.update") && session.status === "DRAFT" && (
            <button className="btn" onClick={() => void changeStatus("RECORDING")} type="button">{T.startRecording}</button>
          )}
          {can("investigations.archive") && session.status !== "ARCHIVED" && (
            <button className="btn" onClick={() => void changeStatus("ARCHIVED")} type="button">{T.archive}</button>
          )}
        </div>
      </div>

      <div className="tabs" role="tablist">
        {TABS.map((x) => (
          <button key={x.key} role="tab" aria-selected={tab === x.key} className={`tab ${tab === x.key ? "active" : ""}`} onClick={() => setTab(x.key)} type="button">
            {x.label}
          </button>
        ))}
      </div>

      {tab === "details" && <DetailsTab session={session} canViewDocuments={can("subjects.documents.view")} />}

      {tab === "recording" && (
        <div className="recorder">
          <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
            {!can("recordings.create") ? (
              <Alert kind="info">{T.err_forbidden}</Alert>
            ) : session.status === "ARCHIVED" ? (
              <Alert kind="warning">{T.err_session_archived}</Alert>
            ) : (
              <>
                <Recorder disabled={processingBusy} onReady={setPending} />
                <ProcessingPanel session={session} pending={pending} agent={agent} onCompleted={onCompleted} onBusyChange={setProcessingBusy} />
              </>
            )}
          </div>
          <AgentStatusPanel status={agent} />
        </div>
      )}

      {tab === "transcript" &&
        (transcript === undefined ? (
          <Loading />
        ) : transcript === null ? (
          <div className="card"><div className="card-body center muted">{T.noTranscript}</div></div>
        ) : (
          <TranscriptViewer transcript={transcript} onChange={setTranscript} />
        ))}

      {tab === "speakers" && (
        <SpeakersPanel
          sessionId={session.id}
          speakers={transcript?.speakers ?? []}
          onChange={(speakers) => transcript && setTranscript({ ...transcript, speakers })}
        />
      )}

      {tab === "activity" && <ActivityTab sessionId={session.id} />}
    </>
  );
}
