import React from "react";
import { formatConfidence } from "../../utils/formatters";

export default function Panel7DataQuality({ data, readOnly, onInsufficientEvidence }) {
  if (!data) return <div className="panel-empty">Data quality summary not available</div>;

  const confidence = data.overall_confidence || 0;
  const hasSAR = data.sar_available;
  const hasGFW = data.gfw_available;
  const warnings = data.warnings || [];
  const age = data.age || {};
  const fc = data.forecast || {};
  const char = data.characterization || {};

  const decisionLabel = data.decision_label || computeDecisionLabel(confidence);
  const isWeak = confidence < 0.5 || (!hasSAR && !hasGFW);

  const uncertaintyFactors = buildUncertaintyFactors(data);

  return (
    <div className="workspace-panel">
      <div className="panel-header">
        <span className="panel-number">7</span>
        <h2>Data Quality &amp; Uncertainty</h2>
      </div>
      <div className="panel-body">
        <div className="panel-card">
          <h4>Final Decision Label</h4>
          <div className="decision-label" style={{
            fontSize: "1.1em",
            fontWeight: 600,
            padding: "8px 0",
            color: isWeak ? "#f59e0b" : "#10b981",
          }}>
            {decisionLabel}
          </div>
          <p className="panel-note">
            This label is derived from the combined evidence of detector confidence,
            data availability, and uncertainty analysis.
          </p>
        </div>

        <div className="panel-stats-grid">
          <div className="panel-card stat-card">
            <span className="stat-label">Overall Confidence</span>
            <span className="stat-value" style={{ color: confidence > 0.7 ? "#10b981" : confidence > 0.5 ? "#f59e0b" : "#ef4444" }}>
              {formatConfidence(confidence)}
            </span>
          </div>
          <div className="panel-card stat-card">
            <span className="stat-label">Satellite Quality</span>
            <span className={`stat-badge ${hasSAR ? "ok" : "warn"}`}>
              {hasSAR ? "SAR Available" : "SAR Not Run"}
            </span>
          </div>
          <div className="panel-card stat-card">
            <span className="stat-label">AIS Completeness</span>
            <span className={`stat-badge ${hasGFW ? "ok" : "warn"}`}>
              {hasGFW ? "GFW Connected" : "GFW Unavailable"}
            </span>
          </div>
          <div className="panel-card stat-card">
            <span className="stat-label">Age Confidence</span>
            <span className="stat-value">
              {age.confidence != null ? Math.round(age.confidence * 100) + "%" : "N/A"}
            </span>
          </div>
        </div>

        {/* Uncertainty layer */}
        <div className="panel-card">
          <h4>Uncertainty Factors</h4>
          <p className="panel-note">Combined signals contributing to overall confidence:</p>
          <table className="panel-table">
            <thead>
              <tr><th>Factor</th><th>Status</th><th>Contribution</th></tr>
            </thead>
            <tbody>
              {uncertaintyFactors.map((f, i) => (
                <tr key={i}>
                  <td>{f.label}</td>
                  <td className={`stat-badge ${f.ok ? "ok" : "warn"}`}>{f.status}</td>
                  <td className="panel-note">{f.detail}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {isWeak && (
          <div className="panel-card warning-card">
            <h4>Weak Evidence</h4>
            <p>Overall confidence is low. This case may warrant an &quot;Insufficient Evidence&quot; closure rather than presenting uncertain findings as definitive.</p>
          </div>
        )}

        {warnings.length > 0 && (
          <div className="panel-card">
            <h4>Pipeline Warnings</h4>
            <ul className="warning-list">
              {warnings.map((w, i) => <li key={i}>{w}</li>)}
            </ul>
          </div>
        )}

        {!readOnly && isWeak && (
          <button className="btn-warning" onClick={onInsufficientEvidence}>
            Close as Insufficient Evidence
          </button>
        )}
      </div>
    </div>
  );
}

function computeDecisionLabel(confidence) {
  if (confidence >= 0.75) return "Likely oil spill";
  if (confidence >= 0.50) return "Probable oil spill";
  if (confidence >= 0.30) return "Uncertain / review required";
  return "Likely false detection";
}

function buildUncertaintyFactors(data) {
  const factors = [];
  const age = data.age || {};
  const fc = data.forecast || {};

  factors.push({
    label: "Detector / Model Confidence",
    status: data.overall_confidence > 0.7 ? "OK" : "Low",
    ok: data.overall_confidence > 0.7,
    detail: data.overall_confidence > 0.7 ? "Confidence above threshold" : `Confidence ${formatConfidence(data.overall_confidence)}`,
  });

  factors.push({
    label: "SAR Data Quality",
    status: data.sar_available ? "Available" : "Not Run",
    ok: !!data.sar_available,
    detail: data.sar_available ? "SAR scene processed" : "No SAR scene used in this run",
  });

  factors.push({
    label: "Temporal Persistence",
    status: age.frames_used > 1 ? "Multi-pass" : "Single pass",
    ok: age.frames_used > 1,
    detail: age.frames_used > 1 ? `${age.frames_used} SAR frames used` : "Single-scene age inversion is imprecise",
  });

  factors.push({
    label: "Age Estimation Confidence",
    status: (age.confidence || 0) > 0.5 ? "Adequate" : "Low",
    ok: (age.confidence || 0) > 0.5,
    detail: age.confidence != null ? `${Math.round(age.confidence * 100)}%` : "Not estimated",
  });

  factors.push({
    label: "Weather / Current Consistency",
    status: fc.confidence > 0.5 ? "Adequate" : fc.confidence ? "Low" : "Unknown",
    ok: fc.confidence > 0.5,
    detail: fc.confidence != null ? `Transport confidence: ${Math.round(fc.confidence * 100)}%` : "No forecast computed",
  });

  factors.push({
    label: "AIS / Vessel Evidence",
    status: data.gfw_available ? "Connected" : "Unavailable",
    ok: !!data.gfw_available,
    detail: data.gfw_available ? "GFW presence data used" : "GFW unavailable; fallback evidence sources not yet configured",
  });

  factors.push({
    label: "Characterisation Quality",
    status: data.characterization ? "Available" : "Not computed",
    ok: !!data.characterization,
    detail: data.characterization ? `Type: ${data.characterization.likely_oil_type || "Unknown"}` : "No characterisation computed",
  });

  return factors;
}
