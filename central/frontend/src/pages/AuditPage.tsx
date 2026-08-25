import { useEffect, useState } from "react";

import { http, qs } from "@/api/client";
import type { AuditEntry, Paged } from "@/api/types";
import { formatDateTime } from "@/lib/format";
import { AuditCell } from "@/components/audit/ActivityTimeline";
import { AUDIT_ACTIONS, T } from "@/lib/i18n";
import { Loading, Pagination } from "@/components/ui";

export function AuditPage() {
  const [action, setAction] = useState("");
  const [entityType, setEntityType] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [page, setPage] = useState(1);
  const [data, setData] = useState<Paged<AuditEntry> | null>(null);

  useEffect(() => {
    void http
      .get<Paged<AuditEntry>>(`/audit-logs${qs({ action, entity_type: entityType, date_from: dateFrom, date_to: dateTo, page, page_size: 50 })}`)
      .then(setData);
  }, [action, entityType, dateFrom, dateTo, page]);

  return (
    <>
      <div className="page-header">
        <h1>{T.audit}</h1>
      </div>
      <div className="card">
        <div className="toolbar">
          <select className="select" value={action} onChange={(e) => { setAction(e.target.value); setPage(1); }}>
            <option value="">{T.action}: {T.all}</option>
            {Object.entries(AUDIT_ACTIONS).map(([k, v]) => (
              <option key={k} value={k}>{v}</option>
            ))}
          </select>
          <select className="select" value={entityType} onChange={(e) => { setEntityType(e.target.value); setPage(1); }}>
            <option value="">{T.entity}: {T.all}</option>
            <option value="user">المستخدم</option>
            <option value="investigation_session">الجلسة</option>
            <option value="audio_recording">التسجيل</option>
            <option value="local_processing_job">مهمة المعالجة</option>
            <option value="transcript">النص المفرغ</option>
            <option value="transcript_segment">مقطع النص</option>
            <option value="session_speaker">المتحدث</option>
            <option value="workstation">محطة العمل</option>
          </select>
          <input className="input" type="date" value={dateFrom} onChange={(e) => { setDateFrom(e.target.value); setPage(1); }} />
          <input className="input" type="date" value={dateTo} onChange={(e) => { setDateTo(e.target.value); setPage(1); }} />
        </div>
        {!data ? (
          <Loading />
        ) : (
          <>
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>{T.time}</th>
                    <th>{T.user}</th>
                    <th>{T.action}</th>
                    <th>{T.entity}</th>
                    <th>{T.auditDetails}</th>
                    <th>{T.ipAddress}</th>
                  </tr>
                </thead>
                <tbody>
                  {data.items.length === 0 && <tr><td colSpan={6} className="empty">{T.noData}</td></tr>}
                  {data.items.map((e) => (
                    <tr key={e.id}>
                      <td className="num">{formatDateTime(e.created_at)}</td>
                      <td>{e.username ?? T.none}</td>
                      <td>{AUDIT_ACTIONS[e.action] ?? e.action}</td>
                      <td className="ltr small">{e.entity_type ?? ""} {e.entity_id ? e.entity_id.slice(0, 8) : ""}</td>
                      <td className="small"><AuditCell entry={e} /></td>
                      <td className="ltr small">{e.ip_address ?? ""}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Pagination page={data.page} pageSize={data.page_size} total={data.total} onChange={setPage} />
          </>
        )}
      </div>
    </>
  );
}
