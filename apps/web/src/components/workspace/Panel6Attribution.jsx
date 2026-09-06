import React, { useState } from "react";

export default function Panel6Attribution({ data, readOnly, onOverrideRank }) {
  const [overrideVessel, setOverrideVessel] = useState(null);
  const [justification, setJustification] = useState("");

  if (!data?.suspects || data.suspects.length === 0) {
    return (
      <div className="workspace-panel">
        <div className="panel-header">
          <span className="panel-number">6</span>
          <h2>Attribution Ranking</h2>
        </div>
        <div className="panel-body">
          <div className="panel-card">
            <div className="panel-empty">No vessel candidates to rank</div>
            {!data.gfw_available && (
              <p className="panel-note">
                AIS data source (Global Fishing Watch) was unavailable.
                Consider checking independent evidence sources (coastal radar, port records, VMS, LRIT) if available.
              </p>
            )}
          </div>
        </div>
      </div>
    );
  }

  const handleOverride = (vessel) => {
    setOverrideVessel(vessel);
    setJustification("");
  };

  const submitOverride = () => {
    if (justification.trim()) {
      onOverrideRank?.({
        vessel_id: overrideVessel.mmsi || overrideVessel.vessel_id,
        new_rank: (overrideVessel._index ?? data.suspects.indexOf(overrideVessel)) + 1,
        justification: justification.trim(),
      });
      setOverrideVessel(null);
      setJustification("");
    }
  };

  const factors = [
    { key: "proximity", label: "Proximity Score", weight: "35%" },
    { key: "duration", label: "Duration Match", weight: "20%" },
    { key: "cargo", label: "Cargo/Type Match", weight: "30%" },
    { key: "behaviour", label: "Behavioural Anomaly", weight: "15%" },
  ];

  const rankedSuspects = data.suspects.map((s, i) => ({ ...s, _index: i }));
  const suspects = rankedSuspects.slice(0, 5);
  const totalSuspects = rankedSuspects.length;

  return (
    <div className="workspace-panel">
      <div className="panel-header">
        <span className="panel-number">6</span>
        <h2>Attribution Ranking</h2>
      </div>
      <div className="panel-body">
        <div className="panel-card info-card">
          <p className="panel-note">
            Ranked candidates with per-factor evidence breakdown.
            Highest-ranked = <em>candidate source vessel</em>, not a definitive attribution.
            Manual review recommended.
          </p>
          {totalSuspects > suspects.length && (
            <p className="panel-note">
              Showing top {suspects.length} of {totalSuspects} ranked vessels by attribution score.
            </p>
          )}
        </div>

        {suspects.map((s, i) => {
          const rank = s._index + 1;
          const isTop = rank === 1 && (suspects[0]?.attribution_score || 0) > 0;
          const label = isTop ? "Probable source vessel" : "Candidate source vessel";
          return (
            <div className="panel-card attribution-card" key={s.vessel_id || s.mmsi || i}>
              <div className="attribution-header">
                <span className="attribution-rank">#{rank}</span>
                <div>
                  <span className="attribution-name">{s.vessel_name}</span>
                  <span className="attribution-meta">
                    MMSI: {s.mmsi} &middot; {s.ship_type} &middot; {s.flag}
                  </span>
                  <span className="attribution-label">{label}</span>
                </div>
                <span className="attribution-score">{s.attribution_score?.toFixed(3)}</span>
              </div>

              <div className="factor-breakdown">
                {factors.map((f) => (
                  <div className="factor-row" key={f.key}>
                    <span className="factor-label">{f.label}</span>
                    <div className="factor-bar-bg">
                      <div
                        className="factor-bar-fill"
                        style={{ width: `${(s.factors?.[f.key] || 0) * 100}%` }}
                      />
                    </div>
                    <span className="factor-weight">
                      {s.factors?.[f.key] != null ? (s.factors[f.key] * 100).toFixed(0) + "%" : "—"}
                      <span className="factor-config"> (config: {f.weight})</span>
                    </span>
                  </div>
                ))}
              </div>

              {s.signals && (
                <div className="vessel-anomaly panel-note">
                  Behaviour anomaly: <span className="mono">{s.anomaly_score}</span>
                  <span className="small">({s.evidence})</span>
                </div>
              )}

              {!readOnly && (
                <button className="btn-sm btn-outline" onClick={() => handleOverride(s)}>
                  Override Rank
                </button>
              )}
            </div>
          );
        })}

        {overrideVessel && (
          <div className="panel-card override-dialog">
            <h4>Manual Rank Override</h4>
            <p>Vessel: <strong>{overrideVessel.vessel_name}</strong> (#{(overrideVessel._index ?? data.suspects.indexOf(overrideVessel)) + 1})</p>
            <textarea
              value={justification}
              onChange={(e) => setJustification(e.target.value)}
              placeholder="Enter justification for this override (required for audit trail)..."
              rows={3}
            />
            <div className="override-actions">
              <button className="btn-secondary" onClick={() => setOverrideVessel(null)}>Cancel</button>
              <button className="btn-primary" onClick={submitOverride} disabled={!justification.trim()}>
                Confirm Override
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
