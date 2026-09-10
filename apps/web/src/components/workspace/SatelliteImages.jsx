import React, { useState } from "react";

const TYPE_META = {
  sar: { label: "SAR", icon: "\u25a0", color: "#f59e0b" },
  optical: { label: "Optical", icon: "\u25c6", color: "#10b981" },
  ndhi: { label: "NDHI", icon: "\u25b2", color: "#ef4444" },
};

export default function SatelliteImages({ images }) {
  const [expanded, setExpanded] = useState(null);

  if (!images || images.length === 0) {
    return (
      <div className="panel-card">
        <h4>Satellite Imagery</h4>
        <p className="panel-note">
          No satellite images were captured for this run. Enable the SAR &amp;
          Optical detection toggle during the pipeline run to fetch imagery.
        </p>
      </div>
    );
  }

  return (
    <div className="panel-card">
      <h4>Satellite Imagery ({images.length})</h4>
      <div className="sat-image-strip">
        {images.map((img, i) => {
          const meta = TYPE_META[img.type] || TYPE_META.sar;
          return (
            <div
              className={`sat-image-item ${expanded === i ? "expanded" : ""}`}
              key={`${img.src}-${i}`}
              onClick={() => setExpanded(expanded === i ? null : i)}
            >
              <img
                src={img.src}
                alt={img.caption || `Satellite image ${i + 1}`}
                loading="lazy"
                className="sat-image-thumb"
              />
              <div className="sat-image-meta">
                <span className="sat-image-badge" style={{ background: `${meta.color}22`, color: meta.color }}>
                  {meta.icon} {meta.label}
                </span>
                <span className="sat-image-caption">
                  {img.caption || "Satellite capture"}
                </span>
                {img.source && (
                  <span className="sat-image-source">Scene: {img.source}</span>
                )}
              </div>
              <div className="sat-image-expand-hint">
                {expanded === i ? "Click to collapse" : "Click to expand"}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}