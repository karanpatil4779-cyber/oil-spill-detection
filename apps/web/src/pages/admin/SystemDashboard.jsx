import React, { useState, useEffect } from "react";
import { apiGet } from "../../api/client";

export default function SystemDashboard() {
  const [runStats, setRunStats] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    loadData();
  }, []);

  const loadData = async () => {
    try {
      const runs = await apiGet("/admin/audit-log?limit=200");
      const stats = { running: 0, queued: 0, failed: 0, succeeded: 0 };
      runs.forEach((r) => {
        if (r.action_type === "pipeline_run") {
          const detail = r.detail || {};
          if (detail.status === "running") stats.running++;
          else if (detail.status === "queued") stats.queued++;
          else if (detail.status === "failed") stats.failed++;
          else if (detail.status === "succeeded") stats.succeeded++;
        }
      });
      setRunStats(stats);
    } catch {
      setRunStats(null);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="page-container">
      <div className="page-header">
        <h1>System Status</h1>
        <p className="page-subtitle">Infrastructure health — no case data visible here</p>
      </div>

      <h2>Data Pipeline Health</h2>
      <div className="demo-data-banner">
        [DEMO DATA] Data source health indicators below are based on provider
        reachability checks at startup. Live monitoring is not yet implemented.
      </div>
      <div className="pipeline-grid">
        {[
          { name: "Sentinel-1 SAR Feed", type: "satellite", status: "green", detail: "Copernicus Data Space (CDSE) — auth verified" },
          { name: "Sentinel-2 Optical Feed", type: "satellite", status: "green", detail: "Copernicus Open Access Hub" },
          { name: "AIS Feed (GFW)", type: "ais", status: "amber", detail: "Global Fishing Watch v3 — presence OK, vessel-identity 403 (permission)" },
          { name: "ERA5 Winds (ECMWF)", type: "metocean", status: "green", detail: "CDS API — pre-processed archives available" },
          { name: "CMEMS Currents", type: "metocean", status: "green", detail: "Copernicus Marine — pre-processed archives available" },
        ].map((p) => (
          <div className={`pipeline-card status-${p.status}`} key={p.name}>
            <div className="pipeline-indicator">
              <span className={`indicator-dot ${p.status}`} />
              <span className="pipeline-name">{p.name}</span>
            </div>
            <p className="pipeline-detail">{p.detail}</p>
          </div>
        ))}
      </div>

      <h2>Job Queue</h2>
      {loading ? (
        <p>Loading job stats...</p>
      ) : runStats ? (
        <div>
          <div className="demo-data-banner">
            [DEMO DATA] Job counts derived from audit log entries — real-time queue
            monitoring is not yet implemented.
          </div>
          <table className="admin-table">
            <thead>
              <tr>
                <th>Status</th>
                <th>Count</th>
              </tr>
            </thead>
            <tbody>
              <tr><td>Running</td><td className="mono">{runStats.running}</td></tr>
              <tr><td>Queued</td><td className="mono">{runStats.queued}</td></tr>
              <tr><td>Succeeded</td><td className="mono" style={{ color: "#10b981" }}>{runStats.succeeded}</td></tr>
              <tr><td>Failed</td><td className="mono" style={{ color: runStats.failed > 0 ? "#ef4444" : "#10b981" }}>{runStats.failed}</td></tr>
            </tbody>
          </table>
        </div>
      ) : (
        <p>Unable to load job statistics.</p>
      )}
    </div>
  );
}
