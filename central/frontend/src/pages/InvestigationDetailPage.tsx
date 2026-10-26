import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";

import { ApiError, http } from "@/api/client";
import type { AuditEntry, Investigation, Paged, Transcript } from "@/api/types";
import { useAuth } from "@/lib/auth";
import { formatDate } from "@/lib/format";
import { T, errorMessage, t } from "@/lib/i18n";
import { Alert, Loading, SessionStatusBadge, useToast } from "@/components/ui";
import { IconEdit, IconFile, IconMic, IconUsers, IconClock, IconFolder, IconChevronLeft } from "@/components/Icons";
import { InvestigationWorkflow } from "@/components/InvestigationWorkflow";
import { AgentStatusPanel, useAgentStatus } from "@/components/recording/AgentStatus";
import { Recorder, type PendingAudio } from "@/components/recording/Recorder";
import { ProcessingPanel } from "@/components/recording/ProcessingPanel";
import { TranscriptViewer } from "@/components/transcript/TranscriptViewer";
import { ActivityTimeline } from "@/components/audit/ActivityTimeline";
import { SpeakersPanel } from "@/components/transcript/SpeakersPanel";
import { InvestigationDetails } from "@/components/InvestigationDetails";
import { InvestigationGuide } from "@/components/InvestigationGuide";
import { IntakeReadiness } from "@/components/IntakeReadiness";
import "@/styles/investigation-workspace.css";

type Tab = "details" | "recording" | "transcript" | "speakers" | "activity";
const TABS: { key: Tab; label: string }[] = [
  { key: "details", label: T.tabDetails },
  { key: "recording", label: T.tabRecording },
  { key: "transcript", label: T.tabTranscript },
  { key: "speakers", label: T.tabSpeakers },
  { key: "activity", label: T.tabActivity },
];
const TAB_ICONS = { details: IconFolder, recording: IconMic, transcript: IconFile, speakers: IconUsers, activity: IconClock };

function ActivityTab({ sessionId }: { sessionId: string }) {
  const [data, setData] = useState<Paged<AuditEntry> | null>(null);
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let cancelled = false;
    setFailed(false);
    setData(null);
    void http.get<Paged<AuditEntry>>(`/investigations/${sessionId}/activity?page_size=100`)
      .then(result => { if (!cancelled) setData(result); })
      .catch(() => { if (!cancelled) setFailed(true); });
    return () => { cancelled = true; };
  }, [sessionId, attempt]);
  if (failed) return <Alert kind="danger"><p>تعذّر تحميل سجل النشاط.</p><button className="btn btn-sm mt-8" type="button" onClick={() => setAttempt(value => value + 1)}>إعادة المحاولة</button></Alert>;
  if (!data) return <Loading />;
  return (
    <div className="card activity-workspace">
      <div className="card-header"><div><h3>{T.tabActivity}</h3><p className="workspace-section-hint">تتبّع التعديلات وعمليات المعالجة المرتبطة بهذه الجلسة.</p></div><span className="workspace-section-count">{data.total}</span></div>
      <div className="card-body">
        {/* withinSession: the session id is on every record here and carries no information. */}
        <ActivityTimeline entries={data.items} withinSession />
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
  const requestedTab = params.get("tab");
  const tab: Tab = TABS.find(item => item.key === requestedTab)?.key ?? "details";
  const [session, setSession] = useState<Investigation | null>(null);
  const [transcript, setTranscript] = useState<Transcript | null | undefined>(undefined);
  const [pending, setPending] = useState<PendingAudio | null>(null);
  const [processingBusy, setProcessingBusy] = useState(false);
  const agent = useAgentStatus();

  useEffect(() => {
    document.getElementById(`investigation-tab-${tab}`)?.scrollIntoView({ block: "nearest", inline: "nearest" });
  }, [tab, session?.id]);

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
  }, [load, tab]);

  const setTab = (next: Tab) => setParams({ tab: next });

  if (!session) return <Loading />;


  const onCompleted = () => {
    void load();
    setPending(null);
    toast.success(t("state_COMPLETED"));
  };

  return (
    <>
      <div className="page-header investigation-context">
        <div>
          <span className="investigation-context-label">ملف جلسة التحقيق</span>
          <h1>
            {session.title}
          </h1>
          <div className="investigation-context-meta">
            <span className="mono">{session.session_number}</span>
            <SessionStatusBadge status={session.status} />
            {session.location && <span>{session.location}</span>}
            {session.session_date && <span>{formatDate(session.session_date)}</span>}
          </div>
        </div>
        <div className="actions">
          {can("investigations.update") && (
            <Link className="btn" to={`/investigations/${session.id}/edit`}>
              <IconEdit /> {T.edit}
            </Link>
          )}
          {/* HTML statements can also be filled manually before a recording exists. */}
          {can("reports.generate") && (
            <Link
              className="btn"
              to={`/investigations/${session.id}/report`}
              data-testid="open-report-composer"
            >
              {T.reportCreate}
            </Link>
          )}
        </div>
      </div>

      <InvestigationWorkflow session={session} onChange={setSession} />
      <div className="tabs investigation-navigation" role="tablist" aria-label="أقسام جلسة التحقيق">
        {TABS.map((x, index) => {
          const Icon = TAB_ICONS[x.key];
          return <button key={x.key} id={`investigation-tab-${x.key}`} role="tab" aria-selected={tab === x.key}
            aria-controls="investigation-tab-content" tabIndex={tab === x.key ? 0 : -1}
            className={`tab ${tab === x.key ? "active" : ""}`} onClick={() => setTab(x.key)} type="button"
            onKeyDown={event => {
              const offset = event.key === "ArrowLeft" ? 1 : event.key === "ArrowRight" ? -1 : 0;
              const next = event.key === "Home" ? 0 : event.key === "End" ? TABS.length - 1 : (index + offset + TABS.length) % TABS.length;
              if (!offset && event.key !== "Home" && event.key !== "End") return;
              event.preventDefault();
              setTab(TABS[next].key);
              document.getElementById(`investigation-tab-${TABS[next].key}`)?.focus();
            }}>
            <Icon />{x.label}
            {x.key === "speakers" && Boolean(transcript?.speakers.length) && <span className="investigation-tab-count">{transcript?.speakers.length}</span>}
          </button>
        })}
      </div>

      <div id="investigation-tab-content" role="tabpanel" aria-labelledby={`investigation-tab-${tab}`}>
      <IntakeReadiness session={session} />
      {tab === "details" && <><InvestigationGuide session={session} transcript={transcript} /><InvestigationDetails session={session} canViewDocuments={can("subjects.documents.view")} /></>}

      {tab === "recording" && (
        <section className="recording-workspace" data-testid="recording-workspace">
          <div className="workspace-heading"><div><span className="workspace-eyebrow">التسجيل والمعالجة</span><h2>من الصوت إلى نص قابل للمراجعة</h2><p>أضف التسجيل، تحقّق من جاهزية المعالجة، ثم راجع النص الناتج.</p></div>
            {session.has_transcript && <Link className="btn" to="?tab=transcript"><IconFile />مراجعة النص<IconChevronLeft /></Link>}
          </div>
          <div className="recording-stage-guide" aria-label="خطوات معالجة التسجيل">
            <div className={!pending && !processingBusy ? "is-current" : ""}><span className="workflow-number">١</span><section><strong>أضف التسجيل</strong><p>ملف محفوظ أو تسجيل مباشر</p></section></div>
            <div className={pending || processingBusy ? "is-current" : ""}><span className="workflow-number">٢</span><section><strong>ابدأ المعالجة</strong><p>تفريغ الكلام وفصل المتحدثين</p></section></div>
            <div><span className="workflow-number">٣</span><section><strong>راجع النتائج</strong><p>النص المفرغ وهويات المتحدثين</p></section></div>
          </div>
        <div className="recorder">
          <div className="recording-main">
            {!can("recordings.create") ? (
              <Alert kind="info">{T.err_forbidden}</Alert>
            ) : ["CLOSED", "ARCHIVED"].includes(session.workflow_state) ? (
              <Alert kind="warning">{T.err_session_archived}</Alert>
            ) : (
              <>
                <Recorder disabled={processingBusy || session.intake_readiness?.ready === false} pending={pending} onReady={setPending} />
                <ProcessingPanel session={session} pending={pending} agent={agent} onCompleted={onCompleted} onBusyChange={setProcessingBusy}
                  onAuthorized={(audio, recordingId) => setPending(current => current?.blob === audio.blob ? { ...current, recordingId, sessionId: session.id } : current)} />
              </>
            )}
          </div>
          <AgentStatusPanel status={agent} />
        </div>
        </section>
      )}

      {tab === "transcript" &&
        (transcript === undefined ? (
          <Loading />
        ) : transcript === null ? (
          session.has_transcript ? <Alert kind="danger"><p>تعذّر تحميل النص المفرغ.</p><button className="btn btn-sm mt-8" type="button" onClick={() => void loadTranscript(true)}>إعادة المحاولة</button></Alert> :
          <div className="card workspace-empty"><IconFile /><h3>النص المفرغ غير متاح بعد</h3><p>أضف تسجيلاً وأكمل معالجته لعرض النص ومراجعته هنا.</p><Link className="btn btn-primary" to="?tab=recording">الانتقال إلى التسجيل<IconChevronLeft /></Link></div>
        ) : (
          <TranscriptViewer transcript={transcript} onChange={setTranscript} />
        ))}

      {tab === "speakers" && (transcript === undefined ? <Loading /> : transcript === null && session.has_transcript ? (
        <Alert kind="danger"><p>تعذّر تحميل بيانات المتحدثين.</p><button className="btn btn-sm mt-8" type="button" onClick={() => void loadTranscript(true)}>إعادة المحاولة</button></Alert>
      ) : (
        <SpeakersPanel
          sessionId={session.id}
          speakers={transcript?.speakers ?? []}
          onChange={(speakers) => transcript && setTranscript({ ...transcript, speakers })}
          // A re-scan rewrites suggestions server-side, so refetch rather than patch state.
          onReload={() => void loadTranscript(true)}
        />
      ))}

      {tab === "activity" && <ActivityTab sessionId={session.id} />}
      </div>
    </>
  );
}
