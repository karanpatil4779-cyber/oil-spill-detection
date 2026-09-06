import React, { useState, useEffect, useCallback } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { apiGet, apiPost, apiPatch } from "../../api/client";
import StatusBadge from "../../components/StatusBadge";
import { formatDateTime } from "../../utils/formatters";
import Panel1Detection from "../../components/workspace/Panel1Detection";
import Panel2Characterization from "../../components/workspace/Panel2Characterization";
import Panel3OriginHindcast from "../../components/workspace/Panel3OriginHindcast";
import Panel4ForwardForecast from "../../components/workspace/Panel4ForwardForecast";
import Panel5AISVessels from "../../components/workspace/Panel5AISVessels";
import Panel6Attribution from "../../components/workspace/Panel6Attribution";
import Panel7DataQuality from "../../components/workspace/Panel7DataQuality";
import Panel8AuditTrail from "../../components/workspace/Panel8AuditTrail";

const STAGE_LABELS = {
  queued: "Queued",
  detection: "SAR Detection",
  characterization: "Characterization",
  metocean: "Metocean Forcing",
  transport: "Transport / Hindcast",
  aging: "Age Estimation",
  forecast: "Forward Forecast",
  eo: "Optical Confirmation",
  ais: "AIS Vessel Search",
  attribution: "Attribution Ranking",
  complete: "Complete",
};

export default function Workspace() {
  const { caseId } = useParams();
  const navigate = useNavigate();
  const [caseData, setCaseData] = useState(null);
  const [auditLog, setAuditLog] = useState([]);
  const [loading, setLoading] = useState(true);
  const [runStatus, setRunStatus] = useState(null);
  const [supervisorNote, setSupervisorNote] = useState(null);

  const loadCase = useCallback(async () => {
    try {
      const data = await apiGet(`/cases/${caseId}`);
      setCaseData(data);

      const notes = await apiGet(`/cases/${caseId}/notes`);
      const returnNote = notes.find((n) => n.is_supervisor_return);
      if (returnNote) setSupervisorNote(returnNote);

      const audit = await apiGet(`/cases/${caseId}/audit`);
      setAuditLog(audit);
    } catch (err) {
      console.error("Failed to load case:", err);
    }
  }, [caseId]);

  useEffect(() => {
    setLoading(true);
    loadCase().finally(() => setLoading(false));
  }, [loadCase]);

  const startPipeline = async () => {
    try {
      const res = await apiPost(`/cases/${caseId}/runs`, { run_sar: false });
      setRunStatus({ run_id: res.run_id, status: res.status });
      await loadCase();
      pollRun(res.run_id);
    } catch (err) {
      alert("Pipeline failed to start: " + err.message);
    }
  };

  const pollRun = useCallback((runId) => {
    let attempts = 0;
    const maxAttempts = 300;
    const timer = setInterval(async () => {
      attempts++;
      try {
        const run = await apiGet(`/cases/${caseId}/runs/${runId}`);
        setRunStatus(run);
        if (run.status === "succeeded" || run.status === "failed" || run.status === "cancelled" || attempts >= maxAttempts) {
          clearInterval(timer);
          setRunStatus(null);
          loadCase();
        }
      } catch {
        clearInterval(timer);
        setRunStatus(null);
        loadCase();
      }
    }, 3000);
  }, [caseId, loadCase]);

  const handleSubmitForReview = async () => {
    try {
      await apiPatch(`/cases/${caseId}/status`, { status: "pending_review" });
      loadCase();
    } catch (err) {
      alert("Failed to submit: " + err.message);
    }
  };

  const handleGenerateReport = async () => {
    try {
      const res = await apiPost(`/cases/${caseId}/generate-report`, {});
      alert(`Report generated: ${res.pdf_path}`);
    } catch (err) {
      alert("Report generation failed: " + err.message);
    }
  };

  const handleOverrideRank = async (override) => {
    try {
      await apiPost(`/cases/${caseId}/override-rank`, override);
      loadCase();
    } catch (err) {
      alert("Override failed: " + err.message);
    }
  };

  const handleRerun = async (stage, params) => {
    try {
      await apiPost(`/cases/${caseId}/rerun`, { stage, params: params || {} });
      loadCase();
    } catch (err) {
      alert(`Re-run failed: ${err.message}`);
    }
  };

  const handleInsufficientEvidence = async () => {
    try {
      await apiPatch(`/cases/${caseId}/status`, { status: "insufficient_evidence" });
      loadCase();
    } catch (err) {
      alert("Failed to close as insufficient evidence: " + err.message);
    }
  };

  const handleFalsePositive = async () => {
    try {
      await apiPatch(`/cases/${caseId}/status`, { status: "closed" });
      loadCase();
    } catch (err) {
      alert("Failed to mark as false positive: " + err.message);
    }
  };

  if (loading) return <div className="loading">Loading case workspace...</div>;
  if (!caseData) return <div className="error">Case not found</div>;

  const result = caseData.pipeline_result || {};
  const isEditable = caseData.status === "in_progress" || caseData.status === "returned";
  const pipelineStatus = caseData.pipeline_status || "idle";
  const hasData = !!(result && result.incident_id);
  const isRunning = pipelineStatus === "running" || runStatus?.status === "running" || runStatus?.status === "queued";

  return (
    <div className="workspace-container">
      <div className="workspace-topbar">
        <button className="btn-back" onClick={() => navigate("/analyst")}>
          &larr; Dashboard
        </button>
        <div className="workspace-title">
          <span className="case-number">{caseData.case_number}</span>
          <StatusBadge status={caseData.status} />
          <span className="case-updated">
            Updated: {formatDateTime(caseData.updated_at)}
          </span>
        </div>
        <div className="workspace-actions">
          {isEditable && !hasData && !isRunning && (
            <button className="btn-primary" onClick={startPipeline}>
              Run Pipeline
            </button>
          )}
          {hasData && isEditable && (
            <>
              <button className="btn-secondary" onClick={handleGenerateReport}>
                Generate Report
              </button>
              <button className="btn-primary" onClick={handleSubmitForReview}>
                Submit for Review
              </button>
            </>
          )}
        </div>
      </div>

      {supervisorNote && (
        <div className="supervisor-return-note">
          <h4>&#8617; Returned by Supervisor: {supervisorNote.author_name}</h4>
          <p>{supervisorNote.content}</p>
          <span className="note-time">
            {formatDateTime(supervisorNote.created_at)}
          </span>
        </div>
      )}

      {/* Run Progress Bar */}
      {isRunning && runStatus && (
        <div className="run-progress-container">
          <div className="run-progress-header">
            <span className="run-progress-label">
              {STAGE_LABELS[runStatus.current_stage] || runStatus.current_stage || "Starting..."}
            </span>
            <span className="run-progress-pct">{Math.round(runStatus.progress_percent || 0)}%</span>
          </div>
          <div className="run-progress-bar">
            <div
              className="run-progress-fill"
              style={{ width: `${runStatus.progress_percent || 0}%` }}
            />
          </div>
          <div className="run-progress-stage">
            Run ID: {runStatus.run_id} | Status: {runStatus.status}
            {runStatus.error_details && (
              <span className="run-error">
                {" "}&mdash; Error: {runStatus.error_details.message || "Unknown error"}
              </span>
            )}
          </div>
        </div>
      )}

      {/* Empty state */}
      {!hasData && !isRunning && (
        <div className="workspace-empty">
          <div className="empty-prompt">
            <h2>Ready to Investigate</h2>
            <p>
              This case has been created but the detection pipeline hasn't been
              run yet.
            </p>
            <p>
              <strong>Location:</strong>{" "}
              {caseData.lon?.toFixed(4)}, {caseData.lat?.toFixed(4)}
            </p>
            <p>
              <strong>Date:</strong> {caseData.detection_date}
            </p>
            <button className="btn-primary btn-lg" onClick={startPipeline}>
              Run Detection Pipeline
            </button>
          </div>
        </div>
      )}

      {/* Results panels — only render after pipeline succeeded */}
      {hasData && (
        <div className="workspace-panels">
          <Panel1Detection data={result} readOnly={!isEditable} onFalsePositive={handleFalsePositive} />
          <Panel2Characterization data={result} readOnly={!isEditable} onResegment={() => handleRerun("characterization")} />
          <Panel3OriginHindcast data={result} readOnly={!isEditable} onChangeSource={(src) => handleRerun("origin", { source: src })} onRerun={() => handleRerun("origin")} />
          <Panel4ForwardForecast data={result} readOnly={!isEditable} />
          <Panel5AISVessels data={result} readOnly={!isEditable} onFilterChange={(f) => handleRerun("ais", { radius: f.radius, time_buffer: f.timeBuffer })} />
          <Panel6Attribution data={result} readOnly={!isEditable} onOverrideRank={handleOverrideRank} />
          <Panel7DataQuality data={result} readOnly={!isEditable} onInsufficientEvidence={handleInsufficientEvidence} />
          <Panel8AuditTrail auditLog={auditLog} />
        </div>
      )}

      {pipelineStatus === "error" && (
        <div className="workspace-error">
          <h3>Pipeline Error</h3>
          <p>The pipeline encountered an error. Check the run status or re-run.</p>
          {result.warnings && result.warnings.length > 0 && (
            <ul className="warning-list">
              {result.warnings.map((w, i) => <li key={i}>{w}</li>)}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
