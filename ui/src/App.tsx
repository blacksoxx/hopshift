import { Navigate, Route, Routes } from "react-router-dom";
import { AppShell } from "@/components/shell/AppShell";
import { PublicOnly, RequireAuth, RequireRole } from "@/components/shell/guards";
import { DashboardPage } from "@/pages/DashboardPage";
import { LoginPage } from "@/pages/LoginPage";
import { SetupPage } from "@/pages/SetupPage";
import { RunsPage } from "@/pages/RunsPage";
import { NewRunPage } from "@/pages/NewRunPage";
import { RunDetailPage } from "@/pages/RunDetailPage";
import { AssessPage } from "@/pages/AssessPage";
import { ConnectionsPage } from "@/pages/ConnectionsPage";
import { SettingsPage } from "@/pages/SettingsPage";
import { AuditPage } from "@/pages/AuditPage";

export default function App() {
  return (
    <Routes>
      <Route
        path="/login"
        element={
          <PublicOnly>
            <LoginPage />
          </PublicOnly>
        }
      />
      <Route
        path="/setup"
        element={
          <PublicOnly>
            <SetupPage />
          </PublicOnly>
        }
      />
      <Route
        element={
          <RequireAuth>
            <AppShell />
          </RequireAuth>
        }
      >
        <Route index element={<DashboardPage />} />
        <Route path="/runs" element={<RunsPage />} />
        <Route
          path="/runs/new"
          element={
            <RequireRole role="operator">
              <NewRunPage />
            </RequireRole>
          }
        />
        <Route path="/runs/:runId" element={<RunDetailPage />} />
        <Route path="/runs/:runId/:tab" element={<RunDetailPage />} />
        <Route path="/assess" element={<AssessPage />} />
        <Route path="/connections" element={<ConnectionsPage />} />
        <Route path="/connections/:connectionId" element={<ConnectionsPage />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="/settings/:tab" element={<SettingsPage />} />
        <Route
          path="/audit"
          element={
            <RequireRole role="admin">
              <AuditPage />
            </RequireRole>
          }
        />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
