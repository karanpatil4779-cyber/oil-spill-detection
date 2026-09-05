import React from "react";

export default function ConfidenceGauge({ score }) {
  if (score == null) return <span className="confidence-gauge">—</span>;
  const pct = Math.round(score * 100);
  let color = "#10b981";
  if (pct < 50) color = "#ef4444";
  else if (pct < 75) color = "#f59e0b";

  return (
    <span className="confidence-gauge" style={{ color }}>
      {pct}%
    </span>
  );
}
