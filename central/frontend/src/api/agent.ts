/* Client for the Local AI Agent running on the investigator desktop (loopback only). */

import type { AgentCapabilities, AgentHealth, AgentJob } from "./types";

export const DEFAULT_AGENT_URL = "http://127.0.0.1:17117";
const AGENT_URL_KEY = "mstt.agent_url";

export function getAgentUrl(): string {
  try {
    return localStorage.getItem(AGENT_URL_KEY) || DEFAULT_AGENT_URL;
  } catch {
    return DEFAULT_AGENT_URL;
  }
}
export function setAgentUrl(url: string): void {
  try {
    localStorage.setItem(AGENT_URL_KEY, url);
  } catch {
    /* ignore */
  }
}

export class AgentError extends Error {
  code: string;
  status: number;
  constructor(status: number, code: string, message?: string) {
    super(message ?? code);
    this.status = status;
    this.code = code;
  }
}

async function agentFetch<T>(path: string, init: RequestInit = {}, timeoutMs = 8000): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  let res: Response;
  try {
    res = await fetch(`${getAgentUrl()}${path}`, { ...init, signal: controller.signal, mode: "cors" });
  } catch (e) {
    throw new AgentError(0, "agent_unavailable", e instanceof Error ? e.message : undefined);
  } finally {
    clearTimeout(timer);
  }
  if (!res.ok) {
    let code = "agent_processing";
    let message: string | undefined;
    try {
      const data = await res.json();
      if (typeof data?.detail === "string") code = data.detail;
      else if (data?.detail?.code) {
        code = data.detail.code;
        message = data.detail.message;
      }
    } catch {
      /* ignore */
    }
    throw new AgentError(res.status, code, message);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const agentApi = {
  health: () => agentFetch<AgentHealth>("/health", {}, 4000),
  capabilities: () => agentFetch<AgentCapabilities>("/capabilities", {}, 6000),
  modelStatus: () => agentFetch<AgentCapabilities>("/model-status", {}, 6000),
  warmup: () => agentFetch<{ accepted: boolean }>("/models/load", { method: "POST" }, 6000),
  submitJob: (token: string, file: Blob, filename: string, onProgress?: (p: number) => void) =>
    new Promise<AgentJob>((resolve, reject) => {
      const form = new FormData();
      form.append("processing_token", token);
      form.append("file", file, filename);
      const xhr = new XMLHttpRequest();
      xhr.open("POST", `${getAgentUrl()}/jobs`);
      xhr.timeout = 10 * 60 * 1000;
      xhr.upload.onprogress = (ev) => {
        if (ev.lengthComputable && onProgress) onProgress(ev.loaded / ev.total);
      };
      xhr.onload = () => {
        if (xhr.status >= 200 && xhr.status < 300) {
          resolve(JSON.parse(xhr.responseText) as AgentJob);
        } else {
          let code = "agent_processing";
          let message: string | undefined;
          try {
            const data = JSON.parse(xhr.responseText);
            if (typeof data?.detail === "string") code = data.detail;
            else if (data?.detail?.code) {
              code = data.detail.code;
              message = data.detail.message;
            }
          } catch {
            /* ignore */
          }
          reject(new AgentError(xhr.status, code, message));
        }
      };
      xhr.onerror = () => reject(new AgentError(0, "agent_unavailable"));
      xhr.ontimeout = () => reject(new AgentError(0, "agent_unavailable"));
      xhr.send(form);
    }),
  job: (jobId: string) => agentFetch<AgentJob>(`/jobs/${jobId}`, {}, 6000),
  cancel: (jobId: string) => agentFetch<AgentJob>(`/jobs/${jobId}/cancel`, { method: "POST" }, 6000),
  jobs: () => agentFetch<AgentJob[]>("/jobs", {}, 6000),
};
