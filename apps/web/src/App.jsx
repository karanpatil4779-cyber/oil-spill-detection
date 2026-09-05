import React from "react";
import { Routes, Route, Navigate } from "react-router-dom";
import { useAuth } from "./auth/AuthContext";
import ProtectedRoute from "./auth/ProtectedRoute";
import LoginPage from "./pages/LoginPage";
import AnalystLayout from "./layouts/AnalystLayout";
import SupervisorLayout from "./layouts/SupervisorLayout";
import AdminLayout from "./layouts/AdminLayout";
import AnalystDashboard from "./pages/analyst/Dashboard";
import NewInvestigation from "./pages/analyst/NewInvestigation";
import Workspace from "./pages/analyst/Workspace";
import PortfolioDashboard from "./pages/supervisor/PortfolioDashboard";
import CaseReview from "./pages/supervisor/CaseReview";
import Analytics from "./pages/supervisor/Analytics";
import SystemDashboard from "./pages/admin/SystemDashboard";
import UserManagement from "./pages/admin/UserManagement";
import DataSourceConfig from "./pages/admin/DataSourceConfig";
import ModelRegistry from "./pages/admin/ModelRegistry";
import AuditLogPage from "./pages/admin/AuditLog";

function RootRedirect() {
  const { user, loading } = useAuth();
  if (loading) return <div className="loading-screen">Loading...</div>;
  if (!user) return <Navigate to="/login" replace />;
  const map = { analyst: "/analyst", supervisor: "/supervisor", admin: "/admin" };
  return <Navigate to={map[user.role] || "/login"} replace />;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />

      {/* Analyst */}
      <Route path="/analyst" element={
        <ProtectedRoute roles={["analyst"]}><AnalystLayout /></ProtectedRoute>
      }>
        <Route index element={<AnalystDashboard />} />
        <Route path="new" element={<NewInvestigation />} />
        <Route path="case/:caseId" element={<Workspace />} />
      </Route>

      {/* Supervisor */}
      <Route path="/supervisor" element={
        <ProtectedRoute roles={["supervisor", "admin"]}><SupervisorLayout /></ProtectedRoute>
      }>
        <Route index element={<PortfolioDashboard />} />
        <Route path="case/:caseId" element={<CaseReview />} />
        <Route path="analytics" element={<Analytics />} />
      </Route>

      {/* Admin */}
      <Route path="/admin" element={
        <ProtectedRoute roles={["admin"]}><AdminLayout /></ProtectedRoute>
      }>
        <Route index element={<SystemDashboard />} />
        <Route path="users" element={<UserManagement />} />
        <Route path="data-sources" element={<DataSourceConfig />} />
        <Route path="models" element={<ModelRegistry />} />
        <Route path="audit" element={<AuditLogPage />} />
      </Route>

      <Route path="*" element={<RootRedirect />} />
    </Routes>
  );
}
