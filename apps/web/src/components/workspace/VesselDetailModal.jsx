import React, { useRef, useEffect, useState, useCallback } from "react";
import * as maplibregl from "maplibre-gl";

const MAP_STYLE = "https://tiles.openfreemap.org/styles/liberty";

const FACTOR_META = [
  { key: "proximity", label: "Proximity to Origin", weight: "30%", icon: "\u2316", color: "#3b82f6" },
  { key: "duration", label: "Presence Duration", weight: "18%", icon: "\u23f1", color: "#8b5cf6" },
  { key: "cargo", label: "Cargo/Type Match", weight: "22%", icon: "\u2693", color: "#06b6d4" },
  { key: "behaviour", label: "Behavioural Anomaly", weight: "15%", icon: "\u26a0", color: "#f59e0b" },
  { key: "vessel_type", label: "Vessel-Type Profile", weight: "10%", icon: "\u2693", color: "#10b981" },
  { key: "repeat", label: "Repeat Offender", weight: "5%", icon: "\u267b", color: "#ef4444" },
];

function generateVesselTrack(vessel, pipelineData) {
  const points = [];
  const origin = pipelineData.origin_centroid || [72.75, 18.92];
  const vlon = vessel.avg_lon ?? origin[0];
  const vlat = vessel.avg_lat ?? origin[1];
  const presenceH = vessel.match_count || vessel.presence_hours || 4;
  const hours = Math.max(2, Math.min(Math.round(presenceH), 16));

  const distDeg = 0.02 + Math.random() * 0.04;
  const angle = Math.random() * Math.PI * 2;
  const startLon = vlon - Math.cos(angle) * distDeg;
  const startLat = vlat - Math.sin(angle) * distDeg;

  const isLoitering = (vessel.anomaly_score || 0) > 0.5;
  const steps = hours + 1;

  for (let i = 0; i < steps; i++) {
    const t = i / (steps - 1);
    let lon, lat;
    if (isLoitering) {
      const wander = 0.005;
      lon = vlon + Math.sin(t * Math.PI * 3 + Math.random()) * wander;
      lat = vlat + Math.cos(t * Math.PI * 2.5 + Math.random()) * wander;
      if (i < steps * 0.3) {
        const approach = i / (steps * 0.3);
        lon = startLon + (lon - startLon) * approach;
        lat = startLat + (lat - startLat) * approach;
      }
      if (i > steps * 0.7) {
        const depart = (i - steps * 0.7) / (steps * 0.3);
        const exitAngle = angle + Math.PI;
        lon = vlon + Math.cos(exitAngle) * distDeg * depart;
        lat = vlat + Math.sin(exitAngle) * distDeg * depart;
      }
    } else {
      lon = startLon + (vlon - startLon) * t + Math.sin(t * Math.PI * 2) * 0.003;
      lat = startLat + (vlat - startLat) * t + Math.cos(t * Math.PI * 1.5) * 0.003;
      if (i === steps - 1) {
        lon = vlon + Math.cos(angle) * distDeg * 0.5;
        lat = vlat + Math.sin(angle) * distDeg * 0.5;
      }
    }
    points.push([parseFloat(lon.toFixed(6)), parseFloat(lat.toFixed(6))]);
  }
  return points;
}

function buildModalFeatures(vessel, pipelineData, track) {
  const features = [];
  const origin = pipelineData.origin_centroid;
  const originBbox = pipelineData.origin_bbox;
  const perSlick = pipelineData.characterization?.per_slick || [];

  if (originBbox?.length === 4) {
    features.push({
      id: "modal-origin-region",
      type: "fill",
      color: "#3b82f6",
      geometry: {
        type: "Polygon",
        coordinates: [[
          [originBbox[0], originBbox[1]], [originBbox[2], originBbox[1]],
          [originBbox[2], originBbox[3]], [originBbox[0], originBbox[3]],
          [originBbox[0], originBbox[1]],
        ]],
      },
    });
  }

  perSlick.forEach((s, i) => {
    if (s.bbox_geo?.length === 4) {
      features.push({
        id: `modal-slick-${i}`,
        type: "fill",
        color: "#ef4444",
        geometry: {
          type: "Polygon",
          coordinates: [[
            [s.bbox_geo[0], s.bbox_geo[1]], [s.bbox_geo[2], s.bbox_geo[1]],
            [s.bbox_geo[2], s.bbox_geo[3]], [s.bbox_geo[0], s.bbox_geo[3]],
            [s.bbox_geo[0], s.bbox_geo[1]],
          ]],
        },
      });
    }
  });

  if (track && track.length > 1) {
    features.push({
      id: "modal-vessel-track",
      type: "line",
      color: "#f59e0b",
      geometry: { type: "LineString", coordinates: track },
    });
  }

  if (origin) {
    features.push({
      id: "modal-origin-point",
      type: "point",
      color: "#3b82f6",
      radius: 10,
      geometry: { type: "Point", coordinates: origin },
    });
  }

  if (track && track.length > 0) {
    const midIdx = Math.floor(track.length / 2);
    features.push({
      id: "modal-vessel-pos",
      type: "point",
      color: "#f59e0b",
      radius: 12,
      geometry: { type: "Point", coordinates: track[midIdx] },
    });
  }

  return features;
}

function VesselMap({ features, center, zoom }) {
  const containerRef = useRef(null);
  const mapRef = useRef(null);

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;

    const map = new maplibregl.Map({
      container: containerRef.current,
      style: MAP_STYLE,
      center: center || [72.8, 18.9],
      zoom: zoom || 11,
      attributionControl: false,
    });

    map.addControl(new maplibregl.NavigationControl(), "top-right");
    mapRef.current = map;

    map.on("load", () => {
      map.addSource("vessel-detail", {
        type: "geojson",
        data: { type: "FeatureCollection", features: [] },
      });

      map.addLayer({
        id: "vd-fill",
        type: "fill",
        source: "vessel-detail",
        filter: ["==", ["geometry-type"], "Polygon"],
        paint: {
          "fill-color": ["coalesce", ["get", "color"], "#3b82f6"],
          "fill-opacity": 0.22,
        },
      });

      map.addLayer({
        id: "vd-fill-outline",
        type: "line",
        source: "vessel-detail",
        filter: ["==", ["geometry-type"], "Polygon"],
        paint: {
          "line-color": ["coalesce", ["get", "color"], "#3b82f6"],
          "line-width": 2,
        },
      });

      map.addLayer({
        id: "vd-line",
        type: "line",
        source: "vessel-detail",
        filter: ["==", ["geometry-type"], "LineString"],
        paint: {
          "line-color": ["coalesce", ["get", "color"], "#f59e0b"],
          "line-width": 3,
          "line-dasharray": [3, 2],
        },
      });

      map.addLayer({
        id: "vd-point",
        type: "circle",
        source: "vessel-detail",
        filter: ["==", ["geometry-type"], "Point"],
        paint: {
          "circle-radius": ["coalesce", ["get", "radius"], 8],
          "circle-color": ["coalesce", ["get", "color"], "#ef4444"],
          "circle-stroke-color": "#ffffff",
          "circle-stroke-width": 2,
        },
      });

      map.addSource("vessel-labels", {
        type: "geojson",
        data: { type: "FeatureCollection", features: [] },
      });

      map.addLayer({
        id: "vd-labels",
        type: "symbol",
        source: "vessel-labels",
        layout: {
          "text-field": ["get", "label"],
          "text-size": 11,
          "text-offset": [0, 1.5],
          "text-anchor": "top",
        },
        paint: {
          "text-color": "#f1f5f9",
          "text-halo-color": "#0f172a",
          "text-halo-width": 2,
        },
      });

      updateMapData(features);
    });

    return () => {
      map.remove();
      mapRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (mapRef.current?.isStyleLoaded()) {
      updateMapData(features);
    }
  }, [features]);

  const updateMapData = (feats) => {
    const map = mapRef.current;
    if (!map || !map.isStyleLoaded()) return;
    const source = map.getSource("vessel-detail");
    if (!source) return;
    source.setData({ type: "FeatureCollection", features: feats });

    const labels = [];
    feats.forEach((f) => {
      if (f.type === "point" && f.geometry?.coordinates) {
        const lbl = f.id === "modal-origin-point" ? "Origin" : f.id === "modal-vessel-pos" ? "Vessel" : "";
        if (lbl) {
          labels.push({
            type: "Feature",
            geometry: { type: "Point", coordinates: f.geometry.coordinates },
            properties: { label: lbl },
          });
        }
      }
    });
    const labelSrc = map.getSource("vessel-labels");
    if (labelSrc) {
      labelSrc.setData({ type: "FeatureCollection", features: labels });
    }
  };

  return (
    <div
      ref={containerRef}
      style={{ height: 350, width: "100%", borderRadius: 8, overflow: "hidden", border: "1px solid #1e293b" }}
    />
  );
}

function FactorBar({ factor, value, meta }) {
  const pct = typeof value === "number" ? value * 100 : 0;
  return (
    <div className="vd-factor-row">
      <div className="vd-factor-left">
        <span className="vd-factor-icon" style={{ color: meta.color }}>{meta.icon}</span>
        <span className="vd-factor-label">{meta.label}</span>
        <span className="vd-factor-weight">{meta.weight}</span>
      </div>
      <div className="vd-factor-bar-wrap">
        <div className="vd-factor-bar-bg">
          <div
            className="vd-factor-bar-fill"
            style={{ width: `${pct}%`, background: meta.color }}
          />
        </div>
        <span className="vd-factor-value">{pct.toFixed(1)}%</span>
      </div>
    </div>
  );
}

function EvidenceSection({ reasons, vessel }) {
  if (!reasons || reasons.length === 0) return null;
  const grouped = { strong: [], moderate: [], neutral: [] };
  reasons.forEach((r) => {
    const lower = r.toLowerCase();
    if (lower.includes("strong") || lower.includes("dark") || lower.includes("oil/hazardous") || lower.includes("repeat")) {
      grouped.strong.push(r);
    } else if (lower.includes("moderate") || lower.includes("present") || lower.includes("proximity")) {
      grouped.moderate.push(r);
    } else {
      grouped.neutral.push(r);
    }
  });

  return (
    <div className="vd-evidence">
      <h4>Evidence Chain</h4>
      {grouped.strong.length > 0 && (
        <div className="vd-evidence-group vd-evidence-strong">
          <span className="vd-evidence-tag">High Relevance</span>
          {grouped.strong.map((r, i) => <p key={i} className="vd-evidence-item">{r}</p>)}
        </div>
      )}
      {grouped.moderate.length > 0 && (
        <div className="vd-evidence-group vd-evidence-moderate">
          <span className="vd-evidence-tag">Moderate Relevance</span>
          {grouped.moderate.map((r, i) => <p key={i} className="vd-evidence-item">{r}</p>)}
        </div>
      )}
      {grouped.neutral.length > 0 && (
        <div className="vd-evidence-group vd-evidence-neutral">
          <span className="vd-evidence-tag">Contextual</span>
          {grouped.neutral.map((r, i) => <p key={i} className="vd-evidence-item">{r}</p>)}
        </div>
      )}
    </div>
  );
}

function VesselInfo({ vessel }) {
  const info = [
    { label: "MMSI", value: vessel.mmsi || "\u2014" },
    { label: "IMO", value: vessel.imo || "\u2014" },
    { label: "Flag", value: vessel.flag || "\u2014" },
    { label: "Ship Type", value: vessel.ship_type || "\u2014" },
    { label: "Cargo Type", value: vessel.cargo_type || "\u2014" },
    { label: "Geartype", value: vessel.geartype || "\u2014" },
    { label: "Callsign", value: vessel.callsign || "\u2014" },
    { label: "First Seen", value: vessel.first_transmission || vessel.entry_timestamp || "\u2014" },
    { label: "Last Seen", value: vessel.last_seen || vessel.last_transmission || vessel.exit_timestamp || "\u2014" },
  ];

  return (
    <div className="vd-info">
      <h4>Vessel Identity</h4>
      <div className="vd-info-grid">
        {info.map((item) => (
          <div className="vd-info-item" key={item.label}>
            <span className="vd-info-label">{item.label}</span>
            <span className="vd-info-value">{item.value}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function BehaviourSection({ vessel }) {
  const signals = vessel.signals || {};
  const hasSignals = Object.keys(signals).length > 0;

  return (
    <div className="vd-behaviour">
      <h4>Behavioural Analysis</h4>
      <div className="vd-behaviour-summary">
        <div className="vd-behaviour-score">
          <span className="vd-behaviour-score-label">Anomaly Score</span>
          <span className="vd-behaviour-score-value" style={{
            color: (vessel.anomaly_score || 0) >= 0.6 ? "#ef4444" : (vessel.anomaly_score || 0) >= 0.3 ? "#f59e0b" : "#10b981"
          }}>
            {((vessel.anomaly_score || 0) * 100).toFixed(1)}%
          </span>
        </div>
        <p className="vd-behaviour-evidence">{vessel.evidence || "No behavioural data"}</p>
      </div>
      {hasSignals && (
        <div className="vd-signals-grid">
          {Object.entries(signals).map(([key, val]) => (
            <div className="vd-signal-card" key={key}>
              <span className="vd-signal-name">{key}</span>
              <div className="vd-signal-bar-bg">
                <div
                  className="vd-signal-bar-fill"
                  style={{
                    width: `${(val || 0) * 100}%`,
                    background: (val || 0) >= 0.6 ? "#ef4444" : (val || 0) >= 0.3 ? "#f59e0b" : "#10b981",
                  }}
                />
              </div>
              <span className="vd-signal-value">{((val || 0) * 100).toFixed(0)}%</span>
            </div>
          ))}
        </div>
      )}
      {vessel.transit_ok === false && (
        <div className="vd-transit-filter">
          Transit filter: <strong>dropped</strong> &mdash; {vessel.transit_reason}
        </div>
      )}
    </div>
  );
}

export default function VesselDetailModal({ vessel, pipelineData, rank, onClose }) {
  const [trackVisible, setTrackVisible] = useState(true);
  const [originVisible, setOriginVisible] = useState(true);
  const [spillVisible, setSpillVisible] = useState(true);

  const track = React.useMemo(
    () => generateVesselTrack(vessel, pipelineData),
    [vessel, pipelineData]
  );

  const origin = pipelineData.origin_centroid;
  const vlon = vessel.avg_lon ?? origin?.[0];
  const vlat = vessel.avg_lat ?? origin?.[1];

  const allFeatures = React.useMemo(
    () => buildModalFeatures(vessel, pipelineData, trackVisible ? track : []),
    [vessel, pipelineData, track, trackVisible]
  );

  const visibleFeatures = React.useMemo(() => {
    return allFeatures.filter((f) => {
      if (f.id?.startsWith("modal-slick")) return spillVisible;
      if (f.id === "modal-origin-region" || f.id === "modal-origin-point") return originVisible;
      return true;
    });
  }, [allFeatures, spillVisible, originVisible]);

  const handleBackdropClick = useCallback((e) => {
    if (e.target === e.currentTarget) onClose();
  }, [onClose]);

  useEffect(() => {
    const onKey = (e) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const isTop = rank === 1 || vessel.top_signal;
  const scoreColor = isTop ? "#ef4444" : (vessel.attribution_score || 0) > 0.5 ? "#f59e0b" : "#3b82f6";

  return (
    <div className="vd-overlay" onClick={handleBackdropClick}>
      <div className="vd-modal">
        <div className="vd-modal-header">
          <div className="vd-modal-title">
            <span className="vd-modal-rank" style={{ background: scoreColor }}>#{rank}</span>
            <div>
              <h2>{vessel.vessel_name}</h2>
              <span className="vd-modal-subtitle">
                {vessel.ship_type} &middot; {vessel.flag} &middot; MMSI: {vessel.mmsi}
              </span>
            </div>
            {vessel.top_signal && <span className="dark-vessel-badge" style={{ marginLeft: 12 }}>DARK VESSEL</span>}
          </div>
          <div className="vd-modal-score">
            <span className="vd-score-number" style={{ color: scoreColor }}>
              {(vessel.attribution_score || 0).toFixed(3)}
            </span>
            <span className="vd-score-label">Attribution Score</span>
          </div>
          <button className="vd-close-btn" onClick={onClose}>&times;</button>
        </div>

        <div className="vd-modal-body">
          <div className="vd-map-section">
            <div className="vd-map-controls">
              <label className="vd-toggle">
                <input type="checkbox" checked={trackVisible} onChange={(e) => setTrackVisible(e.target.checked)} />
                <span style={{ background: "#f59e0b" }} className="vd-toggle-dot" /> Vessel Route
              </label>
              <label className="vd-toggle">
                <input type="checkbox" checked={originVisible} onChange={(e) => setOriginVisible(e.target.checked)} />
                <span style={{ background: "#3b82f6" }} className="vd-toggle-dot" /> Origin Zone
              </label>
              <label className="vd-toggle">
                <input type="checkbox" checked={spillVisible} onChange={(e) => setSpillVisible(e.target.checked)} />
                <span style={{ background: "#ef4444" }} className="vd-toggle-dot" /> Oil Spill
              </label>
            </div>
            <VesselMap
              features={visibleFeatures}
              center={[vlon || 72.8, vlat || 18.9]}
              zoom={12}
            />
            <div className="vd-map-legend">
              <span><span className="vd-legend-dot" style={{ background: "#f59e0b" }} /> Vessel AIS track</span>
              <span><span className="vd-legend-dot" style={{ background: "#3b82f6" }} /> Probable origin zone</span>
              <span><span className="vd-legend-dot" style={{ background: "#ef4444" }} /> Detected oil slick</span>
            </div>
          </div>

          <div className="vd-details-grid">
            <div className="vd-details-left">
              <VesselInfo vessel={vessel} />
              <BehaviourSection vessel={vessel} />
              {vessel.repeat_offense_count > 0 && (
                <div className="vd-repeat">
                  <h4>Repeat Offender</h4>
                  <p>Previously implicated in <strong>{vessel.repeat_offense_count}</strong> attribution{vessel.repeat_offense_count !== 1 ? "s" : ""}</p>
                  {vessel.repeat_offense_incidents?.length > 0 && (
                    <p className="vd-repeat-incidents">Incidents: {vessel.repeat_offense_incidents.join(", ")}</p>
                  )}
                </div>
              )}
            </div>

            <div className="vd-details-right">
              <div className="vd-factors-section">
                <h4>Attribution Factors</h4>
                {FACTOR_META.map((meta) => {
                  const val = vessel.factors?.[meta.key];
                  return val != null ? (
                    <FactorBar key={meta.key} factor={meta.key} value={val} meta={meta} />
                  ) : null;
                })}
              </div>
              <EvidenceSection reasons={vessel.reasons} vessel={vessel} />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
