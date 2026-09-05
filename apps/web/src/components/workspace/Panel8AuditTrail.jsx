import React from "react";
import { formatDateTime } from "../../utils/formatters";

export default function Panel8AuditTrail({ auditLog }) {
  if (!auditLog || auditLog.length === 0) {
    return (
      <div className="workspace-panel">
        <div className="panel-header">
          <span className="panel-number">8</span>
          <h2>Audit Trail</h2>
        </div>
        <div className="panel-body">
          <div className="panel-empty">No audit entries yet. Actions will be logged as you work on this case.</div>
        </div>
      </div>
    );
  }

  const actionLabels = {
    case_created: "Case Created",
    pipeline_run: "Pipeline Executed",
    rerun_detection: "Detection Re-run",
    rerun_characterization: "Re-segmentation",
    rerun_origin: "Hindcast Re-run",
    rerun_forecast: "Forecast Re-run",
    rerun_ais: "AIS Re-search",
    rerun_attribution: "Attribution Re-run",
    rank_override: "Rank Override",
    status_change: "Status Change",
    note_added: "Note Added",
    returned_for_revision: "Returned for Revision",
    approved: "Approved",
    escalated: "Escalated",
    report_generated: "Report Generated",
  };

  return (
    <div className="workspace-panel">
      <div className="panel-header">
        <span className="panel-number">8</span>
        <h2>Audit Trail</h2>
      </div>
      <div className="panel-body">
        <div className="panel-card info-card">
          <p className="panel-note">This log is auto-generated and cannot be edited. It records every action taken during this investigation.</p>
        </div>

        <div className="audit-timeline">
          {auditLog.map((entry, i) => (
            <div className="audit-entry" key={entry.id || i}>
              <div className="audit-dot" />
              <div className="audit-content">
                <div className="audit-header">
                  <span className="audit-action">{actionLabels[entry.action_type] || entry.action_type}</span>
                  <span className="audit-time">{formatDateTime(entry.timestamp)}</span>
                </div>
                <div className="audit-actor">{entry.actor}</div>
                {entry.detail && (
                  <pre className="audit-detail">{JSON.stringify(entry.detail, null, 2)}</pre>
                )}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
