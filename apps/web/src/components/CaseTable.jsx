import React from "react";
import { useNavigate } from "react-router-dom";
import StatusBadge from "./StatusBadge";
import ConfidenceGauge from "./ConfidenceGauge";
import { formatDate } from "../utils/formatters";

export default function CaseTable({ cases, basePath, statusFilter, onStatusFilter }) {
  const navigate = useNavigate();

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
          </tr>
        </thead>
        <tbody>
          {cases.length === 0 && (
            <tr><td colSpan={6} className="empty-row">No cases found</td></tr>
          )}
          {cases.map((c) => (
            <tr key={c.id} onClick={() => navigate(`${basePath}/${c.id}`)} className="clickable-row">
              <td className="mono">{c.case_number}</td>
              <td>{c.analyst_name}</td>
              <td>{c.location_name || "—"}</td>
              <td>{formatDate(c.detection_date)}</td>
              <td><ConfidenceGauge score={c.overall_confidence} /></td>
              <td><StatusBadge status={c.status} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
