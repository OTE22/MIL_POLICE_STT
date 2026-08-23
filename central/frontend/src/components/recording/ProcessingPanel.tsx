import { useEffect, useRef, useState } from "react";

import { AgentError, agentApi } from "@/api/agent";
import { ApiError, http } from "@/api/client";
import type { AgentJob, AgentState, Investigation, Job, ProcessingToken } from "@/api/types";
import { formatDateTime } from "@/lib/format";
import { T, errorMessage, t } from "@/lib/i18n";
import { Alert, JobStatusBadge, useToast } from "@/components/ui";
import { IconWave, IconX } from "@/components/Icons";
import type { AgentStatusState } from "./AgentStatus";
import type { PendingAudio } from "./Recorder";

const STEPS: AgentState[] = ["CREATED", "RECEIVING_AUDIO", "PREPROCESSING", "DIARIZING", "TRANSCRIBING", "FINALIZING", "SYNCING", "COMPLETED"];

function stepClass(step: AgentState, job: AgentJob | null, uploading: boolean): string {
  if (!job) return uploading && step === "RECEIVING_AUDIO" ? "active" : uploading && step === "CREATED" ? "done" : "";
  const cur = STEPS.indexOf(job.state);
  const idx = STEPS.indexOf(step);
  if (job.state === "FAILED" || job.state === "CANCELLED") {
    const failedAt = STEPS.indexOf((job.failure_stage as AgentState) || "CREATED");
    if (idx < failedAt) return "done";
    if (idx === failedAt) return "failed";
    return "";
  }
  if (idx < cur) return "done";
  if (idx === cur) return job.state === "COMPLETED" ? "done" : "active";
  return "";
}

export function ProcessingPanel({
  session,
  pending,
  agent,
  onCompleted,
  onBusyChange,
}: {
  session: Investigation;
  pending: PendingAudio | null;
  agent: AgentStatusState;
  onCompleted: () => void;
  onBusyChange: (busy: boolean) => void;
}) {
  const toast = useToast();
  const [job, setJob] = useState<AgentJob | null>(null);
  const [centralJob, setCentralJob] = useState<Job | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadPct, setUploadPct] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [history, setHistory] = useState<Job[]>([]);
  const pollRef = useRef<number | null>(null);
  const completedNotified = useRef(false);

  const loadHistory = () => void http.get<Job[]>(`/investigations/${session.id}/jobs`).then(setHistory).catch(() => undefined);
  useEffect(loadHistory, [session.id]);

  // Resume polling of an in-flight agent job for this session after a page reload.
  useEffect(() => {
    if (agent.availability !== "available" || job) return;
    void agentApi
      .jobs()
      .then((jobs) => {
        const mine = jobs.find((j) => j.session_id === session.id && !["COMPLETED", "FAILED", "CANCELLED"].includes(j.state));
        if (mine) setJob(mine);
      })
      .catch(() => undefined);
  }, [agent.availability, session.id, job]);

  useEffect(() => {
    if (!job || ["COMPLETED", "FAILED", "CANCELLED"].includes(job.state) && job.sync_state !== "SYNCING" && job.sync_state !== "WAITING_TO_SYNC") {
      if (pollRef.current) window.clearInterval(pollRef.current);
      pollRef.current = null;
      if (job?.state === "COMPLETED" && job.sync_state === "SYNCED" && !completedNotified.current) {
        completedNotified.current = true;
        onBusyChange(false);
        loadHistory();
        onCompleted();
      }
      if (job && (job.state === "FAILED" || job.state === "CANCELLED")) {
        onBusyChange(false);
        loadHistory();
      }
      return;
    }
    pollRef.current = window.setInterval(() => {
      void agentApi
        .job(job.job_id)
        .then((j) => {
          setJob(j);
          if (j.job_id) void http.get<Job>(`/local-processing/${j.job_id}`).then(setCentralJob).catch(() => undefined);
        })
        .catch(() => undefined);
    }, 2000);
    return () => {
      if (pollRef.current) window.clearInterval(pollRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [job?.job_id, job?.state, job?.sync_state]);

  const startProcessing = async () => {
    if (!pending) return;
    setError(null);
    completedNotified.current = false;
    onBusyChange(true);
    let token: ProcessingToken;
    try {
      token = await http.post<ProcessingToken>(`/investigations/${session.id}/local-processing-token`, {
        original_filename: pending.filename,
        mime_type: pending.mimeType,
        size_bytes: pending.blob.size,
        source: pending.source,
      });
    } catch (err) {
      setError(err instanceof ApiError ? errorMessage(err.code) : T.err_generic);
      onBusyChange(false);
      return;
    }
    if (token.speaker_limit_warning) toast.warning(T.speakerLimitWarning);
    setUploading(true);
    setUploadPct(0);
    try {
      const created = await agentApi.submitJob(token.processing_token, pending.blob, pending.filename, setUploadPct);
      setJob(created);
      toast.success(T.processingStarted);
    } catch (err) {
      const code = err instanceof AgentError ? err.code : "agent_unavailable";
      const detail = err instanceof AgentError && err.message && err.message !== err.code ? ` (${err.message})` : "";
      setError(`${errorMessage(code)}${detail}`);
      onBusyChange(false);
      // Tell the central server the job never started so the session does not stay "processing".
      void http.post(`/local-processing/${token.job_id}/cancel`).catch(() => undefined).finally(loadHistory);
    } finally {
      setUploading(false);
    }
  };

  const cancel = async () => {
    if (!job) return;
    try {
      const j = await agentApi.cancel(job.job_id);
      setJob(j);
    } catch {
      toast.error(T.err_generic);
    }
  };

  const canStart = !!pending && agent.availability === "available" && !!agent.caps?.ready && !agent.caps?.busy && !uploading && (!job || ["COMPLETED", "FAILED", "CANCELLED"].includes(job.state));
  const progress = uploading ? uploadPct * 0.1 : job ? Math.max(job.progress, 0.1) : 0;
  const stateLabel = uploading ? t("state_RECEIVING_AUDIO") : job ? (job.state === "COMPLETED" && job.sync_state !== "SYNCED" ? t(`state_${job.sync_state}`, t("state_SYNCING")) : t(`state_${job.state}`)) : "";

  return (
    <div className="card">
      <div className="card-header">
        <h3>{T.processingProgress}</h3>
        {job && !["COMPLETED", "FAILED", "CANCELLED"].includes(job.state) && (
          <button className="btn btn-sm" onClick={() => void cancel()} type="button">
            <IconX /> {T.cancelJob}
          </button>
        )}
      </div>
      <div className="card-body">
        {error && (
          <div className="mb-16">
            <Alert kind="danger">
              {error}
              <div className="small mt-8">{T.err_no_fallback}</div>
            </Alert>
          </div>
        )}
        {!job && !uploading && (
          <button className="btn btn-primary btn-lg btn-block" onClick={() => void startProcessing()} disabled={!canStart} type="button">
            <IconWave /> {T.processRecording}
          </button>
        )}
        {(job || uploading) && (
          <>
            <div className="flex between mb-16">
              <strong>{stateLabel}</strong>
              <span className="num muted">{Math.round(progress * 100)}%</span>
            </div>
            <div className="progress">
              <span style={{ width: `${Math.round(progress * 100)}%` }} />
            </div>
            <div className="steps">
              {STEPS.map((s) => (
                <div key={s} className={`step ${stepClass(s, job, uploading)}`}>
                  <span className="dot" /> {t(`state_${s}`)}
                </div>
              ))}
            </div>
            {job?.message && <div className="muted small mt-8">{job.message}</div>}
            {job?.state === "FAILED" && (
              <div className="mt-16">
                <Alert kind="danger">
                  {errorMessage(job.error_code ?? "agent_processing")}
                  {job.error_message && <div className="small mt-8 ltr">{job.error_message}</div>}
                  <div className="small mt-8">{T.err_no_fallback}</div>
                </Alert>
              </div>
            )}
            {job?.state === "COMPLETED" && job.sync_state === "SYNC_FAILED" && (
              <div className="mt-16">
                <Alert kind="warning">
                  {T.err_agent_sync}
                  {job.last_sync_error && <div className="small mt-8 ltr">{job.last_sync_error}</div>}
                </Alert>
              </div>
            )}
            {job?.state === "COMPLETED" && job.sync_state === "SYNCED" && (
              <div className="mt-16">
                <Alert kind="success">
                  {t("state_COMPLETED")} — {T.speakerCount}: <span className="num">{job.speaker_count ?? "?"}</span>، {T.segments}: <span className="num">{job.segment_count ?? "?"}</span>
                </Alert>
              </div>
            )}
            {job && (job.state === "COMPLETED" || job.state === "FAILED" || job.state === "CANCELLED") && (
              <button className="btn mt-16" type="button" onClick={() => setJob(null)}>
                {T.processRecording}
              </button>
            )}
            {centralJob && <div className="small muted mt-8">{T.status}: <JobStatusBadge status={centralJob.status} /></div>}
          </>
        )}

        {history.length > 0 && (
          <div className="mt-24">
            <h4 className="muted small mb-16">{T.jobHistory}</h4>
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>{T.time}</th>
                    <th>{T.status}</th>
                    <th>{T.agentId}</th>
                  </tr>
                </thead>
                <tbody>
                  {history.map((h) => (
                    <tr key={h.id}>
                      <td className="num">{formatDateTime(h.created_at)}</td>
                      <td>
                        <JobStatusBadge status={h.status} />
                        {h.error_message && <div className="small muted ltr">{h.error_message}</div>}
                      </td>
                      <td className="ltr small">{h.workstation_agent_id ?? T.none}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
