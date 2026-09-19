import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import type { ReactNode } from "react";

import { useAuth } from "@/lib/auth";
import { Layout } from "@/components/Layout";
import { Loading } from "@/components/ui";
import { LoginPage } from "@/pages/LoginPage";
import { DashboardPage } from "@/pages/DashboardPage";
import { InvestigationsPage } from "@/pages/InvestigationsPage";
import { InvestigationFormPage } from "@/pages/InvestigationFormPage";
import { SystemConfigPage } from "@/pages/SystemConfigPage";
import { InvestigationDetailPage } from "@/pages/InvestigationDetailPage";
import { UsersPage } from "@/pages/UsersPage";
import { WorkstationsPage } from "@/pages/WorkstationsPage";
import { AuditPage } from "@/pages/AuditPage";
import { VoiceEnrollmentsPage } from "@/pages/VoiceEnrollmentsPage";
import { ReportComposerPage } from "@/pages/ReportComposerPage";
import { ReportTemplatePage } from "@/pages/ReportTemplatePage";
import { ChangePasswordPage } from "@/pages/ChangePasswordPage";

function RequireAuth({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth();
  const location = useLocation();
  if (loading) return <Loading />;
  if (!user) return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  if (user.must_change_password && location.pathname !== "/change-password") return <Navigate to="/change-password" replace />;
  return <>{children}</>;
}

function RequirePermission({ codes, children }: { codes: string[]; children: ReactNode }) {
  const { can } = useAuth();
  if (!can(...codes)) return <Navigate to="/" replace />;
  return <>{children}</>;
}

export function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        element={
          <RequireAuth>
            <Layout />
          </RequireAuth>
        }
      >
        <Route path="/" element={<DashboardPage />} />
        <Route path="/investigations" element={<InvestigationsPage />} />
        <Route
          path="/investigations/new"
          element={
            <RequirePermission codes={["investigations.create"]}>
              <InvestigationFormPage />
            </RequirePermission>
          }
        />
        <Route path="/investigations/:id" element={<InvestigationDetailPage />} />
        <Route path="/investigations/:id/edit" element={<InvestigationFormPage />} />
        <Route
          path="/report-template"
          element={
            <RequirePermission codes={["reports.templates.manage"]}>
              <ReportTemplatePage />
            </RequirePermission>
          }
        />
        <Route
          path="/investigations/:id/report"
          element={
            <RequirePermission codes={["reports.read", "reports.generate"]}>
              <ReportComposerPage />
            </RequirePermission>
          }
        />
        <Route
          path="/users"
          element={
            <RequirePermission codes={["users.manage"]}>
              <UsersPage />
            </RequirePermission>
          }
        />
        <Route
          path="/settings"
          element={
            <RequirePermission codes={["system.configure"]}>
              <SystemConfigPage />
            </RequirePermission>
          }
        />
        <Route
          path="/workstations"
          element={
            <RequirePermission codes={["workstations.read"]}>
              <WorkstationsPage />
            </RequirePermission>
          }
        />
        <Route
          path="/voice-enrollments"
          element={
            <RequirePermission codes={["voice.identify"]}>
              <VoiceEnrollmentsPage />
            </RequirePermission>
          }
        />
        <Route
          path="/audit"
          element={
            <RequirePermission codes={["audit.read"]}>
              <AuditPage />
            </RequirePermission>
          }
        />
        <Route path="/change-password" element={<ChangePasswordPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
