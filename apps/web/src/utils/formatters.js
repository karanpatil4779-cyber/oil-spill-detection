export function formatDate(dateStr) {
  if (!dateStr) return "—";
  const d = new Date(dateStr);
  return d.toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" });
}

export function formatDateTime(dateStr) {
  if (!dateStr) return "—";
  const d = new Date(dateStr);
  return d.toLocaleString("en-IN", {
    day: "2-digit", month: "short", year: "numeric",
    hour: "2-digit", minute: "2-digit",
  });
}

export function formatConfidence(score) {
  if (score == null) return "—";
  return `${Math.round(score * 100)}%`;
}

export function formatArea(km2) {
  if (km2 == null) return "—";
  return km2 < 1 ? `${(km2 * 1e6).toFixed(0)} m²` : `${km2.toFixed(2)} km²`;
}

export function formatVolume(m3) {
  if (m3 == null) return "—";
  return `${m3.toFixed(1)} m³`;
}
