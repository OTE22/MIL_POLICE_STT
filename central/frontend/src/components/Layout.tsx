import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";

import { useAuth } from "@/lib/auth";
import { T, t } from "@/lib/i18n";
import { initials } from "@/lib/format";
import {
  IconDashboard,
  IconFolder,
  IconKey,
  IconLogout,
  IconMic,
  IconMonitor,
  IconPlus,
  IconShield,
  IconUsers,
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
  if (pathname.startsWith("/investigations/")) return [{ label: T.investigations, to: "/investigations" }, { label: T.sessionDetails }];
  if (pathname.startsWith("/investigations")) return [{ label: T.investigations }];
  if (pathname.startsWith("/users")) return [{ label: T.users }];
  if (pathname.startsWith("/workstations")) return [{ label: T.workstations }];
  if (pathname.startsWith("/audit")) return [{ label: T.audit }];
  if (pathname.startsWith("/change-password")) return [{ label: T.changePassword }];
  return [];
}

export function Layout() {
  const { user, logout, can } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const displayName = user?.profile?.full_name || user?.username || "";
  const roleLabel = user?.roles.map((r) => t(`role${r[0]}${r.slice(1).toLowerCase()}`, r)).join("، ");

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="sidebar-brand">
          <div className="logo">
            <IconMic width={20} height={20} />
          </div>
          <div>
            <strong>{T.appShort}</strong>
            <small>{T.orgLine}</small>
          </div>
        </div>
        <nav>
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
          {(can("users.manage") || can("workstations.read") || can("audit.read")) && <div className="nav-section">{T.administration}</div>}
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
          {can("audit.read") && (
            <NavLink to="/audit" className={({ isActive }) => `nav-link ${isActive ? "active" : ""}`}>
              <IconShield /> {T.audit}
            </NavLink>
          )}
        </nav>
        <div className="sidebar-footer">
          {T.appName} — <span className="num">v{APP_VERSION}</span>
        </div>
      </aside>

      <div className="main">
        <header className="topbar">
          <Breadcrumbs crumbs={crumbsFor(location.pathname)} />
          <div className="user-menu">
            <div className="avatar" aria-hidden>
              {initials(displayName)}
            </div>
            <div>
              <div className="name">{displayName}</div>
              <div className="role">{roleLabel}</div>
            </div>
            <button className="icon-btn" title={T.changePassword} onClick={() => navigate("/change-password")} type="button">
              <IconKey />
            </button>
            <button
              className="icon-btn"
              title={T.logout}
              onClick={() => {
                void logout().then(() => navigate("/login"));
              }}
              type="button"
            >
              <IconLogout />
            </button>
          </div>
        </header>
        <main className="content">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
