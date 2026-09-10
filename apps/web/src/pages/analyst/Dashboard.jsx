import React, { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { apiGet, apiPost } from "../../api/client";
import CaseTable from "../../components/CaseTable";

export default function AnalystDashboard() {
  const [cases, setCases] = useState([]);
  const [statusFilter, setStatusFilter] = useState("");
  const [loading, setLoading] = useState(true);
  const [rerunning, setRerunning] = useState(false);
  const [rerunMessage, setRerunMessage] = useState("");
  const navigate = useNavigate();

  useEffect(() => {
    loadCases();
  }, [statusFilter]);

  const loadCases = async () => {
    setLoading(true);
    try {
      const params = statusFilter ? `?status_filter=${statusFilter}` : "";
      const data = await apiGet(`/cases${params}`);
      setCases(data.cases || []);
    } catch (err) {
      console.error("Failed to load cases:", err);
    } finally {
      setLoading(false);
    }
  };

  const rerunAll = async () => {
    if (!window.confirm("Re-run the pipeline for ALL your cases? This runs SAR & Optical detection and may take several minutes per case.")) {
      return;
    }
    setRerunning(true);
    setRerunMessage("");
    try {
      const res = await apiPost("/cases/rerun-all", { run_sar: true });
      if (res.queued && res.queued.length) {
        setRerunMessage(
          `Queued pipeline runs for ${res.queued.length} case(s)${res.skipped && res.skipped.length ? `; skipped ${res.skipped.length} (already active)` : ""}. Refresh each case to follow progress.`
        );
      } else {
        setRerunMessage(res.skipped && res.skipped.length ? "No new runs queued — all cases already have an active run." : "No cases to re-run.");
      }
      loadCases();
    } catch (err) {
      setRerunMessage("Failed to re-run cases: " + err.message);
    } finally {
      setRerunning(false);
    }
  };

  return (
    <div className="page-container">
      <div className="page-header">
        <div>
          <h1>Investigation Dashboard</h1>
          <p className="page-subtitle">Your active oil spill investigations</p>
        </div>
        <div className="page-header-actions">
          <button
            className="btn-secondary"
            onClick={rerunAll}
            disabled={rerunning}
            title="Re-run the full pipeline (SAR + Optical) for every one of your cases"
          >
            {rerunning ? "Re-running…" : "Re-run all cases"}
          </button>
          <button className="btn-primary" onClick={() => navigate("/analyst/new")}>
            + New Investigation
          </button>
        </div>
      </div>
      {rerunMessage && <div className="rerun-banner">{rerunMessage}</div>}
      {loading ? (
        <div className="loading">Loading cases...</div>
      ) : (
        <CaseTable
          cases={cases}
          basePath="/analyst/case"
          statusFilter={statusFilter}
          onStatusFilter={setStatusFilter}
          showRerun
        />
      )}
    </div>
  );
}
