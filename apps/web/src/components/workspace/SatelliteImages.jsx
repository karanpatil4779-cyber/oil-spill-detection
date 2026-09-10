import React, { useState } from "react";

const TYPE_META = {
  sar: { label: "SAR", icon: "\u25a0", color: "#f59e0b" },
  optical: { label: "Optical", icon: "\u25c6", color: "#10b981" },
  ndhi: { label: "NDHI", icon: "\u25b2", color: "#ef4444" },
};

// Fallback demo previews bundled into the frontend (apps/web/public/satellite-demo).
// Shown when a run captured no reachable imagery so the panel always renders;
// they are labelled as synthetic demo renders, never as real captures.
const DEMO_IMAGES = [
  {
    src: "/satellite-demo/demo-sar.png",
    caption: "SAR backscatter (VV) — dark slick",
    type: "sar",
    source: "Bundled demo render (no capture in this run)",
    is_demo: true,
    is_synthetic: true,
  },
  {
    src: "/satellite-demo/demo-ndhi.png",
    caption: "NDHI hydrocarbon index — oil signature",
    type: "optical",
    source: "Bundled demo render (no capture in this run)",
    is_demo: true,
    is_synthetic: true,
  },
];

const REACHABLE = (url) =>
  /^(https?:|data:|blob:)/.test(url || "") || url.startsWith("/satellite-demo/");

const DEMO_FOR_TYPE = {
  sar: DEMO_IMAGES[0],
  optical: DEMO_IMAGES[1],
  ndhi: DEMO_IMAGES[1],
};

export default function SatelliteImages({ images }) {
  const [expanded, setExpanded] = useState(null);
  // srcs that failed to load (broken/404/unauthorised) -> substitute demo render
  const [broken, setBroken] = useState(() => new Set());

  const captureCount = (images || []).filter((img) => REACHABLE(img.src)).length;

  // Use real captures when at least one is reachable; otherwise fall back to
  // the bundled demo previews so the panel is never empty.
  const effectiveImages = captureCount > 0 ? images : DEMO_IMAGES;
  const isFallback = captureCount === 0;

  const srcFor = (img) => {
    if (broken.has(img.src)) {
      return (DEMO_FOR_TYPE[img.type] || DEMO_IMAGES[0]).src;
    }
    return img.src;
  };

  const badgeFor = (img) =>
    broken.has(img.src) ? (DEMO_FOR_TYPE[img.type] || DEMO_IMAGES[0]) : img;

  return (
    <div className="panel-card">
      <h4>Satellite Imagery{effectiveImages.length ? ` (${effectiveImages.length})` : ""}</h4>
      {isFallback && (
        <p className="panel-note">
          No satellite scene was captured in this run, so bundled demo previews
          are shown. Re-run with the <strong>SAR &amp; Optical detection</strong>{" "}
          toggle enabled to capture live Sentinel-1/2 imagery.
        </p>
      )}
      <div className="sat-image-strip">
        {effectiveImages.map((img, i) => {
          const display = badgeFor(img);
          const meta = TYPE_META[display.type] || TYPE_META.sar;
          return (
            <div
              className={`sat-image-item ${expanded === i ? "expanded" : ""}`}
              key={`${img.src}-${i}`}
              onClick={() => setExpanded(expanded === i ? null : i)}
            >
              <img
                src={srcFor(img)}
                alt={display.caption || `Satellite image ${i + 1}`}
                loading="lazy"
                className="sat-image-thumb"
                onError={() => setBroken((prev) => new Set(prev).add(img.src))}
              />
              <div className="sat-image-meta">
                <span className="sat-image-badge" style={{ background: `${meta.color}22`, color: meta.color }}>
                  {meta.icon} {meta.label}
                </span>
                {(display.is_synthetic || display.is_demo) && (
                  <span className="sat-image-badge" style={{ background: "#8b5cf622", color: "#8b5cf6" }}>
                    Synthetic
                  </span>
                )}
                <span className="sat-image-caption">
                  {broken.has(img.src)
                    ? "Capture failed the download — substituting bundled preview"
                    : (display.caption || "Satellite capture")}
                </span>
                {display.source && (
                  <span className="sat-image-source">Scene: {display.source}</span>
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