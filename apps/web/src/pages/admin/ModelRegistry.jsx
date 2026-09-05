import React, { useState, useEffect } from "react";
import { apiGet, apiPost } from "../../api/client";

export default function ModelRegistry() {
  const [models, setModels] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showDeploy, setShowDeploy] = useState(false);
  const [form, setForm] = useState({ model_type: "detection", version_tag: "", notes: "" });

  useEffect(() => { loadModels(); }, []);

  const loadModels = async () => {
    setLoading(true);
    try {
      const data = await apiGet("/admin/models");
      setModels(data);
    } catch (err) { console.error(err); }
    finally { setLoading(false); }
  };

  const handleDeploy = async (e) => {
    e.preventDefault();
    try {
      await apiPost("/admin/models/deploy", form);
      setShowDeploy(false);
      setForm({ model_type: "detection", version_tag: "", notes: "" });
      loadModels();
    } catch (err) { alert(err.message); }
  };

  const handleRollback = async (modelId) => {
    if (confirm("Rollback to this version?")) {
      await apiPost(`/admin/models/${modelId}/rollback`, {});
      loadModels();
    }
  };

  if (loading) return <div className="loading">Loading model registry...</div>;

  return (
    <div className="page-container">
      <div className="page-header">
        <h1>Model Registry</h1>
        <button className="btn-primary" onClick={() => setShowDeploy(true)}>Deploy New Version</button>
      </div>

      {showDeploy && (
        <div className="create-user-form">
          <form onSubmit={handleDeploy}>
            <div className="form-grid">
              <div>
                <label>Model Type</label>
                <select value={form.model_type} onChange={(e) => setForm({ ...form, model_type: e.target.value })}>
                  <option value="detection">Detection (U-Net)</option>
                  <option value="transport">Transport (Lagrangian)</option>
                  <option value="attribution">Attribution Ranker</option>
                </select>
              </div>
              <div>
                <label>Version Tag</label>
                <input value={form.version_tag} onChange={(e) => setForm({ ...form, version_tag: e.target.value })} placeholder="e.g. v2.1.0" required />
              </div>
              <div>
                <label>Notes</label>
                <input value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} placeholder="Release notes..." />
              </div>
            </div>
            <div className="form-actions">
              <button type="button" className="btn-secondary" onClick={() => setShowDeploy(false)}>Cancel</button>
              <button type="submit" className="btn-primary">Deploy</button>
            </div>
          </form>
        </div>
      )}

      <table className="admin-table">
        <thead>
          <tr><th>Type</th><th>Version</th><th>Active</th><th>Deployed</th><th>Notes</th><th>Action</th></tr>
        </thead>
        <tbody>
          {models.map((m) => (
            <tr key={m.id}>
              <td><span className="type-badge">{m.model_type}</span></td>
              <td className="mono">{m.version_tag}</td>
              <td>
                <span className={`status-indicator ${m.is_active ? "active" : "inactive"}`}>
                  {m.is_active ? "LIVE" : "Archived"}
                </span>
              </td>
              <td className="mono small">{m.deployed_at}</td>
              <td className="small">{m.notes || "—"}</td>
              <td>
                {!m.is_active && (
                  <button className="btn-sm btn-outline" onClick={() => handleRollback(m.id)}>
                    Rollback
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
