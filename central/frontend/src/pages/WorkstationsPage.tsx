import { useEffect, useState } from "react";

import { http } from "@/api/client";
import type { Workstation } from "@/api/types";
import { formatDateTime } from "@/lib/format";
import { T, t } from "@/lib/i18n";
import { AgentStatusPanel, useAgentStatus } from "@/components/recording/AgentStatus";
import { Badge, Loading } from "@/components/ui";
import { IconRefresh } from "@/components/Icons";

export function WorkstationsPage() {
  const [rows, setRows] = useState<Workstation[] | null>(null);
  const agent = useAgentStatus();
  const load = () => void http.get<Workstation[]>("/workstations").then(setRows);
  useEffect(load, []);

  return (
    <>
      <div className="page-header">
        <h1>{T.workstations}</h1>
        <button className="btn" onClick={load} type="button">
          <IconRefresh /> {T.refresh}
        </button>
      </div>
      <div className="recorder">
        <div className="card">
          {!rows ? (
            <Loading />
          ) : (
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>{T.deviceName}</th>
                    <th>{T.agentId}</th>
                    <th>{T.serviceVersion}</th>
                    <th>{T.sttModel}</th>
                    <th>{T.diarModel}</th>
                    <th>{T.device}</th>
                    <th>{T.status}</th>
                    <th>{T.lastSeen}</th>
                    <th>{T.registeredBy}</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.length === 0 && <tr><td colSpan={9} className="empty">{T.noData}</td></tr>}
                  {rows.map((w) => (
                    <tr key={w.id}>
                      <td className="ltr">{w.device_name ?? T.none}</td>
                      <td className="ltr small">{w.agent_id}</td>
                      <td className="ltr">{w.agent_version ?? T.none}</td>
                      <td className="ltr small">{w.stt_model ?? T.none}<br /><span className="muted">{w.stt_model_revision?.slice(0, 12) ?? ""}</span></td>
                      <td className="ltr small">{w.diarization_model ?? T.none}<br /><span className="muted">{w.diarization_model_revision?.slice(0, 12) ?? ""}</span></td>
                      <td className="ltr">{w.processing_device === "cuda" ? `GPU — ${w.gpu_name ?? ""}` : w.processing_device?.toUpperCase() ?? T.none}</td>
                      <td><Badge kind={w.status === "ONLINE" ? "green" : w.status === "DEGRADED" ? "amber" : "gray"}>{t(`ws_${w.status}`)}</Badge></td>
                      <td className="num">{formatDateTime(w.last_seen_at)}</td>
                      <td>{w.registered_by_name ?? T.none}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
        <AgentStatusPanel status={agent} />
      </div>
    </>
  );
}
