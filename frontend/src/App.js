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

function formatAlertTime(iso) {
  if (!iso) return "";
  try {
    const d = new Date(iso);
    return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  } catch {
    return "";
  }
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

function ReportIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
      <polyline points="14 2 14 8 20 8" />
      <line x1="16" y1="13" x2="8" y2="13" />
      <line x1="16" y1="17" x2="8" y2="17" />
      <polyline points="10 9 9 9 8 9" />
    </svg>
  );
}

function HistoryIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="10" />
      <polyline points="12 6 12 12 16 14" />
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
  const [airportInfo, setAirportInfo] = useState(null);
  const [theme, toggleTheme] = useTheme();

  const [mode, setMode] = useState("live");
  const [seekSeconds, setSeekSeconds] = useState(0);
  const [streamSrc, setStreamSrc] = useState("");
  const [activeSegment, setActiveSegment] = useState(null);
  const imgRef = useRef(null);
  const vidRef = useRef(null);
  const lastFrameRef = useRef(Date.now());

  const activeCam = cameras.find((c) => c.id === activeCamId) ?? null;

  const fetchData = useCallback(async () => {
    try {
      const [camRes, alertRes, liveRes, statusRes, infoRes] = await Promise.all([
        fetch("/api/cameras"),
        fetch("/api/notifications/history"),
        fetch("/api/notifications/live"),
        fetch("/api/status"),
        fetch("/api/airport-info"),
      ]);
      const camData = await camRes.json();
      const alertData = await alertRes.json();
      const liveData = await liveRes.json();
      const statusData = await statusRes.json();
      const infoData = await infoRes.json();
      setCameras(camData);
      setAlerts(alertData);
      setLiveAlerts(liveData);
      setBackendOk(statusData.status === "ok");
      setAirportInfo(infoData);
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
    const iv = setInterval(fetchData, 8081);
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

  // Reconnect the MJPEG stream with a cache-busting param
  const reconnectStream = useCallback(() => {
    if (!activeCamId || mode !== "live") return;
    const base = seekSeconds > 0
      ? `/api/stream/${activeCamId}/live?offset=${seekSeconds}`
      : `/api/stream/${activeCamId}/live`;
    setStreamSrc(base + (base.includes("?") ? "&" : "?") + "_t=" + Date.now());
    lastFrameRef.current = Date.now();
  }, [activeCamId, mode, seekSeconds]);

  // Staleness check: if no MJPEG frame received in 5s, force reconnect
  useEffect(() => {
    if (mode !== "live" || !activeCam?.connected) return;
    const iv = setInterval(() => {
      if (Date.now() - lastFrameRef.current > 5000) {
        reconnectStream();
      }
    }, 3000);
    return () => clearInterval(iv);
  }, [mode, activeCam?.connected, reconnectStream]);

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
  const env = airportInfo?.environmental;
  const runway = airportInfo?.runway_status;

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

      {/* ── Main Layout: Left Sidebar + Content ────────────── */}
      <div className="main-layout">
        {/* LEFT SIDEBAR */}
        <aside className="left-sidebar">
          <div className="sidebar-airport">
            <div className="airport-name">
              {airportInfo?.name || "Aeroportul Internațional Oradea"}
            </div>
            <div className="airport-code">({airportInfo?.code || "OMR"})</div>
            <div className="airport-thumb">
              <img
                src="https://upload.wikimedia.org/wikipedia/commons/thumb/e/e0/Oradea_airport_terminal.jpg/320px-Oradea_airport_terminal.jpg"
                alt="Oradea Airport"
              />
            </div>
          </div>

          <nav className="sidebar-nav">
            <button className="sidebar-nav-item">
              <ReportIcon />
              <span>Reports</span>
            </button>
            <button className="sidebar-nav-item">
              <HistoryIcon />
              <span>Incident history</span>
            </button>
          </nav>

          <div className="sidebar-section">
            <div className="sidebar-section-title">Environmental Conditions</div>
            <div className="sidebar-stats">
              <div className="sidebar-stat-row">
                <span className="stat-label">Temperature</span>
                <span className="stat-value">{env ? `${env.temperature}${env.temperature_unit}` : "--"}</span>
              </div>
              <div className="sidebar-stat-row">
                <span className="stat-label">Wind speed</span>
                <span className="stat-value">{env ? `${env.wind_speed} ${env.wind_unit}` : "--"}</span>
              </div>
            </div>
          </div>

          <div className="sidebar-section">
            <div className="sidebar-section-title">Runway Status</div>
            <div className="sidebar-stats">
              <div className="sidebar-stat-row">
                <span className="stat-label">Live incidents</span>
                <span className="stat-value stat-highlight">{runway?.live_incidents ?? "--"}</span>
              </div>
              <div className="sidebar-stat-row">
                <span className="stat-label">Past 24hr</span>
                <span className="stat-value">{runway?.past_24hr ?? "--"}</span>
              </div>
              <div className="sidebar-stat-row">
                <span className="stat-label">Surface condition</span>
                <span className="stat-value">{runway?.surface_condition ?? "--"}</span>
              </div>
            </div>
          </div>
        </aside>

        {/* MAIN CONTENT */}
        <main className="dashboard">
          {/* CAMERA VIEW (top area) */}
          <section className="panel stream-panel">
            <div className="stream-area">
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

                  {activeCam?.connected && streamSrc ? (
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
                        onLoad={() => { lastFrameRef.current = Date.now(); }}
                        onError={() => { setTimeout(reconnectStream, 2000); }}
                      />
                    )
                  ) : (
                    <div className="stream-offline">
                      <ShieldIcon size={36} />
                      <p>{activeCam ? (activeCam.online ? "Camera disconnected — waiting for reconnect..." : "Camera feed unavailable") : "No cameras configured"}</p>
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
                    <div className="timeline-bar"
                      onMouseDown={(e) => {
                        const bar = e.currentTarget;
                        const update = (clientX) => {
                          const rect = bar.getBoundingClientRect();
                          const ratio = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width));
                          const secs = Math.round((1 - ratio) * 30);
                          if (secs === 0) goLive();
                          else seekBack(secs);
                        };
                        update(e.clientX);
                        const onMove = (ev) => update(ev.clientX);
                        const onUp = () => {
                          window.removeEventListener("mousemove", onMove);
                          window.removeEventListener("mouseup", onUp);
                        };
                        window.addEventListener("mousemove", onMove);
                        window.addEventListener("mouseup", onUp);
                      }}
                      onTouchStart={(e) => {
                        const bar = e.currentTarget;
                        const update = (clientX) => {
                          const rect = bar.getBoundingClientRect();
                          const ratio = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width));
                          const secs = Math.round((1 - ratio) * 30);
                          if (secs === 0) goLive();
                          else seekBack(secs);
                        };
                        update(e.touches[0].clientX);
                        const onMove = (ev) => update(ev.touches[0].clientX);
                        const onEnd = () => {
                          window.removeEventListener("touchmove", onMove);
                          window.removeEventListener("touchend", onEnd);
                        };
                        window.addEventListener("touchmove", onMove);
                        window.addEventListener("touchend", onEnd);
                      }}
                    >
                      <div className="timeline-track">
                        <div className="timeline-filled" style={{ width: `${((30 - seekSeconds) / 30) * 100}%` }} />
                        <div className="timeline-thumb" style={{ left: `${((30 - seekSeconds) / 30) * 100}%` }} />
                        {[0, 5, 10, 15, 20, 25, 30].map((s) => (
                          <div key={s} className="timeline-tick" style={{ left: `${((30 - s) / 30) * 100}%` }} />
                        ))}
                      </div>
                      <div className="timeline-labels">
                        <span>-30s</span>
                        <span>-20s</span>
                        <span>-10s</span>
                        <span className="timeline-label-live">
                          <span className="ctrl-live-dot" />
                          LIVE
                        </span>
                      </div>
                    </div>
                    {(seekSeconds > 0 || activeSegment) && (
                      <div className="timeline-status">
                        <button className="ctrl-btn" onClick={goLive}>
                          <span className="ctrl-live-dot" /> Go live
                        </button>
                        <span className="timeline-offset">-{seekSeconds}s</span>
                      </div>
                    )}
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
                          {cam.connected ? (
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
            </div>
          </section>

          {/* BOTTOM ROW: Airport Map + Alerts side by side */}
          <section className="bottom-row">
            <div className="bottom-map-panel panel">
              <div className="panel-header">
                <span className="panel-title">Airport map</span>
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

            <div className="bottom-alerts-panel panel">
              <div className="panel-header">
                <span className="panel-title">Alerts</span>
                <button className="show-all-btn">Show all</button>
              </div>
              <div className="bottom-alerts-list">
                {alerts.length === 0 && (
                  <div className="alerts-empty">No alerts recorded</div>
                )}
                {alerts.map((a) => {
                  const sev = SEVERITY_CONFIG[a.severity] || SEVERITY_CONFIG.low;
                  return (
                    <div
                      key={a.id}
                      className="bottom-alert-item"
                      style={{ borderLeftColor: sev.color }}
                    >
                      <div className="bottom-alert-content">
                        <span className="bottom-alert-msg">{a.classification}</span>
                        <span className={`bottom-alert-status status-${a.status}`}>{a.status?.toUpperCase()}</span>
                      </div>
                      <span className="bottom-alert-time">{formatAlertTime(a.timestamp_start) || timeAgo(a.timestamp_start)}</span>
                    </div>
                  );
                })}
              </div>
            </div>
          </section>
        </main>
      </div>
    </div>
  );
}
