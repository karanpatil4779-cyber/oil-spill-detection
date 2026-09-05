import React, { useState } from "react";
import OilMap from "../OilMap";
import { buildMapFeatures } from "../../utils/mapFeatures";

export default function Panel4ForwardForecast({ data, readOnly }) {
  const [horizon, setHorizon] = useState(72);

  if (!data?.forecast) return <div className="panel-empty">Forward forecast data not available. Pipeline may not have run the transport stage.</div>;

  const fc = data.forecast;
  const age = data.age || {};

  return (
    <div className="workspace-panel">
      <div className="panel-header">
        <span className="panel-number">4</span>
        <h2>Forward Forecast</h2>
      </div>
      <div className="panel-body">
        <div className="map-panel-embed">
          <OilMap
            features={buildMapFeatures(data, "forecast")}
            center={fc.centroid || [72.8, 18.9]}
            initialZoom={8}
            height={260}
          />
          <div className="map-caption">Spread cone / particle envelope at forecast horizon</div>
        </div>

        <div className="panel-card">
          <h4>Forecast Summary</h4>
          <div className="panel-stats-grid">
            <div className="stat-card">
              <span className="stat-label">Predicted Centre</span>
              <span className="stat-value mono">
                {fc.centroid?.[0]?.toFixed(4)}, {fc.centroid?.[1]?.toFixed(4)}
              </span>
            </div>
            <div className="stat-card">
              <span className="stat-label">Spread</span>
              <span className="stat-value">
                &plusmn;{fc.spread_deg?.[0]?.toFixed(3)}&deg; lon, &plusmn;{fc.spread_deg?.[1]?.toFixed(3)}&deg; lat
              </span>
            </div>
            <div className="stat-card">
              <span className="stat-label">Transport Confidence</span>
              <span className="stat-value">{Math.round((fc.confidence ?? 0) * 100)}%</span>
            </div>
            <div className="stat-card">
              <span className="stat-label">Particles Active</span>
              <span className="stat-value">{fc.particles_active || "—"}</span>
            </div>
          </div>
        </div>

        {/* Origin region from backward tracking */}
        {data.origin_bbox && (
          <div className="panel-card">
            <h4>Origin Region (Backward Hindcast)</h4>
            <p className="panel-note">
              Probable origin region: [{data.origin_bbox.map(x => x.toFixed(3)).join(", ")}]
              &mdash; this is an uncertainty-bounded region, not a pin-point location.
            </p>
            {age.age_min_hours != null && (
              <p className="panel-note">
                Time window: {age.age_min_hours}&ndash;{age.age_max_hours} hours before detection.
                When the age interval is wide, the origin region reflects multiple plausible release-time scenarios.
              </p>
            )}
          </div>
        )}

        {/* Wind/current forcing */}
        {fc.forcing_used && (
          <div className="panel-card">
            <h4>Wind / Current Forcing</h4>
            <div className="panel-note">
              {fc.forcing_used.winds && <span>Winds: {fc.forcing_used.winds} </span>}
              {fc.forcing_used.currents && <span>Currents: {fc.forcing_used.currents}</span>}
            </div>
          </div>
        )}

        {/* Scenarios */}
        {fc.scenario_count && (
          <div className="panel-card">
            <h4>Scenario Count</h4>
            <span className="stat-value">{fc.scenario_count} scenarios computed</span>
          </div>
        )}

        {!readOnly && (
          <div className="panel-card">
            <h4>Forecast Horizon</h4>
            <div className="horizon-buttons">
              {[24, 48, 72, 96, 120].map((h) => (
                <button
                  key={h}
                  className={`horizon-btn ${horizon === h ? "active" : ""}`}
                  onClick={() => setHorizon(h)}
                >
                  {h}h
                </button>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
