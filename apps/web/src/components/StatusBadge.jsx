import React from "react";
import { CASE_STATUSES } from "../utils/constants";

export default function StatusBadge({ status }) {
  const info = CASE_STATUSES[status] || { label: status, color: "#6b7280" };
  return (
    <span
      className="status-badge"
      style={{ backgroundColor: info.color + "22", color: info.color, borderColor: info.color }}
    >
      {info.label}
    </span>
  );
}
