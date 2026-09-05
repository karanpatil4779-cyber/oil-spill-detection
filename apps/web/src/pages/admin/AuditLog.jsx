import React, { useState, useEffect } from "react";
import { apiGet } from "../../api/client";
import { formatDateTime } from "../../utils/formatters";

export default function AuditLog() {
  const [entries, setEntries] = useState([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState("");

  useEffect(() => { loadLog(); }, [filter]);

  const loadLog = async () => {
    setLoading(true);
    try {
      const params = filter ? `?action_type=${filter}` : "";
      const data = await apiGet(`/admin/audit-log${params}`);
      setEntries(data);
    } catch (err) { console.error(err); }
    finally { setLoading(false); }
  };

  const actionTypes = [
    "", "pipeline_run", "status_change", "rank_override",
    "returned_for_revision", "approved", "escalated",
    "case_created", "report_generated",
  ];

  return (
    <div className="page-container">
      <div className="page-header">
        <h1>Audit Log</h1>
        <p className="page-subtitle">System-level and account actions — no investigation content visible</p>
      </div>

      <div className="audit-filter">
        <label>Filter by action: </label>
        <select value={filter} onChange={(e) => setFilter(e.target.value)}>
          <option value="">All Actions</option>
          {actionTypes.filter(Boolean).map((t) => (
            <option key={t} value={t}>{t.replace(/_/g, " ")}</option>
          ))}
        </select>
      </div>

      {loading ? <div className="loading">Loading audit log...</div> : (
        <table className="admin-table">
          <thead>
            <tr><th>Timestamp</th><th>Actor</th><th>Action</th><th>Detail</th></tr>
          </thead>
          <tbody>
            {entries.map((e) => (
              <tr key={e.id}>
                <td className="mono small">{formatDateTime(e.timestamp)}</td>
                <td>{e.actor_name}</td>
                <td><span className="action-badge">{e.action_type.replace(/_/g, " ")}</span></td>
                <td className="mono small">
                  {e.detail ? JSON.stringify(e.detail) : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
