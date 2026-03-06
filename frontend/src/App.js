import React, { useEffect, useState, useCallback } from "react";
import ShieldIcon from "./ShieldIcon";
import CameraMap from "./CameraMap";
import "./App.css";

const SEVERITY_CONFIG = {
  severe: { label: "SEVERE", color: "#ef4444", bg: "rgba(239,68,68,.12)" },
  medium: { label: "MEDIUM", color: "#f59e0b", bg: "rgba(245,158,11,.12)" },
  low:    { label: "LOW",    color: "#3b82f6", bg: "rgba(59,130,246,.12)" },
};

function timeAgo(iso) {
  if (!iso) return "ongoing";
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  return `${Math.floor(mins / 60)}h ${mins % 60}m ago`;
}

export default function App() {
  const [cameras, setCameras] = useState([]);
  const [activeCam, setActiveCam] = useState(null);
  const [alerts, setAlerts] = useState([]);
  const [liveAlerts, setLiveAlerts] = useState([]);
  const [backendOk, setBackendOk] = useState(null);

  const fetchData = useCallback(async () => {
    try {
      const [camRes, alertRes, liveRes, statusRes] = await Promise.all([
        fetch("/api/cameras"),
        fetch("/api/notifications/history"),
        fetch("/api/notifications/live"),
        fetch("/api/status"),
      ]);
      const camData = await camRes.json();
      const alertData = await alertRes.json();
      const liveData = await liveRes.json();
      const statusData = await statusRes.json();
      setCameras(camData);
      setAlerts(alertData);
      setLiveAlerts(liveData);
      setBackendOk(statusData.status === "ok");
      if (!activeCam && camData.length) setActiveCam(camData[0]);
    } catch {
      setBackendOk(false);
    }
  }, [activeCam]);

  useEffect(() => {
    fetchData();
    const iv = setInterval(fetchData, 5000);
    return () => clearInterval(iv);
  }, [fetchData]);

  const activeLocation = activeCam?.location ?? { lat: 47.0365, lng: 21.9484 };

  const alertsForCam = liveAlerts.filter(
    (a) => a.source === activeCam?.id || a.type === "environment"
  );

  return (
    <div className="app">
      {/* ── Header ─────────────────────────────────────────── */}
      <header className="header">
        <div className="logo">
          <ShieldIcon size={32} />
          <span className="logo-text">Runway Shield</span>
        </div>
        <div className="header-right">
          <span className={`status-dot ${backendOk ? "green" : backendOk === false ? "red" : ""}`} />
          <span className="status-label">
            {backendOk === null ? "Connecting…" : backendOk ? "Systems Online" : "Offline"}
          </span>
        </div>
      </header>

      {/* ── Main Grid ──────────────────────────────────────── */}
      <main className="dashboard">
        {/* LEFT COLUMN — big stream + alert bar + camera thumbnails */}
        <section className="panel stream-panel">
          <div className="panel-header">
            <span className="panel-title">Camera view</span>
            {activeCam && (
              <span className="panel-badge">{activeCam.name}</span>
            )}
          </div>

          <div className="stream-area">
            <div className="stream-main">
              {activeCam?.online ? (
                <img
                  className="stream-img"
                  src={activeCam.stream_url}
                  alt={activeCam.name}
                />
              ) : (
                <div className="stream-offline">
                  <ShieldIcon size={48} />
                  <p>
                    {activeCam
                      ? "Camera feed unavailable"
                      : "No cameras configured"}
                  </p>
                </div>
              )}

              {/* Alert ticker under the stream */}
              <div className="alert-ticker">
                {alertsForCam.length > 0 ? (
                  alertsForCam.map((a) => {
                    const sev = SEVERITY_CONFIG[a.severity] || SEVERITY_CONFIG.low;
                    return (
                      <span
                        key={a.id}
                        className="ticker-item"
                        style={{ borderColor: sev.color, background: sev.bg }}
                      >
                        <span className="ticker-dot" style={{ background: sev.color }} />
                        <span className="ticker-class">{a.classification}</span>
                        <span className="ticker-sev" style={{ color: sev.color }}>
                          {sev.label}
                        </span>
                      </span>
                    );
                  })
                ) : (
                  <span className="ticker-clear">No active alerts</span>
                )}
              </div>
            </div>

            <div className="cam-thumbs">
              {cameras.map((cam) => (
                <button
                  key={cam.id}
                  className={`cam-thumb ${cam.id === activeCam?.id ? "active" : ""}`}
                  onClick={() => setActiveCam(cam)}
                >
                  <div className="thumb-preview">
                    {cam.online ? (
                      <img src={cam.stream_url} alt={cam.name} />
                    ) : (
                      <div className="thumb-off">
                        <ShieldIcon size={20} />
                      </div>
                    )}
                  </div>
                  <span className="thumb-label">{cam.name}</span>
                </button>
              ))}
            </div>
          </div>
        </section>

        {/* RIGHT COLUMN — Alerts log */}
        <section className="panel alerts-panel">
          <div className="panel-header">
            <span className="panel-title">Alerts</span>
            <span className="panel-count">{alerts.length}</span>
          </div>
          <div className="alerts-list">
            {alerts.length === 0 && (
              <div className="alerts-empty">No alerts recorded</div>
            )}
            {alerts.map((a) => {
              const sev = SEVERITY_CONFIG[a.severity] || SEVERITY_CONFIG.low;
              const active = !a.timestamp_end;
              return (
                <div
                  key={a.id}
                  className={`alert-card ${active ? "alert-active" : ""}`}
                  style={{ borderLeftColor: sev.color }}
                >
                  <div className="alert-top">
                    <span
                      className="alert-severity"
                      style={{ color: sev.color, background: sev.bg }}
                    >
                      {sev.label}
                    </span>
                    <span className="alert-time">
                      {timeAgo(a.timestamp_start)}
                    </span>
                  </div>
                  <div className="alert-body">
                    <span className="alert-class">{a.classification}</span>
                    <span className="alert-source">{a.source}</span>
                  </div>
                  <div className="alert-bottom">
                    <span className={`alert-status status-${a.status}`}>
                      {a.status}
                    </span>
                    {active && <span className="alert-live-dot" />}
                  </div>
                </div>
              );
            })}
          </div>
        </section>

        {/* BOTTOM LEFT — Map */}
        <section className="panel map-panel">
          <div className="panel-header">
            <span className="panel-title">Location</span>
          </div>
          <div className="map-container">
            <CameraMap
              center={[activeLocation.lat, activeLocation.lng]}
              cameras={cameras}
              activeCamId={activeCam?.id}
              onSelectCamera={(cam) => setActiveCam(cam)}
            />
          </div>
        </section>

        {/* BOTTOM RIGHT — System summary */}
        <section className="panel summary-panel">
          <div className="panel-header">
            <span className="panel-title">System</span>
          </div>
          <div className="summary-grid">
            <div className="summary-item">
              <span className="summary-value">{cameras.length}</span>
              <span className="summary-label">Cameras</span>
            </div>
            <div className="summary-item">
              <span className="summary-value">{cameras.filter(c => c.online).length}</span>
              <span className="summary-label">Online</span>
            </div>
            <div className="summary-item severe">
              <span className="summary-value">
                {liveAlerts.filter(a => a.severity === "severe").length}
              </span>
              <span className="summary-label">Severe</span>
            </div>
            <div className="summary-item">
              <span className="summary-value">{liveAlerts.length}</span>
              <span className="summary-label">Active</span>
            </div>
          </div>
        </section>
      </main>
    </div>
  );
}
