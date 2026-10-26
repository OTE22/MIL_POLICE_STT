import { workflowLabels } from "@/components/InvestigationWorkflow";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { http } from "@/api/client";
import type { Dashboard } from "@/api/types";
import { useAuth } from "@/lib/auth";
import { formatDate } from "@/lib/format";
import { T } from "@/lib/i18n";
import { IconClock, IconFolder, IconCheck, IconWave, IconPlus, IconChevronLeft, IconFile, IconShield } from "@/components/Icons";
import { Alert, Loading, Badge, SessionStatusBadge } from "@/components/ui";

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
          <span className="page-kicker" lang="en" dir="ltr">OPERATIONS OVERVIEW</span>
          <h1>{T.dashboard}</h1>
          <p>صورة واضحة لسير التحقيقات وأعمال التوثيق</p>
        </div>
        {can("investigations.create") && (
          <Link to="/investigations/new" className="btn btn-primary">
            <IconPlus /> {T.newInvestigation}
          </Link>
        )}
      </div>

      <section className="dashboard-welcome">
        <div>
          <span className="eyebrow"><span className="tactical-rule" /> مساحة العمليات</span>
          <h2>مرحباً، {user?.profile?.full_name || user?.username}</h2>
          <p>من الأدلة الصوتية إلى الإفادة الموثّقة.<br />تابع الجلسات، راجع المتحدثين، وأكمل المحاضر من مساحة واحدة.</p>
          <Link to="/investigations" className="welcome-link">استعراض الجلسات <IconChevronLeft /></Link>
        </div>
        <div className="command-summary"><div className="command-ring" style={{ "--completion": `${data.total_sessions ? Math.min(100, Math.round(data.completed / data.total_sessions * 100)) : 0}%` } as React.CSSProperties}><IconShield width={30} height={30} /><strong className="num">{data.total_sessions ? Math.round(data.completed / data.total_sessions * 100) : 0}%</strong><span>جلسات مكتملة</span></div><span className="command-summary-caption">{data.completed} من {data.total_sessions} جلسة</span></div>
      </section>

      <div className="grid grid-4 mb-16">
        {cards.map((c) => (
          <div key={c.label} className="card stat">
            <div className="stat-top"><span className="stat-caption" lang="en" dir="ltr">{String(cards.indexOf(c) + 1).padStart(2, "0")} / INTEL</span><div className="icon">{c.icon}</div></div>
            <span className="label">{c.label}</span>
            <span className="value num">{c.value}</span>
          </div>
        ))}
      </div>

      <section className="dashboard-workflow" aria-label="مسار العمل">
        <Link to="/investigations"><span className="workflow-icon"><IconFolder /></span><div><h3>إدارة التحقيقات</h3><p>البيانات والمشاركون والتسجيلات</p></div><IconChevronLeft /></Link>
        {can("voice.identify") && <Link to="/voice-enrollments"><span className="workflow-icon"><IconWave /></span><div><h3>الهويات الصوتية</h3><p>مراجعة الأشخاص وعينات الصوت</p></div><IconChevronLeft /></Link>}
        {can("reports.generate") && <Link to="/investigations"><span className="workflow-icon"><IconFile /></span><div><h3>محاضر التحقيق</h3><p>اختر جلسة لإعداد المحضر ومراجعته وإصدار HTML وPDF</p></div><IconChevronLeft /></Link>}
      </section>

      <div className="card">
        <div className="card-header">
          <div><h2>{T.recentSessions}</h2><p className="hint">الوصول إلى تفاصيل الجلسات ومتابعة حالتها</p></div>
          <Link to="/investigations" className="btn btn-sm">
            {T.view} {T.all}
          </Link>
        </div>
        <div className="table-wrap" tabIndex={0} role="region" aria-label="جدول البيانات — مرّر أفقياً لعرض جميع الأعمدة">
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
                    <div><Badge kind={s.workflow_state === "CLOSED" ? "green" : "navy"}>{workflowLabels[s.workflow_state] ?? workflowLabels.DRAFT}</Badge><div className="mt-8">معالجة التسجيلات: <SessionStatusBadge status={s.status} /></div></div>
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
