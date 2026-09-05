import React, { useState, useEffect } from "react";
import { apiGet, apiPut } from "../../api/client";

export default function DataSourceConfig() {
  const [sources, setSources] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => { loadSources(); }, []);

  const loadSources = async () => {
    setLoading(true);
    try {
      const data = await apiGet("/admin/data-sources");
      setSources(data);
    } catch (err) { console.error(err); }
    finally { setLoading(false); }
  };

  const handleToggle = async (source) => {
    await apiPut(`/admin/data-sources/${source.id}`, {
      source_type: source.source_type,
      name: source.name,
      endpoint: source.endpoint,
      refresh_interval_minutes: source.refresh_interval_minutes,
      is_active: !source.is_active,
    });
    loadSources();
  };

  if (loading) return <div className="loading">Loading data sources...</div>;

  return (
    <div className="page-container">
      <div className="page-header">
        <h1>Data Source Configuration</h1>
        <p className="page-subtitle">Manage external data feed endpoints and polling intervals</p>
      </div>

      <table className="admin-table">
        <thead>
          <tr><th>Source</th><th>Type</th><th>Endpoint</th><th>Refresh Interval</th><th>Status</th><th>Action</th></tr>
        </thead>
        <tbody>
          {sources.map((s) => (
            <tr key={s.id}>
              <td>{s.name}</td>
              <td><span className="type-badge">{s.source_type}</span></td>
              <td className="mono small">{s.endpoint || "—"}</td>
              <td>{s.refresh_interval_minutes} min</td>
              <td>
                <span className={`status-indicator ${s.is_active ? "active" : "inactive"}`}>
                  {s.is_active ? "Active" : "Disabled"}
                </span>
              </td>
              <td>
                <button className="btn-sm btn-outline" onClick={() => handleToggle(s)}>
                  {s.is_active ? "Disable" : "Enable"}
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
