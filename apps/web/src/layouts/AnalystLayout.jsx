import React from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";

export default function AnalystLayout() {
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
        <div className="sidebar-role">Analyst</div>
        <nav className="sidebar-nav">
          <NavLink to="/analyst" end className={({ isActive }) => isActive ? "nav-link active" : "nav-link"}>
            <span className="nav-icon">📋</span> Dashboard
          </NavLink>
          <NavLink to="/analyst/new" className={({ isActive }) => isActive ? "nav-link active" : "nav-link"}>
            <span className="nav-icon">＋</span> New Investigation
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
