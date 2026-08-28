import { useCallback, useEffect, useRef, useState } from "react";

import { agentApi, getAgentUrl } from "@/api/agent";
import { http } from "@/api/client";
import type { AgentCapabilities, AgentModelStatus } from "@/api/types";
import { useAuth } from "@/lib/auth";
import { T } from "@/lib/i18n";
import { Alert, Badge, useToast } from "@/components/ui";
import { IconRefresh } from "@/components/Icons";

export type AgentAvailability = "checking" | "unavailable" | "available";

export interface AgentStatusState {
  availability: AgentAvailability;
  caps: AgentCapabilities | null;
  refresh: () => Promise<void>;
  lastError: string | null;
}

export function useAgentStatus(pollMs = 10000): AgentStatusState {
  const [availability, setAvailability] = useState<AgentAvailability>("checking");
  const [caps, setCaps] = useState<AgentCapabilities | null>(null);
  const [lastError, setLastError] = useState<string | null>(null);
  const timer = useRef<number | null>(null);

  const refresh = useCallback(async () => {
    try {
      const c = await agentApi.capabilities();
      setCaps(c);
      setAvailability("available");
      setLastError(null);
    } catch (e) {
      setAvailability("unavailable");
      setCaps(null);
      setLastError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    void refresh();
    timer.current = window.setInterval(() => void refresh(), pollMs);
    return () => {
      if (timer.current) window.clearInterval(timer.current);
    };
  }, [refresh, pollMs]);

  return { availability, caps, refresh, lastError };
}

/* One distinct message per state: "installed but not loaded" is normal lazy loading
   (spec §42) and must not be reported as a failure. */
function modelBadge(m: AgentModelStatus | undefined) {
  if (!m) return <Badge kind="gray">{T.unknown}</Badge>;
  switch (m.state) {
    case "READY":
      return <Badge kind="green">{T.ready}</Badge>;
    case "LOADING":
      return <Badge kind="blue">{T.modelLoading}</Badge>;
    case "PROVISIONED":
      return <Badge kind="amber">{T.modelNotLoaded}</Badge>;
    case "NOT_PROVISIONED":
      return <Badge kind="red">{T.modelNotInstalled}</Badge>;
    case "ERROR":
    default:
      return <Badge kind="red">{T.modelLoadFailed}</Badge>;
  }
}

/** Highest-severity truthful condition across both models: ERROR/NOT_PROVISIONED > LOADING > PROVISIONED > READY. */
function overallModelIssue(caps: AgentCapabilities | null): "blocked" | "loading" | "not_loaded" | "ready" | null {
  if (!caps) return null;
  const states = [caps.stt.state, caps.diarization.state];
  if (states.some((s) => s === "ERROR" || s === "NOT_PROVISIONED")) return "blocked";
  if (caps.loading || states.some((s) => s === "LOADING")) return "loading";
  if (states.some((s) => s === "PROVISIONED")) return "not_loaded";
  return "ready";
}

/** Per-model line inside the blocking alert, naming the real cause. */
function blockedReason(label: string, m: AgentModelStatus, unavailableMsg: string): string | null {
  if (m.state === "NOT_PROVISIONED") return `${label}: ${T.modelNotInstalled} — ${T.modelNotInstalledHint}`;
  if (m.state === "ERROR") return `${label}: ${unavailableMsg}${m.error ? ` (${m.error})` : ""}`;
  return null;
}

export function AgentStatusPanel({ status }: { status: AgentStatusState }) {
  const { availability, caps, refresh } = status;
  const { can } = useAuth();
  const toast = useToast();
  const [registering, setRegistering] = useState(false);
  const [warming, setWarming] = useState(false);

  const register = async () => {
    if (!caps) return;
    setRegistering(true);
    try {
      await http.post("/workstations/register", {
        agent_id: caps.agent_id,
        device_name: caps.device_name,
        agent_version: caps.agent_version,
        stt_provider: caps.stt.provider,
        stt_model: caps.stt.model,
        stt_model_revision: caps.stt.revision,
        diarization_provider: caps.diarization.provider,
        diarization_model: caps.diarization.model,
        diarization_model_revision: caps.diarization.revision,
        processing_device: caps.processing_device,
        gpu_name: caps.gpu_name,
        stt_ready: caps.stt.state === "READY",
        diarization_ready: caps.diarization.state === "READY",
      });
      toast.success(T.workstationRegistered);
    } catch {
      toast.error(T.err_generic);
    } finally {
      setRegistering(false);
    }
  };

  const warmup = async () => {
    setWarming(true);
    try {
      await agentApi.warmup();
      toast.push(T.modelLoading);
      setTimeout(() => void refresh(), 1500);
    } catch {
      toast.error(T.err_agent_unavailable);
    } finally {
      setWarming(false);
    }
  };

  const issue = overallModelIssue(caps);
  const overall =
    availability === "checking" ? (
      <Badge kind="gray">{T.loading}</Badge>
    ) : availability === "unavailable" ? (
      <Badge kind="red">{T.serviceUnavailable}</Badge>
    ) : caps?.ready ? (
      <Badge kind="green">{T.ready}</Badge>
    ) : issue === "blocked" ? (
      <Badge kind="red">{T.modelNotReady}</Badge>
    ) : issue === "loading" ? (
      <Badge kind="blue">{T.modelLoading}</Badge>
    ) : (
      <Badge kind="amber">{T.modelNotLoaded}</Badge>
    );

  return (
    <div className="card">
      <div className="card-header">
        <h3>{T.localAiStatus}</h3>
        <div className="flex">
          {overall}
          <button className="icon-btn" onClick={() => void refresh()} title={T.refresh} type="button">
            <IconRefresh />
          </button>
        </div>
      </div>
      <div className="card-body">
        <div className="status-list">
          <div className="status-row">
            <span className="k">{T.serviceStatus}</span>
            <span>{availability === "available" ? T.ready : availability === "checking" ? T.loading : T.serviceUnavailable}</span>
          </div>
          <div className="status-row">
            <span className="k">{T.sttModelStatus}</span>
            <span>{modelBadge(caps?.stt)}</span>
          </div>
          <div className="status-row">
            <span className="k">{T.diarModelStatus}</span>
            <span>{modelBadge(caps?.diarization)}</span>
          </div>
          <div className="status-row">
            {/* Without this row a stale agent is indistinguishable from a recording that
                simply had no usable speech: both end as "no voice print for this speaker".
                modelBadge renders an absent model as غير معروف, which is the honest answer
                for an agent that does not know the capability exists. */}
            <span className="k">{T.speakerIdModelStatus}</span>
            <span>{modelBadge(caps?.speaker_id)}</span>
          </div>
          <div className="status-row">
            <span className="k">{T.device}</span>
            <span className="ltr">
              {caps ? (caps.processing_device === "cuda" ? `GPU — ${caps.gpu_name ?? "CUDA"}` : "CPU") : T.notAvailable}
            </span>
          </div>
          <div className="status-row">
            <span className="k">{T.serviceVersion}</span>
            <span className="ltr">{caps?.agent_version ?? T.notAvailable}</span>
          </div>
          <div className="status-row">
            <span className="k">{T.deviceName}</span>
            <span className="ltr">{caps?.device_name ?? T.notAvailable}</span>
          </div>
        </div>
        {caps && caps.processing_device === "cpu" && (
          <div className="mt-16">
            <Alert kind="warning">{T.cpuWarning}</Alert>
          </div>
        )}
        {availability === "unavailable" && (
          <div className="mt-16">
            <Alert kind="danger">
              {T.err_agent_unavailable}
              <div className="small mt-8 ltr">{getAgentUrl()}</div>
              <div className="small mt-8">{T.browserPermissionHint}</div>
            </Alert>
          </div>
        )}
        {/* Exactly one alert, for the highest-severity truthful condition. */}
        {issue === "blocked" && (
          <div className="mt-16">
            <Alert kind="danger">
              {blockedReason(T.sttModelStatus, caps!.stt, T.err_agent_stt_unavailable) && (
                <div>{blockedReason(T.sttModelStatus, caps!.stt, T.err_agent_stt_unavailable)}</div>
              )}
              {blockedReason(T.diarModelStatus, caps!.diarization, T.err_agent_diar_unavailable) && (
                <div>{blockedReason(T.diarModelStatus, caps!.diarization, T.err_agent_diar_unavailable)}</div>
              )}
              <div className="small mt-8">{T.err_no_fallback}</div>
            </Alert>
          </div>
        )}
        {issue === "loading" && (
          <div className="mt-16">
            <Alert kind="info">{T.modelsLoadingNotice}</Alert>
          </div>
        )}
        {issue === "not_loaded" && (
          <div className="mt-16">
            <Alert kind="warning">{T.modelsNotLoadedNotice}</Alert>
          </div>
        )}
        <div className="flex wrap mt-16">
          {caps && caps.loadable && !caps.ready && (
            <button
              className="btn btn-sm"
              onClick={() => void warmup()}
              disabled={warming || caps.loading || issue === "loading"}
              type="button"
              data-testid="load-models"
            >
              {issue === "loading" ? T.modelLoading : T.modelsLoadAction}
            </button>
          )}
          {caps && can("workstations.register") && (
            <button className="btn btn-sm" onClick={() => void register()} disabled={registering} type="button">
              {T.registerWorkstation}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
