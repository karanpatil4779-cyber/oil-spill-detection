import React, { useState } from "react";
import VesselDetailModal from "./VesselDetailModal";

const INITIAL_COUNT = 5;

export default function Panel6Attribution({ data, readOnly, onOverrideRank }) {
  const [overrideVessel, setOverrideVessel] = useState(null);
  const [justification, setJustification] = useState("");
  const [showAll, setShowAll] = useState(false);
  const [selectedVessel, setSelectedVessel] = useState(null);
  const [selectedRank, setSelectedRank] = useState(0);

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

  const handleOverride = (e, vessel) => {
    e.stopPropagation();
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

  const handleVesselClick = (vessel, index) => {
    setSelectedVessel(vessel);
    setSelectedRank(index + 1);
  };

  const rankedSuspects = data.suspects.map((s, i) => ({ ...s, _index: i }));
  const suspects = showAll ? rankedSuspects : rankedSuspects.slice(0, INITIAL_COUNT);
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
            Ranked candidates with per-factor evidence breakdown and stated reasons.
            Highest-ranked = <em>candidate source vessel</em>, not a definitive attribution.
            Manual review recommended.
          </p>
          {totalSuspects > INITIAL_COUNT && (
            <p className="panel-note">
              Showing {showAll ? "all" : `top ${INITIAL_COUNT}`} of {totalSuspects} ranked vessels by attribution score. Click any vessel for full evidence.
            </p>
          )}
        </div>

        {suspects.map((s, i) => {
          const rank = s._index + 1;
          const isTop = (s.top_signal || (rank === 1 && (suspects[0]?.attribution_score || 0) > 0));
          const label = s.top_signal
            ? "Probable source \u2014 SAR dark vessel (no AIS)"
            : isTop
              ? "Probable source vessel"
              : "Candidate source vessel";
          return (
            <div
              className="panel-card attribution-card vessel-clickable"
              key={s.vessel_id || s.mmsi || i}
              onClick={() => handleVesselClick(s, rank)}
            >
              <div className="attribution-header">
                <span className="attribution-rank">#{rank}</span>
                <div>
                  <span className="attribution-name">{s.vessel_name}</span>
                  {s.top_signal && <span className="dark-vessel-badge" title="SAR dark spot with no co-located AIS track">DARK</span>}
                  <span className="attribution-meta">
                    MMSI: {s.mmsi} &middot; {s.ship_type} &middot; {s.flag}
                  </span>
                  <span className="attribution-label">{label}</span>
                </div>
                <span className="attribution-score">{s.attribution_score?.toFixed(3)}</span>
              </div>

              <div className="factor-breakdown">
                {[
                  { key: "proximity", label: "Proximity Score", weight: "30%" },
                  { key: "duration", label: "Duration Match", weight: "18%" },
                  { key: "cargo", label: "Cargo/Type Match", weight: "22%" },
                  { key: "behaviour", label: "Behavioural Anomaly", weight: "15%" },
                  { key: "vessel_type", label: "Vessel-Type Profile", weight: "10%" },
                  { key: "repeat", label: "Repeat-Offender History", weight: "5%" },
                ].map((f) => (
                  <div className="factor-row" key={f.key}>
                    <span className="factor-label">{f.label}</span>
                    <div className="factor-bar-bg">
                      <div
                        className="factor-bar-fill"
                        style={{ width: `${(s.factors?.[f.key] || 0) * 100}%` }}
                      />
                    </div>
                    <span className="factor-weight">
                      {s.factors?.[f.key] != null ? (s.factors[f.key] * 100).toFixed(0) + "%" : "\u2014"}
                      <span className="factor-config"> (config: {f.weight})</span>
                    </span>
                  </div>
                ))}
              </div>

              {s.reasons && s.reasons.length > 0 && (
                <div className="evidence-reasons">
                  <span className="evidence-title">Evidence</span>
                  <ul>
                    {s.reasons.slice(0, 4).map((r, ri) => <li key={ri}>{r}</li>)}
                    {s.reasons.length > 4 && <li className="panel-note">+{s.reasons.length - 4} more reasons (click for full details)</li>}
                  </ul>
                </div>
              )}

              {(s.repeat_offense_count || 0) > 0 && (
                <div className="repeat-offender panel-note">
                  Repeat offender: previously implicated in{" "}
                  <strong>{s.repeat_offense_count}</strong> attribution
                  {s.repeat_offense_count !== 1 ? "s" : ""}
                  {s.repeat_offense_incidents?.length
                    ? ` (${s.repeat_offense_incidents.join(", ")})`
                    : ""}
                </div>
              )}

              {s.signals && (
                <div className="vessel-anomaly panel-note">
                  Behaviour anomaly: <span className="mono">{s.anomaly_score}</span>
                  <span className="small">({s.evidence})</span>
                </div>
              )}

              <div className="vessel-click-hint">
                <span>Click for full details &amp; interactive map &rarr;</span>
                {!readOnly && (
                  <button className="btn-sm btn-outline" onClick={(e) => handleOverride(e, s)}>
                    Override Rank
                  </button>
                )}
              </div>
            </div>
          );
        })}

        {totalSuspects > INITIAL_COUNT && (
          <div className="show-more-container">
            <button className="btn-secondary btn-show-more" onClick={() => setShowAll(!showAll)}>
              {showAll ? "Show Less" : `Show All ${totalSuspects} Ranked Vessels`}
            </button>
            {!showAll && (
              <span className="show-more-hint">
                Showing {INITIAL_COUNT} of {totalSuspects} vessels
              </span>
            )}
          </div>
        )}

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

        {selectedVessel && (
          <VesselDetailModal
            vessel={selectedVessel}
            pipelineData={data}
            rank={selectedRank}
            onClose={() => setSelectedVessel(null)}
          />
        )}
      </div>
    </div>
  );
}
