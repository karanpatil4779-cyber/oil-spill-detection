import React, { useState } from "react";
import { useNavigate } from "react-router-dom";
import { apiPost } from "../../api/client";

const PRESETS = {
  "": { name: "Custom Location", lon: 72.8, lat: 18.9, date: "2018-01-30" },
  mt_jipro_neftis_mumbai_2018: { name: "MT Jipro Neftis 2018", lon: 72.8, lat: 18.9, date: "2018-01-30" },
  gal_constructor_mumbai_2021: { name: "GAL Constructor 2021", lon: 72.7, lat: 19.8, date: "2021-05-17" },
  ennore_chennai_2017: { name: "Chennai/Ennore 2017", lon: 80.35, lat: 13.28, date: "2017-03-10" },
  kandla_gulf_kutch_2023: { name: "Kandla/Kutch 2023", lon: 69.85, lat: 22.78, date: "2023-02-15" },
};

export default function NewInvestigation() {
  const navigate = useNavigate();
  const [preset, setPreset] = useState("");
  const [lon, setLon] = useState(72.8);
  const [lat, setLat] = useState(18.9);
  const [date, setDate] = useState("2018-01-30");
  const [duration, setDuration] = useState(24);
  const [locationName, setLocationName] = useState("");
  const [loading, setLoading] = useState(false);
  const [mode, setMode] = useState("search"); // search | upload

  const onPresetChange = (e) => {
    const key = e.target.value;
    setPreset(key);
    const p = PRESETS[key];
    if (p && key !== "") {
      setLon(p.lon);
      setLat(p.lat);
      setDate(p.date);
      setLocationName(p.name);
    }
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);
    try {
      const caseData = await apiPost("/cases", {
        location_name: locationName || `Custom (${lon}, ${lat})`,
        lon: Number(lon),
        lat: Number(lat),
        detection_date: date,
        duration_hours: Number(duration),
      });
      navigate(`/analyst/case/${caseData.id}`);
    } catch (err) {
      alert("Failed to create case: " + err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="page-container">
      <div className="page-header">
        <div>
          <h1>New Investigation</h1>
          <p className="page-subtitle">Define the area and time for a new oil spill investigation</p>
        </div>
      </div>

      <div className="investigation-mode-toggle">
        <button
          className={`mode-btn ${mode === "search" ? "active" : ""}`}
          onClick={() => setMode("search")}
        >
          Region Search
        </button>
        <button
          className={`mode-btn ${mode === "upload" ? "active" : ""}`}
          onClick={() => setMode("upload")}
        >
          Upload Satellite Scene
        </button>
      </div>

      <form onSubmit={handleSubmit} className="new-investigation-form">
        <div className="form-section">
          <h3>Incident Preset</h3>
          <select value={preset} onChange={onPresetChange}>
            {Object.entries(PRESETS).map(([k, v]) => (
              <option key={k} value={k}>{v.name}</option>
            ))}
          </select>
        </div>

        <div className="form-grid">
          <div className="form-section">
            <h3>Location</h3>
            <label>Longitude</label>
            <input type="number" step="0.001" value={lon} onChange={(e) => setLon(e.target.value)} />
            <label>Latitude</label>
            <input type="number" step="0.001" value={lat} onChange={(e) => setLat(e.target.value)} />
            <label>Location Name</label>
            <input type="text" value={locationName} onChange={(e) => setLocationName(e.target.value)} placeholder="e.g. Mumbai Harbour" />
          </div>

          <div className="form-section">
            <h3>Time Parameters</h3>
            <label>Detection Date</label>
            <input type="date" value={date} onChange={(e) => setDate(e.target.value)} />
            <label>Track-back Duration (hours)</label>
            <input type="number" value={duration} onChange={(e) => setDuration(e.target.value)} min="1" max="168" />
          </div>
        </div>

        {mode === "upload" && (
          <div className="form-section">
            <h3>Satellite Scene</h3>
            <div className="upload-zone">
              <p>Drop a Sentinel-1 .SAFE archive or .tif here, or</p>
              <label className="upload-btn">
                Browse Files
                <input type="file" accept=".zip,.tif,.tiff,.SAFE" style={{ display: "none" }} />
              </label>
            </div>
          </div>
        )}

        <div className="form-actions">
          <button type="button" className="btn-secondary" onClick={() => navigate("/analyst")}>
            Cancel
          </button>
          <button type="submit" className="btn-primary" disabled={loading}>
            {loading ? "Creating Investigation..." : "Start Investigation"}
          </button>
        </div>
      </form>
    </div>
  );
}
