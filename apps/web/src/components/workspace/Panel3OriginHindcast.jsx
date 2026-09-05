import React from "react";
import OilMap from "../OilMap";
import { buildMapFeatures } from "../../utils/mapFeatures";

export default function Panel3OriginHindcast({ data, readOnly, onChangeSource, onRerun }) {
  if (!data) return <div className="panel-empty">Origin/hindcast data not available</div>;

  const centroid = data.origin_centroid;
  const bbox = data.origin_bbox;
  const age = data.age || {};

  return (
    <div className="workspace-panel">
      <div className="panel-header">
        <span className="panel-number">3</span>
        <h2>Origin / Hindcast</h2>
      </div>
      <div className="panel-body">
        <div className="map-panel-embed">
          <OilMap
            features={buildMapFeatures(data, "origin")}
            center={centroid || [72.8, 18.9]}
            initialZoom={8}
            height={260}
          />
          <div className="map-caption">Shaded region = probable origin area with uncertainty bounds</div>
        </div>

        {centroid ? (
          <div className="panel-card">
            <h4>Probable Origin</h4>
            <div className="origin-stats">
              <div className="origin-stat">
                <span className="stat-label">Centroid</span>
                <span className="stat-value mono">{centroid[0].toFixed(4)}, {centroid[1].toFixed(4)}</span>
              </div>
              {bbox && (
                <div className="origin-stat">
                  <span className="stat-label">Uncertainty Region (BBox)</span>
                  <span className="stat-value mono small">
                    [{bbox.map((x) => x.toFixed(3)).join(", ")}]
                  </span>
                </div>
              )}
            </div>
            <p className="panel-note">
              Shaded region represents the probable origin area with uncertainty bounds.
              This is <strong>not</strong> a pin-point location. When the age interval is wide,
              multiple plausible release-time scenarios contribute to this region.
            </p>
          </div>
        ) : (
          <div className="panel-card">
            <p>No origin estimate available. Pipeline may not have run the transport stage.</p>
          </div>
        )}

        {/* Time window from age estimation */}
        {age.age_hours != null && (
          <div className="panel-card">
            <h4>Probable Time Window</h4>
            <p>
              Spill likely occurred <strong>{age.age_min_hours}&ndash;{age.age_max_hours} hours</strong> before detection.
            </p>
            {age.confidence != null && (
              <p className="panel-note">Age confidence: {Math.round(age.confidence * 100)}%</p>
            )}
            {age.method && (
              <p className="panel-note">Method: {age.method}</p>
            )}
            {age.stage_label && (
              <p className="panel-note">Stage: {age.stage_label}</p>
            )}
            {age.mean_wind_ms != null && (
              <p className="panel-note">
                Mean wind: {age.mean_wind_ms} m/s (wind factor: {age.wind_factor}x)
              </p>
            )}
            <p className="panel-note">
              Assumptions: single-pass SAR contrast inversion with wind correction.
              Single-scene age inversion is inherently imprecise; wide brackets reflect genuine uncertainty.
            </p>
          </div>
        )}

        {/* Multi-scenario note when age interval is wide */}
        {age.age_hours != null && (age.age_max_hours - age.age_min_hours) > 24 && (
          <div className="panel-card">
            <h4>Multi-Scenario Origin</h4>
            <p className="panel-note">
              The age interval spans {Math.round(age.age_max_hours - age.age_min_hours)} hours.
              Multiple plausible release-time scenarios have been considered to compute this origin region.
              Earlier release times shift the origin further from the detection location.
            </p>
          </div>
        )}

        {!readOnly && (
          <div className="panel-actions">
            <div className="form-section">
              <label>Metocean Forcing Source</label>
              <select onChange={(e) => onChangeSource?.(e.target.value)}>
                <option value="era5_cmems">ERA5 winds + CMEMS currents (default)</option>
                <option value="era5_only">ERA5 only (winds + reconstructed currents)</option>
                <option value="gfs_cmems">GFS winds + CMEMS currents</option>
              </select>
            </div>
            <button className="btn-secondary" onClick={onRerun}>
              Re-run Hindcast
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
