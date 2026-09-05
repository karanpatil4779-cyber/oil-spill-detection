import React, { useState, useEffect } from "react";
import { apiGet } from "../../api/client";
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, PieChart, Pie, Cell, ResponsiveContainer } from "recharts";

const COLORS = ["#3b82f6", "#f59e0b", "#ef4444", "#10b981", "#6b7280", "#a855f7"];

export default function Analytics() {
  const [throughput, setThroughput] = useState(null);
  const [evidenceRate, setEvidenceRate] = useState(null);
  const [analystPerf, setAnalystPerf] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([
      apiGet("/analytics/throughput"),
      apiGet("/analytics/evidence-rate"),
      apiGet("/analytics/analyst-performance"),
    ]).then(([t, e, a]) => {
      setThroughput(t);
      setEvidenceRate(e);
      setAnalystPerf(a.analysts || []);
    }).catch(console.error)
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <div className="loading">Loading analytics...</div>;

  const statusData = throughput ? Object.entries(throughput.by_status || {}).map(([k, v]) => ({
    name: k.replace(/_/g, " "),
    value: v,
  })) : [];

  return (
    <div className="page-container">
      <div className="page-header">
        <h1>Analytics Dashboard</h1>
        <p className="page-subtitle">Portfolio-level metrics and performance indicators</p>
      </div>

      <div className="analytics-grid">
        <div className="analytics-card">
          <h3>Total Cases</h3>
          <span className="big-number">{throughput?.total_cases || 0}</span>
        </div>
        <div className="analytics-card">
          <h3>Approved</h3>
          <span className="big-number" style={{ color: "#10b981" }}>{evidenceRate?.approved || 0}</span>
        </div>
        <div className="analytics-card">
          <h3>Insufficient Evidence Rate</h3>
          <span className="big-number" style={{ color: "#a855f7" }}>
            {evidenceRate ? `${(evidenceRate.insufficient_rate * 100).toFixed(1)}%` : "—"}
          </span>
        </div>
        <div className="analytics-card">
          <h3>Analysts</h3>
          <span className="big-number">{analystPerf.length}</span>
        </div>
      </div>

      <div className="analytics-charts">
        <div className="chart-card">
          <h3>Cases by Status</h3>
          <ResponsiveContainer width="100%" height={250}>
            <PieChart>
              <Pie data={statusData} dataKey="value" nameKey="name" cx="50%" cy="50%" outerRadius={80} label>
                {statusData.map((_, i) => <Cell key={i} fill={COLORS[i % COLORS.length]} />)}
              </Pie>
              <Tooltip />
            </PieChart>
          </ResponsiveContainer>
        </div>

        <div className="chart-card">
          <h3>Analyst Performance</h3>
          <ResponsiveContainer width="100%" height={250}>
            <BarChart data={analystPerf}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
              <XAxis dataKey="analyst_name" stroke="#94a3b8" fontSize={12} />
              <YAxis stroke="#94a3b8" fontSize={12} />
              <Tooltip contentStyle={{ background: "#1e293b", border: "1px solid #334155" }} />
              <Bar dataKey="total_cases" fill="#3b82f6" name="Total" />
              <Bar dataKey="approved" fill="#10b981" name="Approved" />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  );
}
