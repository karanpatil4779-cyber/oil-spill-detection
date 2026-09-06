import React from "react";
import { formatConfidence } from "../../utils/formatters";
import OilMap from "../OilMap";
import { buildMapFeatures } from "../../utils/mapFeatures";

/**
 * Panel 1 — Detection result.
 *
 * The decision label and its confidence come from the server
 * (`detection_assessment`, produced by engines/assessment.py). They are no
 * longer derived in the browser from `overall_confidence`, which measured
 * transport-particle retention and could report maximum certainty on a run
 * where the satellite was never contacted.
 */
export default function Panel1Detection({ data, readOnly, onFalsePositive }) {
  if (!data) return <div className="panel-empty">Detection data not available</div>;

  // Server-side assessment is authoritative. The local fallback exists only for
  // records written before this field was added, and it is labelled as such.
  const assessment = data.detection_assessment || localAssessment(data);
  const assessable = assessment.assessable !== false;
  const confidence = assessment.confidence;
  const decisionLabel = assessment.label;

  const detections = data.detections || [];
  const providers = data.provider_status || {};
  const transportConfidence =
    data.transport_age_confidence !== undefined
      ? data.transport_age_confidence
      : (data.forecast || {}).confidence;

  const sarState = providers.sar || (data.sar_requested === false ? "not_requested" : null);
  const gfwState = providers.gfw || null;
  const composite = data.composite_confidence || null;

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
          <div className="map-caption">
            {detections.length > 0
              ? "Candidate spill polygon overlaid on detection scene"
              : "No slick was detected — the marker is the operator-entered position, not an observation"}
          </div>
        </div>

        <div className="panel-card">
          <h4>Decision Assessment</h4>
          <div
            className="decision-label"
            style={{ fontSize: "1.1em", fontWeight: 600, padding: "8px 0" }}
          >
            {decisionLabel}
          </div>

          {!assessable && (
            <p className="assessment-note">
              No evidence bearing on the presence of oil is available for this run,
              so no determination can be made. This is not a negative finding.
            </p>
          )}

          <div className="detection-summary">
            <div className="detection-stat">
              <span className="stat-label">Detection confidence</span>
              <span
                className="stat-value"
                style={{ color: !assessable ? "#6b7280" : confidence > 0.7 ? "#10b981" : "#f59e0b" }}
              >
                {assessable && confidence !== null && confidence !== undefined
                  ? formatConfidence(confidence)
                  : "Not assessable"}
              </span>
            </div>
            <div className="detection-stat">
              <span className="stat-label">Evidence available</span>
              <span className="stat-value">
                {assessment.factors_available ?? 0} of {assessment.factors_total ?? 4}
              </span>
            </div>
            <div className="detection-stat">
              <span className="stat-label">Slicks detected</span>
              <span className="stat-value">{detections.length}</span>
            </div>
            <div className="detection-stat">
              <span className="stat-label">Drift-model confidence</span>
              <span className="stat-value" title="Particle retention in the current field — not evidence of oil">
                {transportConfidence !== null && transportConfidence !== undefined
                  ? formatConfidence(transportConfidence)
                  : "—"}
              </span>
            </div>
            <div className="detection-stat">
              <span className="stat-label">SAR</span>
              <span className={`stat-badge ${providerClass(sarState)}`}>
                {PROVIDER_TEXT[sarState] || (data.sar_available ? "Available" : "Not run")}
              </span>
            </div>
            <div className="detection-stat">
              <span className="stat-label">GFW AIS</span>
              <span className={`stat-badge ${providerClass(gfwState)}`}>
                {PROVIDER_TEXT[gfwState] || (data.gfw_available ? "Connected" : "Unavailable")}
              </span>
            </div>
            {composite && (
              <div className="detection-stat">
                <span className="stat-label">Composite confidence</span>
                <span
                  className="stat-value"
                  style={{ color: composite.score >= 0.7 ? "#10b981" : composite.score >= 0.4 ? "#f59e0b" : "#6b7280" }}
                  title={`Composed from: ${Object.keys(composite.components || {}).join(", ")} (geometric mean)`}
                >
                  {composite.label}
                  <span className="stat-sub"> ({formatConfidence(composite.score)})</span>
                </span>
              </div>
            )}
          </div>
        </div>

        {data.lookalike_filter && (
          <div className="panel-card">
            <h4>Look-alike screening</h4>
            <p className="panel-note">
              Biogenic slicks, low-wind films and wake artefacts were screened out
              before attribution. Flagged{" "}
              <strong>{data.lookalike_filter.flagged || 0}</strong> of{" "}
              <strong>{data.lookalike_filter.screened || 0}</strong> dark-spot
              candidate(s)
              {data.lookalike_filter.mean_wind_ms != null &&
                ` at mean wind ${data.lookalike_filter.mean_wind_ms.toFixed(1)} m/s`}
              .
            </p>
            {data.lookalike_filter.reasons?.length > 0 && (
              <ul className="risk-factors">
                {data.lookalike_filter.reasons.map((r, i) => <li key={i}>{r}</li>)}
              </ul>
            )}
          </div>
        )}

        {assessment.reasons && assessment.reasons.length > 0 && (
          <div className="panel-card warning-card">
            <h4>Basis for this assessment</h4>
            <ul className="risk-factors">
              {assessment.reasons.map((r, i) => <li key={i}>{r}</li>)}
            </ul>
          </div>
        )}

        {assessment.basis && (
          <div className="panel-card">
            <h4>Evidence factors</h4>
            <ul className="risk-factors">
              {Object.entries(assessment.basis).map(([key, f]) => (
                <li key={key}>
                  <strong>{FACTOR_NAMES[key] || key}</strong>{" — "}
                  {f.available
                    ? (f.detail || (f.value >= 0.5 ? "supports oil" : "does not support oil"))
                    : `unavailable: ${f.reason || "not computed"}`}
                </li>
              ))}
            </ul>
          </div>
        )}

        {data.warnings && data.warnings.length > 0 && (
          <div className="panel-card warning-card">
            <h4>Warnings ({data.warnings.length})</h4>
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

const FACTOR_NAMES = {
  sar_detection: "SAR dark-spot detection",
  optical_confirmation: "Sentinel-2 optical confirmation",
  volume_plausible: "Volume plausibility",
  age_plausible: "Age plausibility",
};

const PROVIDER_TEXT = {
  ok: "Returned data",
  ok_no_vessels: "Queried, no vessels",
  no_detections: "Scene clean",
  failed: "Failed",
  not_requested: "Not requested",
  no_particles: "No particles retained",
};

function providerClass(state) {
  if (state === "ok") return "ok";
  if (state === "failed") return "error";
  return "warn";
}

/**
 * Fallback for records stored before the server computed an assessment.
 * It reports "not assessable" rather than inventing a verdict, because the
 * fields those older records contain cannot support one.
 */
function localAssessment(data) {
  const detections = data.detections || [];
  if (detections.length === 0) {
    return {
      label: "Uncertain / review required",
      confidence: null,
      assessable: false,
      factors_available: 0,
      factors_total: 4,
      reasons: [
        "This case was recorded before server-side assessment existed, and it " +
          "contains no detections, so the presence of oil cannot be assessed.",
      ],
      basis: null,
    };
  }
  return {
    label: "Uncertain / review required",
    confidence: null,
    assessable: false,
    factors_available: 0,
    factors_total: 4,
    reasons: [
      "This case predates server-side assessment. Re-run the pipeline to obtain a verdict.",
    ],
    basis: null,
  };
}
