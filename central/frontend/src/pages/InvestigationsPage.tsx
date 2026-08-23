import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { http, qs } from "@/api/client";
import type { InvestigationListItem, Paged, Profile, SessionStatus } from "@/api/types";
import { useAuth } from "@/lib/auth";
import { formatDate, formatDuration } from "@/lib/format";
import { T, t } from "@/lib/i18n";
import { IconPlus, IconSearch } from "@/components/Icons";
import { Loading, Pagination, SessionStatusBadge } from "@/components/ui";

const STATUSES: SessionStatus[] = ["DRAFT", "RECORDING", "PROCESSING", "COMPLETED", "FAILED", "ARCHIVED"];

export function InvestigationsPage() {
  const { can } = useAuth();
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [investigatorId, setInvestigatorId] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [page, setPage] = useState(1);
  const [data, setData] = useState<Paged<InvestigationListItem> | null>(null);
  const [investigators, setInvestigators] = useState<Profile[]>([]);
  const pageSize = 20;

  useEffect(() => {
    if (can("investigators.read")) void http.get<Profile[]>("/investigators").then(setInvestigators).catch(() => undefined);
  }, [can]);

  useEffect(() => {
    const handle = setTimeout(() => {
      void http
        .get<Paged<InvestigationListItem>>(
          `/investigations${qs({ q, status, investigator_id: investigatorId, date_from: dateFrom, date_to: dateTo, page, page_size: pageSize })}`,
        )
        .then(setData);
    }, 250);
    return () => clearTimeout(handle);
  }, [q, status, investigatorId, dateFrom, dateTo, page]);

  const reset = () => {
    setQ("");
    setStatus("");
    setInvestigatorId("");
    setDateFrom("");
    setDateTo("");
    setPage(1);
  };

  return (
    <>
      <div className="page-header">
        <div>
          <h1>{T.investigations}</h1>
        </div>
        {can("investigations.create") && (
          <Link to="/investigations/new" className="btn btn-primary">
            <IconPlus /> {T.newInvestigation}
          </Link>
        )}
      </div>

      <div className="card">
        <div className="toolbar">
          <div className="flex" style={{ position: "relative" }}>
            <input
              className="input search"
              placeholder={T.searchPlaceholder}
              value={q}
              onChange={(e) => {
                setQ(e.target.value);
                setPage(1);
              }}
              aria-label={T.search}
            />
            <IconSearch style={{ position: "absolute", insetInlineEnd: 10, top: 9, color: "var(--muted)" }} width={16} height={16} />
          </div>
          <select className="select" value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }} aria-label={T.status}>
            <option value="">{T.status}: {T.all}</option>
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {t(`status_${s}`)}
              </option>
            ))}
          </select>
          {investigators.length > 0 && (
            <select className="select" value={investigatorId} onChange={(e) => { setInvestigatorId(e.target.value); setPage(1); }} aria-label={T.investigator}>
              <option value="">{T.investigator}: {T.all}</option>
              {investigators.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.full_name}
                </option>
              ))}
            </select>
          )}
          <input className="input" type="date" value={dateFrom} onChange={(e) => { setDateFrom(e.target.value); setPage(1); }} aria-label="من تاريخ" />
          <input className="input" type="date" value={dateTo} onChange={(e) => { setDateTo(e.target.value); setPage(1); }} aria-label="إلى تاريخ" />
          <button className="btn btn-ghost" onClick={reset} type="button">
            {T.reset}
          </button>
        </div>
        {!data ? (
          <Loading />
        ) : (
          <>
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>{T.sessionNumber}</th>
                    <th>{T.title}</th>
                    <th>{T.investigator}</th>
                    <th>{T.location}</th>
                    <th>{T.date}</th>
                    <th>{T.duration}</th>
                    <th>{T.status}</th>
                    <th>{T.actions}</th>
                  </tr>
                </thead>
                <tbody>
                  {data.items.length === 0 && (
                    <tr>
                      <td colSpan={8} className="empty">
                        {T.noData}
                      </td>
                    </tr>
                  )}
                  {data.items.map((s) => (
                    <tr key={s.id}>
                      <td className="mono">{s.session_number}</td>
                      <td>
                        <Link to={`/investigations/${s.id}`}>{s.title}</Link>
                      </td>
                      <td>{s.lead_investigator ?? T.none}</td>
                      <td>{s.location ?? T.none}</td>
                      <td className="num">{formatDate(s.session_date)}</td>
                      <td>{formatDuration(s.duration_seconds)}</td>
                      <td>
                        <SessionStatusBadge status={s.status} />
                      </td>
                      <td className="actions-cell">
                        <Link to={`/investigations/${s.id}`} className="btn btn-sm">
                          {T.view}
                        </Link>
                      </td>
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
