import React from "react";
import { formatConfidence } from "../../utils/formatters";
import OilMap from "../OilMap";
import { buildMapFeatures } from "../../utils/mapFeatures";

export default function Panel1Detection({ data, readOnly, onFalsePositive }) {
  if (!data) return <div className="panel-empty">Detection data not available</div>;

  const confidence = data.overall_confidence || 0;
  const age = data.age || {};
  const fc = data.forecast || {};
  const gfw = data.gfw_available;
  const sar = data.sar_available;

  const decisionLabel = data.decision_label || computeDecisionLabel(confidence, data);
  const lookalikeRisk = data.lookalike_risk || computeLookalikeRisk(confidence);

  return (
    <div className="workspace-panel">
      <div className="panel-header">
        <span className="panel-number">1</span>
        <h2>Detection Result</h2>
      </div>
      <div className="panel-body">
        <div className="map-panel-embed">
          <OilMap
            features={buildMapFeatures(data, "detection")}
            center={data.origin_centroid || [72.8, 18.9]}
            initialZoom={9}
            height={260}
          />
          <div className="map-caption">Candidate spill polygon overlaid on detection scene</div>
        </div>

        <div className="panel-card">
          <h4>Decision Assessment</h4>
          <div className="decision-label" style={{ fontSize: "1.1em", fontWeight: 600, padding: "8px 0" }}>
            {decisionLabel}
          </div>
          <div className="detection-summary">
            <div className="detection-stat">
              <span className="stat-label">Confidence</span>
              <span className="stat-value" style={{ color: confidence > 0.7 ? "#10b981" : "#f59e0b" }}>
                {formatConfidence(confidence)}
              </span>
            </div>
            <div className="detection-stat">
              <span className="stat-label">Status</span>
              <span className="stat-value">{data.status || "—"}</span>
            </div>
            <div className="detection-stat">
              <span className="stat-label">SAR</span>
              <span className={`stat-badge ${sar ? "ok" : "warn"}`}>
                {sar ? "Available" : "Not Run"}
              </span>
            </div>
            <div className="detection-stat">
              <span className="stat-label">GFW AIS</span>
              <span className={`stat-badge ${gfw ? "ok" : "warn"}`}>
                {gfw ? "Connected" : "Unavailable"}
              </span>
            </div>
          </div>
        </div>

        {lookalikeRisk && (
          <div className="panel-card warning-card">
            <h4>Look-alike / False Detection Risk</h4>
            <div className="lookalike-breakdown">
              <div className="risk-item">
                <span className="stat-label">Risk Level</span>
                <span className="stat-value">{lookalikeRisk.level}</span>
              </div>
              {lookalikeRisk.contributing_factors && (
                <ul className="risk-factors">
                  {lookalikeRisk.contributing_factors.map((f, i) => (
                    <li key={i}>{f}</li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        )}

        {data.warnings && data.warnings.length > 0 && (
          <div className="panel-card warning-card">
            <h4>Warnings</h4>
            {data.warnings.map((w, i) => <p key={i}>{w}</p>)}
          </div>
        )}

        {!readOnly && (
          <button className="btn-danger" onClick={onFalsePositive}>
            Mark as False Positive
          </button>
        )}
      </div>
    </div>
  );
}

function computeDecisionLabel(confidence, data) {
  if (confidence >= 0.75) return "Likely oil spill";
  if (confidence >= 0.50) return "Probable oil spill";
  if (confidence >= 0.30) return "Uncertain / review required";
  return "Likely false detection";
}

function computeLookalikeRisk(confidence) {
  const risk = 1 - confidence;
  if (risk < 0.25) return null;
  const factors = [];
  if (confidence < 0.5) factors.push("Low model confidence");
  if (!data?.sar_available) factors.push("SAR data not run");
  if (risk >= 0.5) factors.push("High look-alike probability — requires manual review");
  return {
    level: risk >= 0.7 ? "High" : risk >= 0.5 ? "Medium" : "Low",
    contributing_factors: factors,
  };
}
