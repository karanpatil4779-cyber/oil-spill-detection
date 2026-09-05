import React, { useState, useEffect } from "react";
import { apiGet } from "../../api/client";
import CaseTable from "../../components/CaseTable";

export default function PortfolioDashboard() {
  const [cases, setCases] = useState([]);
  const [statusFilter, setStatusFilter] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    loadCases();
  }, [statusFilter]);

  const loadCases = async () => {
    setLoading(true);
    try {
      const params = statusFilter ? `?status_filter=${statusFilter}` : "";
      const data = await apiGet(`/cases${params}`);
      setCases(data.cases || []);
    } catch (err) {
      console.error("Failed to load cases:", err);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="page-container">
      <div className="page-header">
        <div>
          <h1>Portfolio Dashboard</h1>
          <p className="page-subtitle">All investigations across all analysts</p>
        </div>
      </div>
      {loading ? (
        <div className="loading">Loading cases...</div>
      ) : (
        <CaseTable
          cases={cases}
          basePath="/supervisor/case"
          statusFilter={statusFilter}
          onStatusFilter={setStatusFilter}
        />
      )}
    </div>
  );
}
