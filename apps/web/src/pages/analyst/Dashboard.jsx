import React, { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { apiGet } from "../../api/client";
import CaseTable from "../../components/CaseTable";

export default function AnalystDashboard() {
  const [cases, setCases] = useState([]);
  const [statusFilter, setStatusFilter] = useState("");
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();

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
          <h1>Investigation Dashboard</h1>
          <p className="page-subtitle">Your active oil spill investigations</p>
        </div>
        <button className="btn-primary" onClick={() => navigate("/analyst/new")}>
          + New Investigation
        </button>
      </div>
      {loading ? (
        <div className="loading">Loading cases...</div>
      ) : (
        <CaseTable
          cases={cases}
          basePath="/analyst/case"
          statusFilter={statusFilter}
          onStatusFilter={setStatusFilter}
        />
      )}
    </div>
  );
}
