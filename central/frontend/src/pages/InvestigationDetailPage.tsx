import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";

import { ApiError, http } from "@/api/client";
import type { AuditEntry, Investigation, Paged, SessionStatus, Transcript } from "@/api/types";
import { useAuth } from "@/lib/auth";
import { formatBytes, formatDate, formatDateTime, formatDuration, formatTime } from "@/lib/format";
import { AUDIT_ACTIONS, T, errorMessage, t } from "@/lib/i18n";
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

function DetailsTab({ session }: { session: Investigation }) {
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
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>{T.subjectName}</th>
                <th>{T.referenceNumber}</th>
                <th>{T.militaryId}</th>
                <th>{T.rank}</th>
                <th>{T.unit}</th>
                <th>{T.department}</th>
                <th>{T.notes}</th>
              </tr>
            </thead>
            <tbody>
              {session.subjects.length === 0 && <tr><td colSpan={7} className="empty">{T.noData}</td></tr>}
              {session.subjects.map((s, i) => (
                <tr key={s.id ?? i}>
                  <td>{s.subject_name ?? T.none}</td>
                  <td>{s.reference_number ?? T.none}</td>
                  <td className="ltr">{s.military_id ?? T.none}</td>
                  <td>{s.rank ?? T.none}</td>
                  <td>{s.unit ?? T.none}</td>
                  <td>{s.department ?? T.none}</td>
                  <td>{s.notes ?? T.none}</td>
                </tr>
              ))}
            </tbody>
          </table>
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

      {tab === "details" && <DetailsTab session={session} />}

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
