import React, { useState } from "react";
import OilMap from "../OilMap";
import { buildMapFeatures } from "../../utils/mapFeatures";

export default function Panel5AISVessels({ data, readOnly, onFilterChange, onRerun }) {
  const [radius, setRadius] = useState(50);
  const [timeBuffer, setTimeBuffer] = useState(6);

  if (!data) return <div className="panel-empty">AIS vessel data not available</div>;

  const suspects = (data.suspects || []).slice(0, 5);
  const totalSuspects = (data.suspects || []).length;
  const gfwAvailable = data.gfw_available;
  const hasFilterStats = data.ais_filter_stats;
  const totalInRegion = hasFilterStats ? data.ais_filter_stats.total_in_region : null;
  const afterFilter = suspects.length;

  return (
    <div className="workspace-panel">
      <div className="panel-header">
        <span className="panel-number">5</span>
        <h2>AIS / Vessel Candidates</h2>
      </div>
      <div className="panel-body">
        {!gfwAvailable && (
          <div className="panel-warning">
            AIS data source (Global Fishing Watch) was unavailable for this run. Results may be incomplete.
          </div>
        )}

        <div className="map-panel-embed">
          <OilMap
            features={buildMapFeatures(data, "ais")}
            center={data.origin_centroid || [72.8, 18.9]}
            initialZoom={8}
            height={240}
          />
          <div className="map-caption">Orange markers = candidate vessels scoped to origin region</div>
        </div>

        <div className="panel-card">
          <h4>Candidate Filtering</h4>
          {totalInRegion != null ? (
            <div className="reduction-ratio">
              <span className="reduction-from">{totalInRegion} vessels in search area</span>
              <span className="reduction-arrow">&rarr;</span>
              <span className="reduction-to">{afterFilter} candidates after filtering</span>
            </div>
          ) : (
            <div className="reduction-ratio">
              <span className="reduction-to">{afterFilter} top candidate vessel(s) identified</span>
            </div>
          )}
          {totalSuspects > suspects.length && (
            <div className="panel-note">
              Showing top {suspects.length} of {totalSuspects} candidate vessels by attribution rank.
            </div>
          )}
          {hasFilterStats && (
            <div className="filter-summary panel-note">
              {hasFilterStats.spatial_filtered != null && <span>Spatial filter: {hasFilterStats.spatial_filtered} &rarr; </span>}
              {hasFilterStats.temporal_filtered != null && <span>Temporal filter: {hasFilterStats.temporal_filtered} &rarr; </span>}
              {hasFilterStats.trajectory_matched != null && <span>Trajectory match: {hasFilterStats.trajectory_matched}</span>}
            </div>
          )}
        </div>

        {suspects.length > 0 ? (
          <div className="vessel-list">
            {suspects.map((s, i) => (
              <div className="panel-card vessel-card" key={s.vessel_id || s.mmsi || i}>
                <div className="vessel-header">
                  <span className="vessel-rank">#{i + 1}</span>
                  <span className="vessel-name">{s.vessel_name}</span>
                  {s.dark_vessel && (
                    <span className="dark-vessel-badge" title="SAR dark spot with no co-located AIS track">DARK</span>
                  )}
                  <span className="vessel-score">{s.attribution_score?.toFixed(2)}</span>
                </div>
                <div className="vessel-details">
                  <span>{s.dark_vessel ? "SAR-only (no AIS)" : `${s.ship_type} / ${s.cargo_type}`}</span>
                  <span>Flag: {s.flag || "—"}</span>
                  <span className="mono">MMSI: {s.mmsi}</span>
                </div>
                <div className="vessel-meta">
                  <span>Presence: {s.match_count || (s.dark_vessel ? "0 (no AIS)" : 0)}h</span>
                  <span>Last seen: {s.last_seen || "—"}</span>
                  {s.ais_gap_hours != null && (
                    <span className="ais-gap" title="Hours inside the origin window with no AIS transmissions">
                      AIS gap: {s.ais_gap_hours}h
                    </span>
                  )}
                </div>
                {s.signals && (
                  <div className="vessel-anomaly">
                    Behaviour anomaly: <span className="mono">{s.anomaly_score}</span>
                    <span className="small">({s.evidence})</span>
                  </div>
                )}
                {s.factors && (
                  <div className="vessel-factors panel-note">
                    {Object.entries(s.factors).map(([k, v]) => (
                      <span key={k} className="factor-tag">{k}: {typeof v === 'number' ? v.toFixed(2) : v}</span>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        ) : (
          <div className="panel-card">
            <p>No AIS vessels found matching current filters.</p>
            {!gfwAvailable && (
              <p className="panel-note">AIS data source was unavailable. Consider checking independent evidence sources (coastal radar, port records) if available.</p>
            )}
          </div>
        )}

        {!readOnly && (
          <div className="panel-card">
            <h4>Filter Thresholds</h4>
            <div className="filter-controls">
              <div className="filter-item">
                <label>Search Radius: {radius} km</label>
                <input
                  type="range" min="10" max="200" value={radius}
                  onChange={(e) => setRadius(Number(e.target.value))}
                />
              </div>
              <div className="filter-item">
                <label>Time Buffer: {timeBuffer} hrs</label>
                <input
                  type="range" min="1" max="24" value={timeBuffer}
                  onChange={(e) => setTimeBuffer(Number(e.target.value))}
                />
              </div>
              <button className="btn-secondary" onClick={() => onFilterChange?.({ radius, timeBuffer }) || onRerun?.()}>
                Re-run Candidate Search
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
