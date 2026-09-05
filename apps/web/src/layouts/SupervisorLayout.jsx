import React from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";

export default function SupervisorLayout() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  const handleLogout = () => { logout(); navigate("/login"); };

  return (
    <div className="app-layout">
      <aside className="sidebar">
        <div className="sidebar-brand">
          <span className="brand-icon">🛢</span>
          <span className="brand-text">OilSpillAI</span>
        </div>
        <div className="sidebar-role">Supervisor</div>
        <nav className="sidebar-nav">
          <NavLink to="/supervisor" end className={({ isActive }) => isActive ? "nav-link active" : "nav-link"}>
            <span className="nav-icon">📋</span> All Cases
          </NavLink>
          <NavLink to="/supervisor/analytics" className={({ isActive }) => isActive ? "nav-link active" : "nav-link"}>
            <span className="nav-icon">📊</span> Analytics
          </NavLink>
        </nav>
        <div className="sidebar-footer">
          <div className="sidebar-user">{user?.name}</div>
          <button className="btn-logout" onClick={handleLogout}>Sign Out</button>
        </div>
      </aside>
      <main className="main-content">
        <Outlet />
      </main>
    </div>
  );
}
