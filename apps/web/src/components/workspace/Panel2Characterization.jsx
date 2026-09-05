import React from "react";
import { formatArea, formatVolume } from "../../utils/formatters";

export default function Panel2Characterization({ data, readOnly, onResegment }) {
  if (!data) return <div className="panel-empty">Characterization data not available</div>;

  const char = data.characterization || {};
  const age = data.age || {};
  const perSlick = char.per_slick || [];

  return (
    <div className="workspace-panel">
      <div className="panel-header">
        <span className="panel-number">2</span>
        <h2>Characterization &amp; Age</h2>
      </div>
      <div className="panel-body">
        <div className="panel-stats-grid">
          <div className="panel-card stat-card">
            <span className="stat-label">Total Area</span>
            <span className="stat-value">{formatArea(char.total_area_km2)}</span>
          </div>
          <div className="panel-card stat-card">
            <span className="stat-label">Slick Count</span>
            <span className="stat-value">{char.slick_count || "—"}</span>
          </div>
          <div className="panel-card stat-card">
            <span className="stat-label">Volume (est.)</span>
            <span className="stat-value">{formatVolume(char.est_volume_m3)}</span>
          </div>
          <div className="panel-card stat-card">
            <span className="stat-label">Oil Type</span>
            <span className="stat-value">{char.likely_oil_type || "—"}</span>
          </div>
        </div>

        {perSlick.length > 0 && (
          <div className="panel-card">
            <h4>Per-Slick Breakdown</h4>
            <table className="panel-table">
              <thead>
                <tr><th>#</th><th>Area</th><th>Volume (m&sup3;)</th><th>Barrels</th><th>Tonnes</th></tr>
              </thead>
              <tbody>
                {perSlick.map((s, i) => (
                  <tr key={i}>
                    <td>{i + 1}</td>
                    <td>{formatArea(s.area_km2)}</td>
                    <td>{s.est_volume_m3?.toFixed(1) || "—"}</td>
                    <td>{s.est_volume_barrels?.toFixed(1) || "—"}</td>
                    <td>{s.est_volume_tonnes?.toFixed(1) || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {/* Age as interval with confidence */}
        {age.age_hours != null && (
          <div className="panel-card">
            <h4>Spill Age Estimate</h4>
            <div className="age-interval">
              <div className="age-range-display">
                <span className="age-min">{age.age_min_hours} hrs</span>
                <span className="age-arrow">&mdash;</span>
                <span className="age-max">{age.age_max_hours} hrs</span>
              </div>
              <div className="age-details">
                <span>Most likely: <strong>{age.age_hours} hours</strong></span>
                <span>Confidence: {Math.round((age.confidence || 0) * 100)}%</span>
                <span>Stage: {age.stage_label || "—"}</span>
                <span>Method: {age.method || "—"}</span>
              </div>
            </div>

            {age.mean_wind_ms != null && (
              <div className="panel-note">
                Wind correction: mean {age.mean_wind_ms} m/s, wind factor {age.wind_factor}x
                {age.wind_factor > 1 ? " (accelerated weathering)" : age.wind_factor < 1 ? " (slower weathering)" : " (neutral)"}
              </div>
            )}

            <div className="panel-note">
              Time since first observation: {age.age_min_hours}&ndash;{age.age_max_hours} hours
              (estimated time since release).
              Single-scene age inversion is inherently imprecise; wide brackets reflect genuine uncertainty.
            </div>

            {age.frames_used > 1 && (
              <div className="panel-note">Multi-pass bracket used ({age.frames_used} frames)</div>
            )}
          </div>
        )}

        {!readOnly && (
          <button className="btn-warning" onClick={onResegment}>
            Re-segment Detection
          </button>
        )}
      </div>
    </div>
  );
}
