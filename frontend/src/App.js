import React, { useEffect, useState, useCallback, useRef } from "react";
import ShieldIcon from "./ShieldIcon";
import CameraMap from "./CameraMap";
import "./App.css";

const SEVERITY_CONFIG = {
  severe: { label: "SEVERE", color: "#f04858", bg: "rgba(240,72,88,.10)" },
  medium: { label: "MEDIUM", color: "#f0a030", bg: "rgba(240,160,48,.10)" },
  low:    { label: "LOW",    color: "#38bdd2", bg: "rgba(56,189,210,.10)" },
};

function timeAgo(iso) {
  if (!iso) return "ongoing";
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  return `${Math.floor(mins / 60)}h ${mins % 60}m ago`;
}

function parseSegmentTimestamp(name) {
  const ts = name.replace(".mp4", "").replace("Z", "");
  const y = ts.slice(0, 4), mo = ts.slice(4, 6), d = ts.slice(6, 8);
  const h = ts.slice(9, 11), mi = ts.slice(11, 13), s = ts.slice(13, 15);
  return new Date(`${y}-${mo}-${d}T${h}:${mi}:${s}Z`);
}

function formatSegmentTime(name) {
  try {
    const d = parseSegmentTimestamp(name);
    return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  } catch {
    return name;
  }
}

function SunIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="5" />
      <line x1="12" y1="1" x2="12" y2="3" />
      <line x1="12" y1="21" x2="12" y2="23" />
      <line x1="4.22" y1="4.22" x2="5.64" y2="5.64" />
      <line x1="18.36" y1="18.36" x2="19.78" y2="19.78" />
      <line x1="1" y1="12" x2="3" y2="12" />
      <line x1="21" y1="12" x2="23" y2="12" />
      <line x1="4.22" y1="19.78" x2="5.64" y2="18.36" />
      <line x1="18.36" y1="5.64" x2="19.78" y2="4.22" />
    </svg>
  );
}

function MoonIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
    </svg>
  );
}

function useTheme() {
  const [theme, setTheme] = useState(() => {
    const stored = localStorage.getItem("rws-theme");
    return stored || "dark";
  });

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem("rws-theme", theme);
  }, [theme]);

  const toggle = useCallback(() => {
    setTheme((t) => (t === "dark" ? "light" : "dark"));
  }, []);

  return [theme, toggle];
}

export default function App() {
  const [cameras, setCameras] = useState([]);
  const [activeCamId, setActiveCamId] = useState(null);
  const [alerts, setAlerts] = useState([]);
  const [liveAlerts, setLiveAlerts] = useState([]);
  const [backendOk, setBackendOk] = useState(null);
  const [theme, toggleTheme] = useTheme();

  const [mode, setMode] = useState("live");
  const [seekSeconds, setSeekSeconds] = useState(0);
  const [streamSrc, setStreamSrc] = useState("");
  const [activeSegment, setActiveSegment] = useState(null);
  const imgRef = useRef(null);
  const vidRef = useRef(null);

  const activeCam = cameras.find((c) => c.id === activeCamId) ?? null;

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
      setActiveCamId((prev) => {
        if (!prev && camData.length) return camData[0].id;
        return prev;
      });
    } catch {
      setBackendOk(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
    const iv = setInterval(fetchData, 5000);
    return () => clearInterval(iv);
  }, [fetchData]);

  useEffect(() => {
    if (!activeCamId) {
      setStreamSrc("");
      return;
    }
    if (mode === "live") {
      const url = seekSeconds > 0
        ? `/api/stream/${activeCamId}/live?offset=${seekSeconds}`
        : `/api/stream/${activeCamId}/live`;
      setStreamSrc(url);
    }
  }, [activeCamId, mode, seekSeconds]);

  const goLive = () => {
    setMode("live");
    setSeekSeconds(0);
    setActiveSegment(null);
    if (vidRef.current) {
      vidRef.current.pause();
      vidRef.current.removeAttribute("src");
    }
  };

  const seekBack = (seconds) => {
    if (!activeCamId) return;
    setActiveSegment(null);

    if (seconds <= 30) {
      setMode("live");
      setSeekSeconds(seconds);
      if (vidRef.current) {
        vidRef.current.pause();
        vidRef.current.removeAttribute("src");
      }
    } else {
      setMode("history");
      setSeekSeconds(seconds);
      const t = (Date.now() / 1000) - seconds;
      setStreamSrc(`/api/stream/${activeCamId}/history?t=${t}`);
    }
  };

  const playSegment = (segName) => {
    if (!activeCamId) return;
    setMode("history");
    setActiveSegment(segName);
    setSeekSeconds(0);
    const segDate = parseSegmentTimestamp(segName);
    const t = segDate.getTime() / 1000;
    setStreamSrc(`/api/stream/${activeCamId}/history?t=${t}`);
  };

  const handleCamSwitch = (cam) => {
    if (cam.id === activeCamId) return;
    setActiveCamId(cam.id);
    goLive();
  };

  const mapCenter = activeCam?.location
    ? [activeCam.location.lat, activeCam.location.lng]
    : [47.0365, 21.9484];

  const alertsForCam = liveAlerts.filter(
    (a) => a.source === activeCam?.id || a.type === "environment"
  );
  const segments = activeCam?.segments ?? [];

  return (
    <div className="app">
      {/* ── Header ─────────────────────────────────────────── */}
      <header className="header">
        <div className="logo">
          <ShieldIcon size={24} />
          <span className="logo-text">Runway Shield</span>
        </div>
        <div className="header-right">
          <button
            className="theme-toggle"
            onClick={toggleTheme}
            aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} mode`}
            title={`Switch to ${theme === "dark" ? "light" : "dark"} mode`}
          >
            {theme === "dark" ? <SunIcon /> : <MoonIcon />}
          </button>
          <span className={`status-dot ${backendOk ? "green" : backendOk === false ? "red" : ""}`} />
          <span className="status-label">
            {backendOk === null ? "Connecting..." : backendOk ? "Systems Online" : "Offline"}
          </span>
        </div>
      </header>

      {/* ── Main Grid ──────────────────────────────────────── */}
      <main className="dashboard">
        {/* LEFT COLUMN */}
        <section className="panel stream-panel">
          <div className="stream-area">
            {/* Top: stream + camera sidebar */}
            <div className="stream-top">
              <div className="stream-main">
                <div className="panel-header">
                  <span className="panel-title">Camera view</span>
                  <div className="panel-header-right">
                    {activeCam && <span className="panel-badge">{activeCam.name}</span>}
                    <span className={`mode-badge ${mode === "live" && !seekSeconds ? "mode-live" : "mode-playback"}`}>
                      {mode === "live" && !seekSeconds ? "LIVE" : seekSeconds ? `-${seekSeconds}s` : "REC"}
                    </span>
                  </div>
                </div>

                {activeCam?.online && streamSrc ? (
                  mode === "history" ? (
                    <video
                      ref={vidRef}
                      className="stream-img"
                      src={streamSrc}
                      autoPlay
                      onEnded={() => {
                        if (activeSegment) {
                          const segs = activeCam.segments ?? [];
                          const idx = segs.indexOf(activeSegment);
                          if (idx >= 0 && idx + 1 < segs.length) {
                            playSegment(segs[idx + 1]);
                          } else {
                            goLive();
                          }
                        } else {
                          goLive();
                        }
                      }}
                    />
                  ) : (
                    <img
                      ref={imgRef}
                      className="stream-img"
                      src={streamSrc}
                      alt={activeCam.name}
                    />
                  )
                ) : (
                  <div className="stream-offline">
                    <ShieldIcon size={36} />
                    <p>{activeCam ? "Camera feed unavailable" : "No cameras configured"}</p>
                  </div>
                )}

                <div className="alert-ticker">
                  {alertsForCam.length > 0 ? (
                    alertsForCam.map((a) => {
                      const sev = SEVERITY_CONFIG[a.severity] || SEVERITY_CONFIG.low;
                      return (
                        <span key={a.id} className="ticker-item" style={{ borderColor: sev.color, background: sev.bg }}>
                          <span className="ticker-dot" style={{ background: sev.color }} />
                          <span className="ticker-class">{a.classification}</span>
                          <span className="ticker-sev" style={{ color: sev.color }}>{sev.label}</span>
                        </span>
                      );
                    })
                  ) : (
                    <span className="ticker-clear">No active alerts</span>
                  )}
                </div>

                <div className="playback-controls">
                  <button
                    className={`ctrl-btn ${mode === "live" && !seekSeconds ? "ctrl-active" : ""}`}
                    onClick={goLive}
                  >
                    <span className="ctrl-live-dot" />
                    Live
                  </button>
                  <div className="ctrl-divider" />
                  {[5, 10, 30].map((s) => (
                    <button
                      key={s}
                      className={`ctrl-btn ${seekSeconds === s && !activeSegment ? "ctrl-active" : ""}`}
                      onClick={() => seekBack(s)}
                    >
                      -{s}s
                    </button>
                  ))}
                  <div className="ctrl-divider" />
                  <div className="ctrl-seek">
                    <label className="ctrl-seek-label">Rewind</label>
                    <input
                      type="range"
                      className="ctrl-slider"
                      min="0"
                      max="30"
                      step="1"
                      value={seekSeconds}
                      onChange={(e) => {
                        const v = parseInt(e.target.value, 10);
                        if (v === 0) goLive();
                        else seekBack(v);
                      }}
                    />
                    <span className="ctrl-seek-val">{seekSeconds}s</span>
                  </div>
                </div>
              </div>

              {/* Camera sidebar */}
              <div className="cam-sidebar">
                <div className="cam-thumbs">
                  {cameras.map((cam) => (
                    <button
                      key={cam.id}
                      className={`cam-thumb ${cam.id === activeCam?.id ? "active" : ""}`}
                      onClick={() => handleCamSwitch(cam)}
                    >
                      <div className="thumb-preview">
                        {cam.online ? (
                          <img src={cam.stream_url} alt={cam.name} />
                        ) : (
                          <div className="thumb-off">
                            <ShieldIcon size={16} />
                          </div>
                        )}
                      </div>
                      <span className="thumb-label">{cam.name}</span>
                    </button>
                  ))}
                </div>

                <div className="segments-box">
                  <div className="segments-title">Recordings</div>
                  <div className="segments-list">
                    {segments.length === 0 ? (
                      <div className="segments-empty">No segments yet</div>
                    ) : (
                      [...segments].reverse().map((seg) => (
                        <button
                          key={seg}
                          className={`segment-item ${activeSegment === seg ? "segment-active" : ""}`}
                          onClick={() => playSegment(seg)}
                        >
                          <span className="segment-dot" />
                          <span className="segment-time">{formatSegmentTime(seg)}</span>
                        </button>
                      ))
                    )}
                  </div>
                </div>
              </div>
            </div>

            {/* Bottom strip: map + system stats */}
            <div className="bottom-strip">
              <div className="map-section">
                <div className="panel-header">
                  <span className="panel-title">Location</span>
                  {activeCam && (
                    <span className="panel-badge">
                      {activeCam.location
                        ? `${activeCam.location.lat.toFixed(4)}, ${activeCam.location.lng.toFixed(4)}`
                        : "N/A"}
                    </span>
                  )}
                </div>
                <div className="map-container">
                  <CameraMap
                    center={mapCenter}
                    cameras={cameras}
                    activeCamId={activeCam?.id}
                    onSelectCamera={(cam) => handleCamSwitch(cam)}
                  />
                </div>
              </div>

              <div className="system-section">
                <div className="panel-header">
                  <span className="panel-title">System</span>
                </div>
                <div className="summary-grid">
                  <div className="summary-item">
                    <span className="summary-value">{cameras.length}</span>
                    <span className="summary-label">Cameras</span>
                  </div>
                  <div className="summary-item">
                    <span className="summary-value">{cameras.filter((c) => c.online).length}</span>
                    <span className="summary-label">Online</span>
                  </div>
                  <div className="summary-item severe">
                    <span className="summary-value">{liveAlerts.filter((a) => a.severity === "severe").length}</span>
                    <span className="summary-label">Severe</span>
                  </div>
                  <div className="summary-item">
                    <span className="summary-value">{liveAlerts.length}</span>
                    <span className="summary-label">Active</span>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </section>

        {/* RIGHT COLUMN -- Alerts */}
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
                    <span className="alert-severity" style={{ color: sev.color, background: sev.bg }}>
                      {sev.label}
                    </span>
                    <span className="alert-time">{timeAgo(a.timestamp_start)}</span>
                  </div>
                  <div className="alert-body">
                    <span className="alert-class">{a.classification}</span>
                    <span className="alert-source">{a.source}</span>
                  </div>
                  <div className="alert-bottom">
                    <span className={`alert-status status-${a.status}`}>{a.status}</span>
                    {active && <span className="alert-live-dot" />}
                  </div>
                </div>
              );
            })}
          </div>
        </section>
      </main>
    </div>
  );
}
