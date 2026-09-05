import React from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";

export default function AdminLayout() {
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
        <div className="sidebar-role">Administrator</div>
        <nav className="sidebar-nav">
          <NavLink to="/admin" end className={({ isActive }) => isActive ? "nav-link active" : "nav-link"}>
            <span className="nav-icon">🖥</span> System Status
          </NavLink>
          <NavLink to="/admin/users" className={({ isActive }) => isActive ? "nav-link active" : "nav-link"}>
            <span className="nav-icon">👥</span> Users
          </NavLink>
          <NavLink to="/admin/data-sources" className={({ isActive }) => isActive ? "nav-link active" : "nav-link"}>
            <span className="nav-icon">📡</span> Data Sources
          </NavLink>
          <NavLink to="/admin/models" className={({ isActive }) => isActive ? "nav-link active" : "nav-link"}>
            <span className="nav-icon">🤖</span> Model Registry
          </NavLink>
          <NavLink to="/admin/audit" className={({ isActive }) => isActive ? "nav-link active" : "nav-link"}>
            <span className="nav-icon">📜</span> Audit Log
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
