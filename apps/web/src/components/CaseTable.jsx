import React, { useState } from "react";
import { useNavigate } from "react-router-dom";
import StatusBadge from "./StatusBadge";
import ConfidenceGauge from "./ConfidenceGauge";
import { formatDate } from "../utils/formatters";
import { apiPost } from "../api/client";

export default function CaseTable({ cases, basePath, statusFilter, onStatusFilter, showRerun = false }) {
  const navigate = useNavigate();
  const [runState, setRunState] = useState({}); // case_id -> message

  const statuses = ["", "in_progress", "pending_review", "returned", "approved", "closed", "insufficient_evidence"];
  const statusLabels = {
    "": "All Statuses",
    in_progress: "In Progress",
    pending_review: "Pending Review",
    returned: "Returned",
    approved: "Approved",
    closed: "Closed",
    insufficient_evidence: "Insufficient Evidence",
  };

  const runCase = async (e, id, caseNumber) => {
    e.stopPropagation();
    if (!window.confirm(`Re-run the pipeline for ${caseNumber}? This runs SAR & Optical detection for this case.`)) {
      return;
    }
    setRunState((s) => ({ ...s, [id]: "Re-running…" }));
    try {
      const res = await apiPost(`/cases/${id}/runs`, { run_sar: true });
      setRunState((s) => ({
        ...s,
        [id]: res.status === "queued" || res.status === "running"
          ? `Queued (${res.run_id.slice(0, 8)}…)`
          : "Run completed",
      }));
    } catch (err) {
      setRunState((s) => ({ ...s, [id]: `Failed: ${err.message}` }));
    }
  };

  return (
    <div className="case-table-wrapper">
      <div className="case-table-filters">
        <select value={statusFilter || ""} onChange={(e) => onStatusFilter(e.target.value)}>
          {statuses.map((s) => (
            <option key={s} value={s}>{statusLabels[s]}</option>
          ))}
        </select>
        <span className="case-count">{cases.length} case{cases.length !== 1 ? "s" : ""}</span>
      </div>
      <table className="case-table">
        <thead>
          <tr>
            <th>Case ID</th>
            <th>Analyst</th>
            <th>Location</th>
            <th>Detection Date</th>
            <th>Confidence</th>
            <th>Status</th>
            {showRerun && <th>Actions</th>}
          </tr>
        </thead>
        <tbody>
          {cases.length === 0 && (
            <tr><td colSpan={showRerun ? 7 : 6} className="empty-row">No cases found</td></tr>
          )}
          {cases.map((c) => (
            <tr key={c.id} onClick={() => navigate(`${basePath}/${c.id}`)} className="clickable-row">
              <td className="mono">{c.case_number}</td>
              <td>{c.analyst_name}</td>
              <td>{c.location_name || "—"}</td>
              <td>{formatDate(c.detection_date)}</td>
              <td><ConfidenceGauge score={c.overall_confidence} /></td>
              <td><StatusBadge status={c.status} /></td>
              {showRerun && (
                <td>
                  <div className="case-row-actions">
                    <button
                      className="btn-secondary btn-sm"
                      onClick={(e) => runCase(e, c.id, c.case_number)}
                      disabled={!!runState[c.id]}
                      title="Re-run the full pipeline (SAR + Optical) for this case"
                    >
                      Re-run
                    </button>
                    {runState[c.id] && <span className="case-row-status">{runState[c.id]}</span>}
                  </div>
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}