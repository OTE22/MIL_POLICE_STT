import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { http } from "@/api/client";
import type { Dashboard } from "@/api/types";
import { useAuth } from "@/lib/auth";
import { formatDate } from "@/lib/format";
import { T } from "@/lib/i18n";
import { IconClock, IconFolder, IconCheck, IconWave, IconPlus } from "@/components/Icons";
import { Loading, SessionStatusBadge } from "@/components/ui";

export function DashboardPage() {
  const { can } = useAuth();
  const [data, setData] = useState<Dashboard | null>(null);

  useEffect(() => {
    void http.get<Dashboard>("/investigations/dashboard").then(setData);
  }, []);

  if (!data) return <Loading />;

  const cards = [
    { label: T.totalSessions, value: data.total_sessions, icon: <IconFolder /> },
    { label: T.sessionsToday, value: data.sessions_today, icon: <IconClock /> },
    { label: T.processing, value: data.processing, icon: <IconWave /> },
    { label: T.completedSessions, value: data.completed, icon: <IconCheck /> },
  ];

  return (
    <>
      <div className="page-header">
        <div>
          <h1>{T.dashboard}</h1>
          <p>{T.orgLine}</p>
        </div>
        {can("investigations.create") && (
          <Link to="/investigations/new" className="btn btn-primary">
            <IconPlus /> {T.newInvestigation}
          </Link>
        )}
      </div>

      <div className="grid grid-4 mb-16">
        {cards.map((c) => (
          <div key={c.label} className="card stat">
            <div className="icon">{c.icon}</div>
            <span className="label">{c.label}</span>
            <span className="value num">{c.value}</span>
          </div>
        ))}
      </div>

      <div className="card">
        <div className="card-header">
          <h2>{T.recentSessions}</h2>
          <Link to="/investigations" className="btn btn-sm">
            {T.view} {T.all}
          </Link>
        </div>
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>{T.sessionNumber}</th>
                <th>{T.title}</th>
                <th>{T.investigator}</th>
                <th>{T.date}</th>
                <th>{T.location}</th>
                <th>{T.status}</th>
                <th>{T.actions}</th>
              </tr>
            </thead>
            <tbody>
              {data.recent.length === 0 && (
                <tr>
                  <td colSpan={7} className="empty">
                    {T.noData}
                  </td>
                </tr>
              )}
              {data.recent.map((s) => (
                <tr key={s.id}>
                  <td className="mono">{s.session_number}</td>
                  <td>{s.title}</td>
                  <td>{s.lead_investigator ?? T.none}</td>
                  <td className="num">{formatDate(s.session_date)}</td>
                  <td>{s.location ?? T.none}</td>
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
      </div>
    </>
  );
}
