import React, { useState, useEffect } from "react";
import { apiGet, apiPost, apiPatch } from "../../api/client";
import { ROLES } from "../../utils/constants";

export default function UserManagement() {
  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [form, setForm] = useState({ email: "", name: "", password: "", role: "analyst" });

  useEffect(() => { loadUsers(); }, []);

  const loadUsers = async () => {
    setLoading(true);
    try {
      const data = await apiGet("/admin/users");
      setUsers(data);
    } catch (err) { console.error(err); }
    finally { setLoading(false); }
  };

  const handleCreate = async (e) => {
    e.preventDefault();
    try {
      await apiPost("/admin/users", form);
      setShowCreate(false);
      setForm({ email: "", name: "", password: "", role: "analyst" });
      loadUsers();
    } catch (err) { alert(err.message); }
  };

  const handleToggleStatus = async (user) => {
    const newStatus = user.status === "active" ? "deactivated" : "active";
    await apiPatch(`/admin/users/${user.id}`, { status: newStatus });
    loadUsers();
  };

  const handleRoleChange = async (userId, newRole) => {
    await apiPatch(`/admin/users/${userId}`, { role: newRole });
    loadUsers();
  };

  return (
    <div className="page-container">
      <div className="page-header">
        <h1>User Management</h1>
        <button className="btn-primary" onClick={() => setShowCreate(true)}>+ Create Account</button>
      </div>

      {showCreate && (
        <div className="create-user-form">
          <form onSubmit={handleCreate}>
            <div className="form-grid">
              <div><label>Name</label><input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required /></div>
              <div><label>Email</label><input type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} required /></div>
              <div><label>Password</label><input type="password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} required /></div>
              <div>
                <label>Role</label>
                <select value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}>
                  <option value="analyst">Analyst</option>
                  <option value="supervisor">Supervisor</option>
                  <option value="admin">Admin</option>
                </select>
              </div>
            </div>
            <div className="form-actions">
              <button type="button" className="btn-secondary" onClick={() => setShowCreate(false)}>Cancel</button>
              <button type="submit" className="btn-primary">Create</button>
            </div>
          </form>
        </div>
      )}

      {loading ? <div className="loading">Loading users...</div> : (
        <table className="admin-table">
          <thead>
            <tr><th>Name</th><th>Email</th><th>Role</th><th>Status</th><th>Last Login</th><th>Actions</th></tr>
          </thead>
          <tbody>
            {users.map((u) => (
              <tr key={u.id}>
                <td>{u.name}</td>
                <td className="mono">{u.email}</td>
                <td>
                  <select value={u.role} onChange={(e) => handleRoleChange(u.id, e.target.value)} className="inline-select">
                    <option value="analyst">Analyst</option>
                    <option value="supervisor">Supervisor</option>
                    <option value="admin">Admin</option>
                  </select>
                </td>
                <td>
                  <span className={`status-indicator ${u.status === "active" ? "active" : "inactive"}`}>
                    {u.status}
                  </span>
                </td>
                <td className="mono small">{u.last_login || "Never"}</td>
                <td>
                  <button className="btn-sm btn-outline" onClick={() => handleToggleStatus(u)}>
                    {u.status === "active" ? "Deactivate" : "Activate"}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
