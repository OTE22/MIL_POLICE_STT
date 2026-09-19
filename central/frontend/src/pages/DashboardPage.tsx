import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { http } from "@/api/client";
import type { Dashboard } from "@/api/types";
import { useAuth } from "@/lib/auth";
import { formatDate } from "@/lib/format";
import { T } from "@/lib/i18n";
import { IconClock, IconFolder, IconCheck, IconWave, IconPlus, IconChevronLeft } from "@/components/Icons";
import { Alert, Loading, SessionStatusBadge } from "@/components/ui";

export function DashboardPage() {
  const { can, user } = useAuth();
  const [data, setData] = useState<Dashboard | null>(null);
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let active = true;
    setFailed(false);
    void http.get<Dashboard>("/investigations/dashboard").then((result) => { if (active) setData(result); }).catch(() => { if (active) setFailed(true); });
    return () => { active = false; };
  }, [attempt]);

  if (failed) return <Alert kind="danger"><div>{T.err_generic}</div><button className="btn btn-sm mt-8" onClick={() => setAttempt((value) => value + 1)}>إعادة المحاولة</button></Alert>;
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
          <p>نظرة شاملة على الجلسات وأعمال التوثيق</p>
        </div>
        {can("investigations.create") && (
          <Link to="/investigations/new" className="btn btn-primary">
            <IconPlus /> {T.newInvestigation}
          </Link>
        )}
      </div>

      <section className="dashboard-welcome">
        <div>
          <span className="eyebrow">مساحة العمل</span>
          <h2>مرحباً، {user?.profile?.full_name || user?.username}</h2>
          <p>تابع جلساتك، راجع النصوص، وأكمل التوثيق من مكان واحد.</p>
          <Link to="/investigations" className="welcome-link">استعراض الجلسات <IconChevronLeft /></Link>
        </div>
        <div className="welcome-emblem" aria-hidden="true"><IconWave width={100} height={100} /></div>
      </section>

      <div className="grid grid-4 mb-16">
        {cards.map((c) => (
          <div key={c.label} className="card stat">
            <div className="stat-top"><span className="stat-caption">ملخص الجلسات</span><div className="icon">{c.icon}</div></div>
            <span className="label">{c.label}</span>
            <span className="value num">{c.value}</span>
          </div>
        ))}
      </div>

      <div className="card">
        <div className="card-header">
          <div><h2>{T.recentSessions}</h2><p className="hint">الوصول إلى تفاصيل الجلسات ومتابعة حالتها</p></div>
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
                    <div className="empty-state"><IconFolder width={32} height={32} /><strong>{T.noData}</strong><span>ستظهر الجلسات هنا عند إضافتها</span>{can("investigations.create") && <Link to="/investigations/new" className="btn btn-primary btn-sm"><IconPlus />{T.newInvestigation}</Link>}</div>
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
