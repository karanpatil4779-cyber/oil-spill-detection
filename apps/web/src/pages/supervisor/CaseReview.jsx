import React, { useState, useEffect } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { apiGet, apiPost, apiPatch } from "../../api/client";
import StatusBadge from "../../components/StatusBadge";
import { formatDateTime } from "../../utils/formatters";
import Panel1Detection from "../../components/workspace/Panel1Detection";
import Panel2Characterization from "../../components/workspace/Panel2Characterization";
import Panel3OriginHindcast from "../../components/workspace/Panel3OriginHindcast";
import Panel4ForwardForecast from "../../components/workspace/Panel4ForwardForecast";
import Panel5AISVessels from "../../components/workspace/Panel5AISVessels";
import Panel6Attribution from "../../components/workspace/Panel6Attribution";
import Panel7DataQuality from "../../components/workspace/Panel7DataQuality";
import Panel8AuditTrail from "../../components/workspace/Panel8AuditTrail";

export default function CaseReview() {
  const { caseId } = useParams();
  const navigate = useNavigate();
  const [caseData, setCaseData] = useState(null);
  const [auditLog, setAuditLog] = useState([]);
  const [notes, setNotes] = useState([]);
  const [loading, setLoading] = useState(true);
  const [returnNote, setReturnNote] = useState("");
  const [noteText, setNoteText] = useState("");
  const [showReturnDialog, setShowReturnDialog] = useState(false);

  useEffect(() => { loadCase(); }, [caseId]);

  const loadCase = async () => {
    setLoading(true);
    try {
      const data = await apiGet(`/cases/${caseId}`);
      setCaseData(data);
      const audit = await apiGet(`/cases/${caseId}/audit`);
      setAuditLog(audit);
      const caseNotes = await apiGet(`/cases/${caseId}/notes`);
      setNotes(caseNotes);
    } catch (err) {
      console.error("Failed to load case:", err);
    } finally {
      setLoading(false);
    }
  };

  const handleApprove = async () => {
    if (confirm("Approve this case?")) {
      await apiPost(`/cases/${caseId}/approve`, {});
      loadCase();
    }
  };

  const handleReturn = async () => {
    if (!returnNote.trim()) return;
    await apiPost(`/cases/${caseId}/return`, { content: returnNote.trim() });
    setShowReturnDialog(false);
    setReturnNote("");
    navigate("/supervisor");
  };

  const handleEscalate = async () => {
    const reason = prompt("Escalation reason:");
    if (reason) {
      await apiPost(`/cases/${caseId}/escalate`, { content: reason });
      loadCase();
    }
  };

  const handleAddNote = async () => {
    if (!noteText.trim()) return;
    await apiPost(`/cases/${caseId}/notes`, { content: noteText.trim() });
    setNoteText("");
    loadCase();
  };

  if (loading) return <div className="loading">Loading case for review...</div>;
  if (!caseData) return <div className="error">Case not found</div>;

  const result = caseData.pipeline_result || {};

  return (
    <div className="workspace-container">
      <div className="workspace-topbar">
        <button className="btn-back" onClick={() => navigate("/supervisor")}>← All Cases</button>
        <div className="workspace-title">
          <span className="case-number">{caseData.case_number}</span>
          <StatusBadge status={caseData.status} />
          <span className="case-analyst">Analyst: {caseData.analyst_name}</span>
        </div>
      </div>

      <div className="supervisor-decision-bar">
        <button className="btn-success" onClick={handleApprove}>Approve</button>
        <button className="btn-warning" onClick={() => setShowReturnDialog(true)}>Return for Revision</button>
        <button className="btn-outline" onClick={handleEscalate}>Escalate</button>
        <div className="note-input-group">
          <input
            type="text"
            value={noteText}
            onChange={(e) => setNoteText(e.target.value)}
            placeholder="Add a note..."
          />
          <button className="btn-secondary" onClick={handleAddNote}>Add Note</button>
        </div>
      </div>

      {showReturnDialog && (
        <div className="return-dialog">
          <h3>Return for Revision</h3>
          <textarea
            value={returnNote}
            onChange={(e) => setReturnNote(e.target.value)}
            placeholder="Explain what needs to be revised (required)..."
            rows={4}
          />
          <div className="dialog-actions">
            <button className="btn-secondary" onClick={() => setShowReturnDialog(false)}>Cancel</button>
            <button className="btn-warning" onClick={handleReturn} disabled={!returnNote.trim()}>Return Case</button>
          </div>
        </div>
      )}

      {notes.length > 0 && (
        <div className="supervisor-notes-section">
          <h3>Notes</h3>
          {notes.map((n) => (
            <div key={n.id} className={`note-card ${n.is_supervisor_return ? "return-note" : ""}`}>
              <div className="note-header">
                <strong>{n.author_name}</strong>
                <span className="note-time">{formatDateTime(n.created_at)}</span>
              </div>
              <p>{n.content}</p>
            </div>
          ))}
        </div>
      )}

      <div className="workspace-panels read-only">
        <Panel1Detection data={result} readOnly />
        <Panel2Characterization data={result} readOnly />
        <Panel3OriginHindcast data={result} readOnly />
        <Panel4ForwardForecast data={result} readOnly />
        <Panel5AISVessels data={result} readOnly />
        <Panel6Attribution data={result} readOnly />
        <Panel7DataQuality data={result} readOnly />
        <Panel8AuditTrail auditLog={auditLog} />
      </div>
    </div>
  );
}
