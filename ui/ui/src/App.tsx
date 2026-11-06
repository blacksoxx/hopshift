import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import { AssessPage } from "./pages/AssessPage";
import { NewRunPage } from "./pages/NewRunPage";
import { RunDetailPage } from "./pages/RunDetailPage";
import { RunsPage } from "./pages/RunsPage";
import { SettingsPage } from "./pages/SettingsPage";

export default function App() {
  return (
    <div className="layout">
      <aside className="sidebar">
        <div className="brand">
          VMware Migration Agent
          <small>deterministic core, AI at the edges</small>
        </div>
        <nav>
          <NavLink to="/runs" end>Runs</NavLink>
          <NavLink to="/runs/new">New run</NavLink>
          <NavLink to="/assess">Assess</NavLink>
          <NavLink to="/settings">Settings</NavLink>
        </nav>
      </aside>
      <main className="content">
        <Routes>
          <Route path="/" element={<Navigate to="/runs" replace />} />
          <Route path="/runs" element={<RunsPage />} />
          <Route path="/runs/new" element={<NewRunPage />} />
          <Route path="/runs/:runId" element={<RunDetailPage />} />
          <Route path="/assess" element={<AssessPage />} />
          <Route path="/settings" element={<SettingsPage />} />
        </Routes>
      </main>
    </div>
  );
}
