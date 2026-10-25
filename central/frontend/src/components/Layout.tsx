import { useEffect, useRef, useState } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";

import { useAuth } from "@/lib/auth";
import { T, t } from "@/lib/i18n";
import { initials } from "@/lib/format";
import {
  IconDashboard,
  IconFolder,
  IconKey,
  IconLogout,
  IconMonitor,
  IconPlus,
  IconMic as IconVoice,
  IconGear,
  IconShield,
  IconUsers,
  IconX,
} from "./Icons";

const APP_VERSION = "1.0.0";

export interface Crumb {
  label: string;
  to?: string;
}

function Breadcrumbs({ crumbs }: { crumbs: Crumb[] }) {
  return (
    <nav className="breadcrumbs" aria-label="breadcrumb">
      <Link to="/">{T.dashboard}</Link>
      {crumbs.map((c, i) => (
        <span key={i} className="flex">
          <span className="sep">/</span>
          {c.to && i < crumbs.length - 1 ? <Link to={c.to}>{c.label}</Link> : <span className="current">{c.label}</span>}
        </span>
      ))}
    </nav>
  );
}

export function crumbsFor(pathname: string): Crumb[] {
  if (pathname.startsWith("/investigations/new")) return [{ label: T.investigations, to: "/investigations" }, { label: T.newInvestigation }];
  if (/^\/investigations\/[^/]+\/report/.test(pathname)) return [{ label: T.investigations, to: "/investigations" }, { label: "إعداد المحضر" }];
  if (/^\/investigations\/[^/]+\/edit/.test(pathname)) return [{ label: T.investigations, to: "/investigations" }, { label: "تعديل بيانات الجلسة" }];
  if (pathname.startsWith("/investigations/")) return [{ label: T.investigations, to: "/investigations" }, { label: T.sessionDetails }];
  if (pathname.startsWith("/investigations")) return [{ label: T.investigations }];
  if (pathname.startsWith("/users")) return [{ label: T.users }];
  if (pathname.startsWith("/workstations")) return [{ label: T.workstations }];
  if (pathname.startsWith("/voice-enrollments")) return [{ label: T.voiceEnrollments }];
  if (pathname.startsWith("/audit")) return [{ label: T.audit }];
  if (pathname.startsWith("/report-template")) return [{ label: T.templateTitle }];
  if (pathname.startsWith("/settings")) return [{ label: T.systemConfig }];
  if (pathname.startsWith("/change-password")) return [{ label: T.changePassword }];
  return [];
}

export function Layout() {
  const { user, logout, can } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [navOpen, setNavOpen] = useState(false);
  const menu = useRef<HTMLButtonElement>(null);
  const sidebar = useRef<HTMLElement>(null);
  useEffect(() => { setNavOpen(false); }, [location.pathname]);
  useEffect(() => {
    if (!navOpen) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    sidebar.current?.querySelector<HTMLElement>("button, a")?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setNavOpen(false);
      if (event.key !== "Tab") return;
      const items = Array.from(sidebar.current?.querySelectorAll<HTMLElement>("a, button") ?? []).filter(el => el.getClientRects().length);
      if (event.shiftKey && document.activeElement === items[0]) { event.preventDefault(); items[items.length - 1]?.focus(); }
      else if (!event.shiftKey && document.activeElement === items[items.length - 1]) { event.preventDefault(); items[0]?.focus(); }
    };
    const onResize = () => { if (window.innerWidth > 960) setNavOpen(false); };
    window.addEventListener("keydown", onKey); window.addEventListener("resize", onResize);
    return () => { document.body.style.overflow = previousOverflow; window.removeEventListener("keydown", onKey); window.removeEventListener("resize", onResize); menu.current?.focus(); };
  }, [navOpen]);
  const displayName = user?.profile?.full_name || user?.username || "";
  const roleLabel = user?.roles.map((r) => t(`role${r[0]}${r.slice(1).toLowerCase()}`, r)).join("، ");

  return (
    <div className={`app-shell ${navOpen ? "navigation-open" : ""}`}>
      <a className="skip-link" href="#main-content">انتقل إلى المحتوى</a>
      {navOpen && <div className="navigation-scrim" onClick={() => setNavOpen(false)} aria-hidden="true" />}
      <aside ref={sidebar} id="primary-navigation" className={`sidebar ${navOpen ? "is-open" : ""}`} aria-label="القائمة الرئيسية" role={navOpen ? "dialog" : undefined} aria-modal={navOpen || undefined}>
        <div className="sidebar-brand">
          <div className="logo">
            <IconShield width={25} height={25} />
          </div>
          <div>
            <strong>{T.appShort}</strong>
            <small>منصة المعلومات والتحقيق</small>
          </div>
        </div>
        <button className="icon-btn navigation-close" type="button" onClick={() => setNavOpen(false)} aria-label="إغلاق القائمة"><IconX /></button>
        <div className="sidebar-context"><span className="context-rule" /><span lang="en" dir="ltr">INTELLIGENCE & INVESTIGATION</span></div>
        <nav aria-label="التنقل الرئيسي">
          <div className="nav-section">{T.operations}</div>
          <NavLink to="/" end className={({ isActive }) => `nav-link ${isActive ? "active" : ""}`}>
            <IconDashboard /> {T.dashboard}
          </NavLink>
          <NavLink to="/investigations" end className={({ isActive }) => `nav-link ${isActive ? "active" : ""}`}>
            <IconFolder /> {T.investigations}
          </NavLink>
          {can("investigations.create") && (
            <NavLink to="/investigations/new" className={({ isActive }) => `nav-link ${isActive ? "active" : ""}`}>
              <IconPlus /> {T.newInvestigation}
            </NavLink>
          )}
          {(can("users.manage") || can("workstations.read") || can("audit.read") || can("voice.identify")) && <div className="nav-section">{T.administration}</div>}
          {can("users.manage") && (
            <NavLink to="/users" className={({ isActive }) => `nav-link ${isActive ? "active" : ""}`}>
              <IconUsers /> {T.users}
            </NavLink>
          )}
          {can("workstations.read") && (
            <NavLink to="/workstations" className={({ isActive }) => `nav-link ${isActive ? "active" : ""}`}>
              <IconMonitor /> {T.workstations}
            </NavLink>
          )}
          {can("voice.identify") && (
            <NavLink to="/voice-enrollments" className={({ isActive }) => `nav-link ${isActive ? "active" : ""}`}>
              <IconVoice /> {T.voiceEnrollments}
            </NavLink>
          )}
          {can("audit.read") && (
            <NavLink to="/audit" className={({ isActive }) => `nav-link ${isActive ? "active" : ""}`}>
              <IconShield /> {T.audit}
            </NavLink>
          )}
          {can("system.configure") && (
            <NavLink to="/settings" className={({ isActive }) => `nav-link ${isActive ? "active" : ""}`}>
              <IconGear /> {T.systemConfig}
            </NavLink>
          )}
        </nav>
        <div className="sidebar-footer">
          <div className="sidebar-footer-heading"><IconShield /> بيئة العمليات المركزية</div>
          <span lang="en" dir="ltr">MILITARY POLICE · v{APP_VERSION}</span>
        </div>
      </aside>

      <div className="main">
        <header className="topbar">
          <div className="topbar-location"><button ref={menu} className="icon-btn navigation-toggle" type="button" onClick={() => setNavOpen(true)} aria-label="فتح القائمة الرئيسية" aria-expanded={navOpen} aria-controls="primary-navigation"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true"><path d="M4 6h16M4 12h16M4 18h16" /></svg></button><div><div className="topbar-kicker">مركز العمليات والتحقيق</div><Breadcrumbs crumbs={crumbsFor(location.pathname)} /></div></div>
          <div className="user-menu">
            <div className="avatar" aria-hidden>
              {initials(displayName)}
            </div>
            <div>
              <div className="name">{displayName}</div>
              <div className="role">{roleLabel}</div>
            </div>
            <button className="icon-btn" aria-label={T.changePassword} title={T.changePassword} onClick={() => navigate("/change-password")} type="button">
              <IconKey />
            </button>
            <button
              className="icon-btn"
              title={T.logout}
              aria-label={T.logout}
              onClick={() => {
                void logout().then(() => navigate("/login"));
              }}
              type="button"
            >
              <IconLogout />
            </button>
          </div>
        </header>
        <main className="content" id="main-content" tabIndex={-1}>
          <Outlet />
        </main>
      </div>
    </div>
  );
}
