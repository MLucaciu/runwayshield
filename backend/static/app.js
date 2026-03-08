"use strict";

  // ── State ───────────────────────────────────────────────────────
  let cameras = [];
  let activeCamId = null;
  let backendOk = null;
  let airportInfo = null;
  let zoneAlerts = [];
  let liveAlerts = [];
  let zonesConfig = null;

  let mode = "live";
  let seekSeconds = 0;
  let streamSrc = "";
  let activeSegment = null;
  let annotated = false;
  let showZones = false;
  let lastFrameTime = Date.now();

  // ── DOM refs ────────────────────────────────────────────────────
  const $ = (id) => document.getElementById(id);
  const statusDot = $("statusDot");
  const statusLabel = $("statusLabel");
  const themeToggle = $("themeToggle");
  const sunIcon = $("sunIcon");
  const moonIcon = $("moonIcon");
  const airportNameEl = $("airportName");
  const airportCodeEl = $("airportCode");
  const envTemp = $("envTemp");
  const envHumidity = $("envHumidity");
  const envPressure = $("envPressure");
  const envRain = $("envRain");
  const runwayLive = $("runwayLive");
  const runway24hr = $("runway24hr");
  const runwaySurface = $("runwaySurface");
  const streamImg = $("streamImg");
  const streamVid = $("streamVid");
  const streamOffline = $("streamOffline");
  const offlineMsg = $("offlineMsg");
  const annotationTrack = $("annotationTrack");
  const zonesTrack = $("zonesTrack");
  const camNameBadge = $("camNameBadge");
  const modeBadge = $("modeBadge");
  const alertTicker = $("alertTicker");
  const timelineBar = $("timelineBar");
  const timelineFilled = $("timelineFilled");
  const timelineThumb = $("timelineThumb");
  const timelineStatus = $("timelineStatus");
  const goLiveBtn = $("goLiveBtn");
  const timelineOffset = $("timelineOffset");
  const camThumbs = $("camThumbs");
  const segmentsList = $("segmentsList");
  const mapCoords = $("mapCoords");
  const zoneAlertTitle = $("zoneAlertTitle");
  const zoneAlertCount = $("zoneAlertCount");
  const ackFirstBtn = $("ackFirstBtn");
  const zoneAlertsList = $("zoneAlertsList");

  // ── Severity config ─────────────────────────────────────────────
  const SEV = {
    high:   { label: "HIGH",   color: "#f04858", bg: "rgba(240,72,88,.10)" },
    medium: { label: "MEDIUM", color: "#f0a030", bg: "rgba(240,160,48,.10)" },
    low:    { label: "LOW",    color: "#38bdd2", bg: "rgba(56,189,210,.10)" },
    warning:{ label: "WARNING",color: "#f0a030", bg: "rgba(240,160,48,.07)" },
  };

  // ── Helpers ─────────────────────────────────────────────────────
  function parseSegTs(name) {
    const ts = name.replace(".mp4", "").replace("Z", "");
    const y = ts.slice(0,4), mo = ts.slice(4,6), d = ts.slice(6,8);
    const h = ts.slice(9,11), mi = ts.slice(11,13), s = ts.slice(13,15);
    return new Date(y + "-" + mo + "-" + d + "T" + h + ":" + mi + ":" + s + "Z");
  }

  function fmtSegTime(name) {
    try { return parseSegTs(name).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }); }
    catch { return name; }
  }

  function fmtAlertTime(iso) {
    if (!iso) return "";
    try {
      const d = new Date(iso);
      const now = new Date();
      const isToday = d.toDateString() === now.toDateString();
      const time = d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
      if (isToday) return time;
      const day = d.toLocaleDateString([], { month: "short", day: "numeric" });
      return day + " " + time;
    } catch { return ""; }
  }

  function getActiveCam() {
    return cameras.find(c => c.id === activeCamId) || null;
  }

  // ── Theme ───────────────────────────────────────────────────────
  let theme = localStorage.getItem("rws-theme") || "dark";
  document.documentElement.setAttribute("data-theme", theme);
  updateThemeIcon();

  function updateThemeIcon() {
    if (theme === "dark") {
      sunIcon.style.display = "";
      moonIcon.style.display = "none";
    } else {
      sunIcon.style.display = "none";
      moonIcon.style.display = "";
    }
  }

  themeToggle.addEventListener("click", () => {
    theme = theme === "dark" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem("rws-theme", theme);
    updateThemeIcon();
  });

  // ── Data fetching ───────────────────────────────────────────────
  async function fetchData() {
    try {
      const [camRes, alertRes, liveRes, statusRes, infoRes, zoneAlertRes, zonesRes] = await Promise.all([
        fetch("/api/cameras"),
        fetch("/api/notifications/history"),
        fetch("/api/notifications/live"),
        fetch("/api/status"),
        fetch("/api/airport-info"),
        fetch("/api/alerts/live"),
        fetch("/api/zones"),
      ]);
      cameras = await camRes.json();
      await alertRes.json();
      liveAlerts = await liveRes.json();
      const statusData = await statusRes.json();
      airportInfo = await infoRes.json();
      zoneAlerts = await zoneAlertRes.json();
      zonesConfig = await zonesRes.json();

      backendOk = statusData.status === "ok";

      if (!activeCamId && cameras.length) {
        activeCamId = cameras[0].id;
      }

      updateUI();
    } catch {
      backendOk = false;
      updateStatusIndicator();
    }
  }

  fetchData();
  setInterval(fetchData, 30000);

  // ── WebSocket (real-time alerts) ────────────────────────────────
  const socket = io({ transports: ["websocket", "polling"] });

  socket.on("connect", () => {
    console.log("[ws] connected");
  });

  socket.on("disconnect", () => {
    console.log("[ws] disconnected");
  });

  socket.on("alerts_snapshot", (data) => {
    zoneAlerts = data;
    updateAlertTicker();
    updateZoneAlerts();
    updateMap();
  });

  socket.on("alert_event", (data) => {
    const evt = data.event;
    const alert = data.alert;

    if (evt === "alert_new" || evt === "warning_new") {
      const idx = zoneAlerts.findIndex(a => a.id === alert.id);
      if (idx >= 0) zoneAlerts[idx] = alert;
      else zoneAlerts.unshift(alert);
    } else if (evt === "warning_escalated") {
      const idx = zoneAlerts.findIndex(a => a.id === alert.id);
      if (idx >= 0) zoneAlerts[idx] = alert;
      else zoneAlerts.unshift(alert);
    } else if (evt === "alert_acknowledged") {
      const idx = zoneAlerts.findIndex(a => a.id === alert.id);
      if (idx >= 0) zoneAlerts[idx] = alert;
    } else if (evt === "alert_closed" || evt === "alert_resolved" || evt === "warning_closed") {
      const idx = zoneAlerts.findIndex(a => a.id === alert.id);
      if (idx >= 0) zoneAlerts[idx] = alert;
      else zoneAlerts.unshift(alert);
    }

    updateAlertTicker();
    updateZoneAlerts();
    updateMap();
  });

  // ── UI update orchestrator ──────────────────────────────────────
  function updateUI() {
    updateStatusIndicator();
    updateSidebar();
    updateCamThumbs();
    updateStream();
    updateSegments();
    updateAlertTicker();
    updateZoneAlerts();
    updateMap();
  }

  function updateStatusIndicator() {
    statusDot.className = "status-dot" + (backendOk ? " green" : backendOk === false ? " red" : "");
    statusLabel.textContent = backendOk === null ? "Connecting..." : backendOk ? "Systems Online" : "Offline";
  }

  // ── Sidebar ─────────────────────────────────────────────────────
  function updateSidebar() {
    if (airportInfo) {
      airportNameEl.textContent = airportInfo.name || "Aeroportul Internațional Oradea";
      airportCodeEl.textContent = "(" + (airportInfo.code || "OMR") + ")";
    }

    const env = airportInfo?.environmental;
    envTemp.textContent = env?.temperature != null ? env.temperature + (env.temperature_unit || "") : "--";
    envHumidity.textContent = env?.humidity != null ? env.humidity + (env.humidity_unit || "") : "--";
    envPressure.textContent = env?.pressure != null ? env.pressure + " " + (env.pressure_unit || "") : "--";

    if (env?.rain_detected != null) {
      envRain.textContent = env.rain_detected ? "Rain detected" : "Clear";
      envRain.className = "stat-value" + (env.rain_detected ? " stat-alert" : "");
    } else {
      envRain.textContent = "--";
      envRain.className = "stat-value";
    }

    const rwy = airportInfo?.runway_status;
    runwayLive.textContent = rwy?.live_incidents ?? "--";
    runway24hr.textContent = rwy?.past_24hr ?? "--";
    runwaySurface.textContent = rwy?.surface_condition ?? "--";
    runwaySurface.className = "stat-value" + (rwy?.surface_condition && rwy.surface_condition !== "Dry" ? " stat-alert" : "");
  }

  // ── Camera thumbs ──────────────────────────────────────────────
  let _thumbIntervals = [];

  function updateCamThumbs() {
    // Clear existing snapshot refresh timers
    _thumbIntervals.forEach(id => clearInterval(id));
    _thumbIntervals = [];
    camThumbs.innerHTML = "";
    cameras.forEach(cam => {
      const btn = document.createElement("button");
      btn.className = "cam-thumb" + (cam.id === activeCamId ? " active" : "");
      btn.addEventListener("click", () => handleCamSwitch(cam));

      const preview = document.createElement("div");
      preview.className = "thumb-preview";
      if (cam.connected) {
        const img = document.createElement("img");
        const snapshotUrl = "/api/stream/" + cam.id + "/snapshot";
        img.src = snapshotUrl + "?_t=" + Date.now();
        img.alt = cam.name;
        preview.appendChild(img);
        // Refresh snapshot every 1s without holding a persistent connection
        const iid = setInterval(() => {
          img.src = snapshotUrl + "?_t=" + Date.now();
        }, 1000);
        _thumbIntervals.push(iid);
      } else {
        const off = document.createElement("div");
        off.className = "thumb-off";
        off.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="16" height="16"><path d="M32 4 L56 16 V34 C56 48 44 58 32 62 C20 58 8 48 8 34 V16 Z" fill="currentColor" opacity="0.4"/></svg>';
        preview.appendChild(off);
      }
      btn.appendChild(preview);

      const label = document.createElement("span");
      label.className = "thumb-label";
      label.textContent = cam.name;
      btn.appendChild(label);

      camThumbs.appendChild(btn);
    });
  }

  // ── Stream display ─────────────────────────────────────────────
  function updateStream() {
    const cam = getActiveCam();

    if (cam) {
      camNameBadge.textContent = cam.name;
      camNameBadge.style.display = "";
    } else {
      camNameBadge.style.display = "none";
    }

    updateModeBadge();
    updateTimelineUI();
  }

  function buildStreamSrc() {
    if (!activeCamId) return "";
    const params = new URLSearchParams();
    if (annotated) params.set("annotated", "1");
    if (showZones) params.set("zones", "1");

    if (mode === "live") {
      if (seekSeconds > 0) params.set("offset", seekSeconds);
      const qs = params.toString();
      return "/api/stream/" + activeCamId + "/live" + (qs ? "?" + qs : "");
    } else {
      let t;
      if (activeSegment) {
        t = parseSegTs(activeSegment).getTime() / 1000;
      } else {
        t = (Date.now() / 1000) - seekSeconds;
      }
      params.set("t", t);
      return "/api/stream/" + activeCamId + "/history?" + params;
    }
  }

  function applyStream() {
    const cam = getActiveCam();
    streamSrc = buildStreamSrc();

    if (cam?.connected && streamSrc) {
      streamOffline.style.display = "none";
      if (mode === "history") {
        streamImg.style.display = "none";
        streamImg.src = "";
        streamVid.style.display = "block";
        streamVid.src = streamSrc;
        streamVid.load();
        streamVid.play().catch(() => {});
      } else {
        streamVid.style.display = "none";
        streamVid.pause();
        streamVid.removeAttribute("src");
        // Abort old MJPEG connection before starting new one to avoid connection exhaustion
        streamImg.removeAttribute("src");
        streamImg.style.display = "block";
        streamImg.src = streamSrc;
      }
    } else {
      streamImg.removeAttribute("src");
      streamImg.style.display = "none";
      streamVid.style.display = "none";
      streamOffline.style.display = "";
      if (cam) {
        offlineMsg.textContent = cam.online ? "Camera disconnected — waiting for reconnect..." : "Camera feed unavailable";
      } else {
        offlineMsg.textContent = "No cameras configured";
      }
    }
  }

  function updateModeBadge() {
    if (mode === "live" && !seekSeconds) {
      modeBadge.textContent = "LIVE";
      modeBadge.className = "mode-badge mode-live";
    } else if (seekSeconds) {
      modeBadge.textContent = "-" + seekSeconds + "s";
      modeBadge.className = "mode-badge mode-playback";
    } else {
      modeBadge.textContent = "REC";
      modeBadge.className = "mode-badge mode-playback";
    }
  }

  function updateTimelineUI() {
    const pct = ((30 - Math.min(seekSeconds, 30)) / 30) * 100;
    timelineFilled.style.width = pct + "%";
    timelineThumb.style.left = pct + "%";

    if (seekSeconds > 0 || activeSegment) {
      timelineStatus.style.display = "";
      timelineOffset.textContent = "-" + seekSeconds + "s";
    } else {
      timelineStatus.style.display = "none";
    }
  }

  // ── Stream actions ─────────────────────────────────────────────
  function goLive() {
    mode = "live";
    seekSeconds = 0;
    activeSegment = null;
    applyStream();
    updateModeBadge();
    updateTimelineUI();
    renderSegmentsList();
  }

  function seekBack(seconds) {
    if (!activeCamId) return;
    activeSegment = null;
    if (seconds <= 30) {
      mode = "live";
      seekSeconds = seconds;
    } else {
      mode = "history";
      seekSeconds = seconds;
    }
    applyStream();
    updateModeBadge();
    updateTimelineUI();
  }

  function playSegment(segName) {
    if (!activeCamId) return;
    mode = "history";
    activeSegment = segName;
    seekSeconds = 0;
    applyStream();
    updateModeBadge();
    updateTimelineUI();
    renderSegmentsList();
  }

  function handleCamSwitch(cam) {
    if (cam.id === activeCamId) return;
    activeCamId = cam.id;
    goLive();
    updateCamThumbs();
    updateStream();
    updateSegments();
    updateMap();
  }

  // ── Reconnect (staleness) ──────────────────────────────────────
  streamImg.addEventListener("load", () => { lastFrameTime = Date.now(); });
  streamImg.addEventListener("error", () => { setTimeout(reconnectStream, 2000); });

  function reconnectStream() {
    if (!activeCamId || mode !== "live") return;
    const params = new URLSearchParams();
    if (seekSeconds > 0) params.set("offset", seekSeconds);
    if (annotated) params.set("annotated", "1");
    if (showZones) params.set("zones", "1");
    params.set("_t", Date.now());
    streamImg.src = "/api/stream/" + activeCamId + "/live?" + params;
    lastFrameTime = Date.now();
  }

  setInterval(() => {
    if (mode !== "live" || !getActiveCam()?.connected) return;
    if (Date.now() - lastFrameTime > 5000) reconnectStream();
  }, 3000);

  // ── Video ended handler ────────────────────────────────────────
  streamVid.addEventListener("ended", () => {
    if (mode !== "history") return;
    const cam = getActiveCam();
    if (activeSegment && cam) {
      const segs = cam.segments || [];
      const idx = segs.indexOf(activeSegment);
      if (idx >= 0 && idx + 1 < segs.length) {
        playSegment(segs[idx + 1]);
      } else {
        goLive();
      }
    } else {
      goLive();
    }
  });

  // ── Toggles ────────────────────────────────────────────────────
  annotationTrack.parentElement.addEventListener("click", () => {
    annotated = !annotated;
    annotationTrack.classList.toggle("on", annotated);
    applyStream();
  });

  zonesTrack.parentElement.addEventListener("click", () => {
    showZones = !showZones;
    zonesTrack.classList.toggle("on", showZones);
    applyStream();
  });

  // ── Timeline scrubber ──────────────────────────────────────────
  function handleTimelineDrag(e) {
    const bar = timelineBar;
    const update = (clientX) => {
      const rect = bar.getBoundingClientRect();
      const ratio = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width));
      const secs = Math.round((1 - ratio) * 30);
      if (secs === 0) goLive();
      else seekBack(secs);
    };

    if (e.type === "mousedown") {
      update(e.clientX);
      const onMove = (ev) => update(ev.clientX);
      const onUp = () => { window.removeEventListener("mousemove", onMove); window.removeEventListener("mouseup", onUp); };
      window.addEventListener("mousemove", onMove);
      window.addEventListener("mouseup", onUp);
    } else if (e.type === "touchstart") {
      update(e.touches[0].clientX);
      const onMove = (ev) => update(ev.touches[0].clientX);
      const onEnd = () => { window.removeEventListener("touchmove", onMove); window.removeEventListener("touchend", onEnd); };
      window.addEventListener("touchmove", onMove);
      window.addEventListener("touchend", onEnd);
    }
  }

  timelineBar.addEventListener("mousedown", handleTimelineDrag);
  timelineBar.addEventListener("touchstart", handleTimelineDrag);
  goLiveBtn.addEventListener("click", goLive);

  // ── Segments ───────────────────────────────────────────────────
  function updateSegments() {
    renderSegmentsList();
  }

  function renderSegmentsList() {
    const cam = getActiveCam();
    const segs = cam?.segments || [];

    if (!segs.length) {
      segmentsList.innerHTML = '<div class="segments-empty">No segments yet</div>';
      return;
    }

    segmentsList.innerHTML = "";
    [...segs].reverse().forEach(seg => {
      const btn = document.createElement("button");
      btn.className = "segment-item" + (activeSegment === seg ? " segment-active" : "");
      btn.addEventListener("click", () => playSegment(seg));

      const dot = document.createElement("span");
      dot.className = "segment-dot";
      btn.appendChild(dot);

      const time = document.createElement("span");
      time.className = "segment-time";
      time.textContent = fmtSegTime(seg);
      btn.appendChild(time);

      segmentsList.appendChild(btn);
    });
  }

  // ── Alert ticker ───────────────────────────────────────────────
  function updateAlertTicker() {
    const cam = getActiveCam();
    const alertsForCam = liveAlerts.filter(a => a.source === cam?.id || a.type === "environment");

    alertTicker.innerHTML = "";

    if (zoneAlerts.length > 0) {
      zoneAlerts.forEach(a => {
        const isWarning = a.alert_type === "warning";
        const sev = isWarning ? SEV.warning : (SEV[a.severity] || SEV.low);
        const span = document.createElement("span");
        span.className = "ticker-item" + (isWarning ? " is-warning" : "");
        span.style.borderColor = sev.color;
        span.style.background = sev.bg;
        const label = isWarning ? "WARNING" : sev.label;
        const prefix = isWarning ? "⚠ " : "";
        span.innerHTML =
          '<span class="ticker-dot" style="background:' + sev.color + '"></span>' +
          '<span class="ticker-class">' + prefix + esc(a.object_type) + ' → ' + esc(a.zone_id) + '</span>' +
          '<span class="ticker-sev" style="color:' + sev.color + '">' + label + '</span>';
        alertTicker.appendChild(span);
      });
    } else if (alertsForCam.length > 0) {
      alertsForCam.forEach(a => {
        const sev = SEV[a.severity] || SEV.low;
        const span = document.createElement("span");
        span.className = "ticker-item";
        span.style.borderColor = sev.color;
        span.style.background = sev.bg;
        span.innerHTML =
          '<span class="ticker-dot" style="background:' + sev.color + '"></span>' +
          '<span class="ticker-class">' + esc(a.classification) + '</span>' +
          '<span class="ticker-sev" style="color:' + sev.color + '">' + sev.label + '</span>';
        alertTicker.appendChild(span);
      });
    } else {
      alertTicker.innerHTML = '<span class="ticker-clear">No active alerts</span>';
    }
  }

  function esc(s) {
    if (!s) return "";
    const d = document.createElement("div");
    d.textContent = s;
    return d.innerHTML;
  }

  // ── Zone alerts panel ──────────────────────────────────────────
  function updateZoneAlerts() {
    const alertCount = zoneAlerts.filter(a => a.alert_type !== "warning").length;
    const warningCount = zoneAlerts.filter(a => a.alert_type === "warning").length;
    zoneAlertCount.textContent = alertCount + (warningCount ? " + " + warningCount + "w" : "");
    zoneAlertTitle.textContent = warningCount ? "Zone Alerts & Warnings" : "Zone Alerts";

    const hasActive = zoneAlerts.some(a => a.status === "active" && a.alert_type !== "warning");
    ackFirstBtn.style.display = hasActive ? "" : "none";

    if (!zoneAlerts.length) {
      zoneAlertsList.innerHTML = '<div class="alerts-empty">No active zone alerts</div>';
      return;
    }

    // Sort: active first, then acknowledged, then resolved/closed
    const ORDER = { active: 0, acknowledged: 1, resolved: 2, closed: 2 };
    const sorted = [...zoneAlerts].sort((a, b) => {
      const wa = a.alert_type === "warning" ? 0.5 : 0;
      const wb = b.alert_type === "warning" ? 0.5 : 0;
      return (ORDER[a.status] || 0) + wa - ((ORDER[b.status] || 0) + wb);
    });

    zoneAlertsList.innerHTML = "";
    sorted.forEach(a => {
      const isWarning = a.alert_type === "warning";
      const isClosed = a.status === "resolved" || a.status === "closed";
      const sev = isWarning ? SEV.warning : (SEV[a.severity] || SEV.low);
      const item = document.createElement("div");
      item.className = "bottom-alert-item" + (isWarning ? " is-warning" : "") + (isClosed ? " is-closed" : "");
      item.style.borderLeftColor = isClosed ? "var(--text-dim)" : sev.color;
      if (isClosed) item.style.opacity = "0.55";

      const content = document.createElement("div");
      content.className = "bottom-alert-content";

      const msg = document.createElement("span");
      msg.className = "bottom-alert-msg";
      const verb = isWarning ? " → " : " in ";
      msg.textContent = (a.object_type || "") + verb + (a.zone_name || a.zone_id || "");
      content.appendChild(msg);

      const meta = document.createElement("span");
      meta.className = "bottom-alert-status";

      if (isWarning) {
        const warnBadge = document.createElement("span");
        warnBadge.className = "warning-badge";
        warnBadge.textContent = "TRAJECTORY WARNING";
        meta.appendChild(warnBadge);
      } else {
        const statusSpan = document.createElement("span");
        statusSpan.className = "status-" + (a.status || "");
        statusSpan.textContent = (a.status || "").toUpperCase();
        meta.appendChild(statusSpan);
      }

      if (a.created_at) {
        const ts = document.createElement("span");
        ts.style.cssText = "color:var(--text-muted);margin-left:0.5em;font-weight:500;";
        ts.textContent = fmtAlertTime(a.created_at);
        meta.appendChild(ts);
      }
      content.appendChild(meta);

      item.appendChild(content);

      const actions = document.createElement("div");
      actions.className = "bottom-alert-actions";

      const time = document.createElement("span");
      time.className = "bottom-alert-time";
      time.textContent = fmtAlertTime(a.created_at);
      actions.appendChild(time);

      if (!isWarning && a.status === "active") {
        const ackBtn = document.createElement("button");
        ackBtn.className = "ack-btn-react";
        ackBtn.textContent = "ACK";
        ackBtn.addEventListener("click", (e) => { e.stopPropagation(); acknowledgeAlert(a.id); });
        actions.appendChild(ackBtn);
      } else if (!isWarning && a.status === "acknowledged") {
        const lbl = document.createElement("span");
        lbl.className = "ack-label";
        lbl.textContent = a.acknowledged_by || "";
        actions.appendChild(lbl);
      }

      if (!isWarning) {
        const detBtn = document.createElement("button");
        detBtn.className = "detail-btn-react";
        detBtn.textContent = "DETAILS";
        detBtn.addEventListener("click", (e) => { e.stopPropagation(); openAlertModal(a); });
        actions.appendChild(detBtn);
      }

      item.appendChild(actions);
      zoneAlertsList.appendChild(item);
    });
  }

  async function acknowledgeAlert(alertId) {
    try {
      await fetch("/api/alerts/" + alertId + "/acknowledge", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ acknowledged_by: "operator" }),
      });
      fetchData();
    } catch {}
  }

  ackFirstBtn.addEventListener("click", () => {
    const first = zoneAlerts.find(a => a.status === "active" && a.alert_type !== "warning");
    if (first) acknowledgeAlert(first.id);
  });

  // ── Alert detail modal ─────────────────────────────────────────
  const alertModalOverlay = document.getElementById("alertModalOverlay");
  const alertModalClose = document.getElementById("alertModalClose");
  const alertModalTitle = document.getElementById("alertModalTitle");
  const alertModalBody = document.getElementById("alertModalBody");

  function closeAlertModal() {
    alertModalOverlay.classList.remove("open");
    const vid = alertModalBody.querySelector("video");
    if (vid) vid.pause();
    alertModalBody.innerHTML = "";
  }

  alertModalClose.addEventListener("click", closeAlertModal);
  alertModalOverlay.addEventListener("click", (e) => { if (e.target === alertModalOverlay) closeAlertModal(); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeAlertModal(); });

  function amDetail(label, value) {
    return '<div class="alert-modal-detail"><span class="alert-modal-detail-label">' +
      esc(label) + '</span><span class="alert-modal-detail-value">' + esc(value || "—") + '</span></div>';
  }

  function fmtDt(ts) {
    if (!ts) return "—";
    return new Date(ts).toLocaleString();
  }

  async function openAlertModal(alertData) {
    let a = alertData;
    try {
      const res = await fetch("/api/alerts/" + alertData.id);
      if (res.ok) { const fresh = await res.json(); fresh.camera_name = alertData.camera_name || fresh.camera_name; a = fresh; }
    } catch(e) {}

    const zoneName = a.zone_name || a.zone_id || "Unknown Zone";
    alertModalTitle.textContent = (a.object_type || "Alert") + " in " + zoneName + " — #" + a.id;

    const camEncoded = encodeURIComponent(a.camera_id);
    const createdMs = new Date(a.created_at).getTime();
    const ageSeconds = (Date.now() - createdMs) / 1000;
    const isRecent = a.status === "active" || ageSeconds < 30;

    let html = "";
    if (isRecent) {
      const offset = Math.max(0, Math.min(30, Math.round(ageSeconds)));
      const liveUrl = "/api/stream/" + camEncoded + "/live?annotated=1" + (offset > 0 ? "&offset=" + offset : "");
      html += '<div class="alert-modal-video-wrap"><img id="amLive" src="' + esc(liveUrl) + '" alt="Live stream"></div>';
    } else {
      const histUrl = "/api/stream/" + camEncoded + "/history?t=" + (createdMs / 1000) + "&annotated=1";
      html += '<div class="alert-modal-video-wrap"><video id="amVideo" controls preload="auto"><source src="' + esc(histUrl) + '" type="video/mp4"></video></div>';
    }

    html += '<div class="alert-modal-details">';
    html += amDetail("ID", "#" + a.id);
    html += amDetail("Severity", (a.severity || "").toUpperCase());
    html += amDetail("Object", a.object_type);
    html += amDetail("Zone", zoneName);
    html += amDetail("Camera", a.camera_name || a.camera_id);
    html += amDetail("Status", (a.status || "").toUpperCase());
    html += amDetail("Created", fmtDt(a.created_at));
    html += amDetail("Last updated", fmtDt(a.updated_at));
    html += amDetail("Acked by", a.acknowledged_by);
    html += amDetail("Acked at", fmtDt(a.acknowledged_at));
    html += amDetail("Closed at", fmtDt(a.closed_at));
    if (a.gps_lat != null && a.gps_lng != null) {
      html += amDetail("GPS", a.gps_lat.toFixed(5) + ", " + a.gps_lng.toFixed(5));
    }
    html += '</div>';

    alertModalBody.innerHTML = html;

    let logs = a.logs || [];
    if (!logs.length) {
      try { const lr = await fetch("/api/alerts/" + a.id + "/logs"); logs = await lr.json(); } catch(e) {}
    }
    if (logs.length) {
      let logsHtml = '<div class="alert-modal-logs-title">Audit Log</div><div class="alert-modal-logs">';
      logs.forEach(log => {
        logsHtml += '<div class="alert-modal-log-entry">' +
          '<span class="alert-modal-log-action">' + esc(log.action) + '</span>' +
          '<span class="alert-modal-log-time">' + esc(fmtDt(log.timestamp)) + '</span>' +
          '</div>';
      });
      logsHtml += '</div>';
      alertModalBody.insertAdjacentHTML("beforeend", logsHtml);
    }

    const vid = alertModalBody.querySelector("#amVideo");
    if (vid) vid.addEventListener("error", () => { vid.parentElement.innerHTML = '<div class="alert-modal-no-video">No video available</div>'; });
    const liveImg = alertModalBody.querySelector("#amLive");
    if (liveImg) liveImg.addEventListener("error", () => { liveImg.parentElement.innerHTML = '<div class="alert-modal-no-video">Live stream unavailable</div>'; });

    alertModalOverlay.classList.add("open");
  }

  // ── Leaflet map ────────────────────────────────────────────────
  const FALLBACK_CENTER = [47.0365, 21.9484];
  let leafletMap = null;
  let mapAlertMarkers = [];
  let mapInitialFit = false;

  const ALERT_PIN_COLORS = { high: "#f04858", medium: "#f0a030", low: "#38bdd2", warning: "#f0a030" };

  function makeAlertPinSvg(color) {
    return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 42" width="28" height="36">' +
      '<path d="M16 0C7.2 0 0 7.2 0 16c0 12 16 26 16 26s16-14 16-26C32 7.2 24.8 0 16 0z" fill="' + color + '"/>' +
      '<path d="M16 0C7.2 0 0 7.2 0 16c0 12 16 26 16 26s16-14 16-26C32 7.2 24.8 0 16 0z" fill="none" stroke="rgba(0,0,0,0.25)" stroke-width="1"/>' +
      '<circle cx="16" cy="15" r="7" fill="rgba(255,255,255,0.9)"/>' +
      '<text x="16" y="19" text-anchor="middle" font-size="10" font-weight="bold" font-family="sans-serif" fill="' + color + '">!</text>' +
      '</svg>';
  }

  function getAirportCenter() {
    if (!zonesConfig) return FALLBACK_CENTER;
    const lats = [], lngs = [];
    Object.values(zonesConfig).forEach(cam => {
      const corners = cam.gps_corners;
      if (!corners) return;
      Object.values(corners).forEach(c => {
        if (c.gps) { lats.push(c.gps[0]); lngs.push(c.gps[1]); }
      });
    });
    if (!lats.length) return FALLBACK_CENTER;
    return [
      (Math.min(...lats) + Math.max(...lats)) / 2,
      (Math.min(...lngs) + Math.max(...lngs)) / 2,
    ];
  }

  function getAirportBounds() {
    if (!zonesConfig) return null;
    const lats = [], lngs = [];
    Object.values(zonesConfig).forEach(cam => {
      const corners = cam.gps_corners;
      if (!corners) return;
      Object.values(corners).forEach(c => {
        if (c.gps) { lats.push(c.gps[0]); lngs.push(c.gps[1]); }
      });
    });
    if (!lats.length) return null;
    return L.latLngBounds(
      [Math.min(...lats), Math.min(...lngs)],
      [Math.max(...lats), Math.max(...lngs)]
    );
  }

  function initMap() {
    leafletMap = L.map("map", { zoomControl: false, scrollWheelZoom: true }).setView(FALLBACK_CENTER, 16);
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      attribution: '&copy; <a href="https://www.openstreetmap.org/">OSM</a>',
    }).addTo(leafletMap);
    setTimeout(() => leafletMap.invalidateSize(), 200);
  }

  initMap();

  function addAlertMarkers(alerts) {
    alerts.forEach(a => {
      const isWarning = a.alert_type === "warning";
      const color = isWarning ? ALERT_PIN_COLORS.warning : (ALERT_PIN_COLORS[a.severity] || ALERT_PIN_COLORS.medium);
      const icon = L.divIcon({
        html: makeAlertPinSvg(color),
        className: "alert-map-pin",
        iconSize: [28, 36],
        iconAnchor: [14, 36],
        popupAnchor: [0, -34],
      });

      const marker = L.marker([a.gps_lat, a.gps_lng], {
        icon: icon,
        zIndexOffset: isWarning ? 500 : 1000,
      }).addTo(leafletMap);

      const sevLabel = isWarning ? "WARNING" : (a.severity || "").toUpperCase();
      const zoneName = a.zone_name || a.zone_id || "";
      const camName = a.camera_name || a.camera_id || "";
      const titlePrefix = isWarning ? "Warning" : "Alert";

      marker.bindPopup(
        '<div style="min-width:150px;font-family:\'DM Sans\',sans-serif;">' +
          '<div style="font-weight:700;font-size:12px;margin-bottom:4px;">' + titlePrefix + ' #' + a.id + '</div>' +
          (isWarning ? '<div style="font-size:10px;margin-bottom:4px;padding:2px 6px;background:rgba(240,160,48,0.15);border-radius:3px;color:#f0a030;font-weight:700;">TRAJECTORY WARNING</div>' : '') +
          '<div style="font-size:11px;margin-bottom:2px;"><strong>Object:</strong> ' + esc(a.object_type) + '</div>' +
          '<div style="font-size:11px;margin-bottom:2px;"><strong>Zone:</strong> ' + esc(zoneName) + '</div>' +
          '<div style="font-size:11px;margin-bottom:2px;"><strong>Camera:</strong> ' + esc(camName) + '</div>' +
          '<div style="font-size:11px;margin-bottom:2px;"><strong>Severity:</strong> ' +
            '<span style="color:' + color + ';font-weight:600;">' + esc(sevLabel) + '</span></div>' +
          '<div style="font-size:11px;margin-bottom:2px;"><strong>Status:</strong> ' +
            '<span style="font-weight:600;">' + esc((a.status || "").toUpperCase()) + '</span></div>' +
          '<div style="font-size:10px;opacity:0.6;margin-top:4px;">' +
            a.gps_lat.toFixed(5) + ', ' + a.gps_lng.toFixed(5) + '</div>' +
        '</div>'
      );
      mapAlertMarkers.push(marker);
    });
  }

  function updateMap() {
    mapAlertMarkers.forEach(m => leafletMap.removeLayer(m));
    mapAlertMarkers = [];

    const activeOnly = zoneAlerts.filter(a => a.gps_lat != null && a.gps_lng != null);

    // Update header badge with alert count or airport coords
    if (activeOnly.length) {
      mapCoords.textContent = activeOnly.length + " alert" + (activeOnly.length !== 1 ? "s" : "") + " on map";
    } else {
      const c = getAirportCenter();
      mapCoords.textContent = c[0].toFixed(4) + ", " + c[1].toFixed(4);
    }

    if (activeOnly.length) {
      const bounds = activeOnly.map(a => [a.gps_lat, a.gps_lng]);
      if (bounds.length === 1) {
        leafletMap.setView(bounds[0], 17);
      } else {
        leafletMap.fitBounds(L.latLngBounds(bounds), {
          padding: [30, 30], maxZoom: 18,
        });
      }
      addAlertMarkers(activeOnly);
    } else if (!mapInitialFit) {
      const airportBounds = getAirportBounds();
      if (airportBounds) {
        leafletMap.fitBounds(airportBounds, { padding: [20, 20], maxZoom: 17 });
      } else {
        leafletMap.setView(getAirportCenter(), 16);
      }
      mapInitialFit = true;
    }
  }

  // Invalidate on resize
  new ResizeObserver(() => { if (leafletMap) leafletMap.invalidateSize(); }).observe(document.getElementById("map"));
