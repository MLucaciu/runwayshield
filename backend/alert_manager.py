"""Alert lifecycle manager.

Processes zone violations from the detection pipeline, manages alert
creation/update/close with a grace period to prevent flicker, and
publishes MQTT messages for new and closed alerts.
"""

import json
import time
import threading
from datetime import datetime, timezone


SEVERITY_MAP = {
    "person": "high",
    "car": "high",
    "truck": "high",
    "bus": "high",
    "dog": "medium",
    "cat": "medium",
    "bird": "medium",
    "horse": "medium",
    "deer": "medium",
    "bear": "medium",
    "motorcycle": "medium",
    "bicycle": "medium",
}

DEFAULT_SEVERITY = "low"

MQTT_ALERTS_TOPIC = "runway-shield/alerts"


class AlertManager:
    """Manages alert lifecycle driven by per-frame zone violations.

    Thread-safe: called from each camera's detection thread.
    """

    def __init__(self, alerts_db, mqtt_client=None, esp_sensor=None,
                 grace_seconds=3.0, warning_grace_seconds=3.0, ws_emit=None):
        self._db = alerts_db
        self._mqtt = mqtt_client
        self._esp = esp_sensor
        self._ws_emit = ws_emit
        self._grace = grace_seconds
        self._warning_grace = warning_grace_seconds
        self._lock = threading.Lock()
        self._last_seen: dict[tuple, float] = {}
        self._warning_last_seen: dict[tuple, float] = {}

    def process_frame(self, camera_id, violations, warnings=None):
        """Called per frame with zone violations and trajectory warnings.

        violations: objects currently inside a zone (from ZoneChecker.check_detections)
        warnings:   objects whose trajectory points into a zone (from check_trajectory_warnings)
        """
        now = time.monotonic()
        warnings = warnings or []

        seen_keys = set()
        for v in violations:
            key = (camera_id, v["zone_id"], v["object_type"])
            seen_keys.add(key)

            with self._lock:
                self._last_seen[key] = now

        # Escalate warnings first so that upsert below creates fresh alerts
        # rather than silently updating an existing warning row.
        self._escalate_warnings(camera_id, seen_keys, now)

        for v in violations:
            severity = v.get("severity_override") or SEVERITY_MAP.get(
                v["object_type"], DEFAULT_SEVERITY
            )

            alert, is_new = self._db.upsert(
                camera_id=camera_id,
                zone_id=v["zone_id"],
                object_type=v["object_type"],
                severity=severity,
                gps_lat=v["gps_lat"],
                gps_lng=v["gps_lng"],
                zone_name=v.get("zone_name"),
                alert_type="alert",
            )

            if is_new:
                if self._mqtt:
                    self._publish("alert_new", alert)
                if severity == "high" and self._esp:
                    self._esp.set_led(True)
                    self._esp.set_buzzer(True)

        self._process_warnings(camera_id, warnings, seen_keys, now)
        self._close_stale(camera_id, seen_keys, now)
        self._close_stale_warnings(camera_id, now)

    def _process_warnings(self, camera_id, warnings, violation_keys, now):
        """Create or update warnings for trajectory-predicted zone entries."""
        warning_seen = set()
        for w in warnings:
            key = (camera_id, w["zone_id"], w["object_type"])
            if key in violation_keys:
                continue
            warning_seen.add(key)

            with self._lock:
                self._warning_last_seen[key] = now

            severity = w.get("severity_override") or SEVERITY_MAP.get(
                w["object_type"], DEFAULT_SEVERITY
            )

            alert, is_new = self._db.upsert(
                camera_id=camera_id,
                zone_id=w["zone_id"],
                object_type=w["object_type"],
                severity=severity,
                gps_lat=w["gps_lat"],
                gps_lng=w["gps_lng"],
                zone_name=w.get("zone_name"),
                alert_type="warning",
            )

            if is_new and self._mqtt:
                self._publish("warning_new", alert)

    def _escalate_warnings(self, camera_id, violation_keys, now):
        """Promote warnings to full alerts when the object enters the zone."""
        open_warnings = self._db.find_open_warnings(camera_id)
        for warning in open_warnings:
            key = (warning["camera_id"], warning["zone_id"], warning["object_type"])
            if key not in violation_keys:
                continue

            severity = SEVERITY_MAP.get(warning["object_type"], DEFAULT_SEVERITY)
            escalated = self._db.escalate_warning(warning["id"], severity)
            if escalated:
                with self._lock:
                    self._warning_last_seen.pop(key, None)
                    self._last_seen[key] = now
                if self._mqtt:
                    self._publish("warning_escalated", escalated)
                if severity == "high" and self._esp:
                    self._esp.set_led(True)
                    self._esp.set_buzzer(True)

    def _close_stale_warnings(self, camera_id, now):
        """Close warnings whose trajectory no longer points at the zone."""
        open_warnings = self._db.find_open_warnings(camera_id)
        for warning in open_warnings:
            key = (warning["camera_id"], warning["zone_id"], warning["object_type"])

            with self._lock:
                last = self._warning_last_seen.get(key, 0)

            if (now - last) >= self._warning_grace:
                self._db.close_alert(warning["id"])
                with self._lock:
                    self._warning_last_seen.pop(key, None)
                if self._mqtt:
                    warning["status"] = "closed"
                    self._publish("warning_closed", warning)

    def _close_stale(self, camera_id, seen_keys, now):
        """Close alerts whose object type has not been seen for > grace period."""
        open_alerts = self._db.find_open_alerts(camera_id)

        for alert in open_alerts:
            if alert.get("alert_type") == "warning":
                continue
            key = (alert["camera_id"], alert["zone_id"], alert["object_type"])
            if key in seen_keys:
                continue

            with self._lock:
                last = self._last_seen.get(key, 0)

            if (now - last) >= self._grace:
                was_acked = alert["status"] == "acknowledged"
                self._db.close_alert(alert["id"])
                with self._lock:
                    self._last_seen.pop(key, None)
                if self._mqtt:
                    alert["status"] = "resolved" if was_acked else "closed"
                    event = "alert_resolved" if was_acked else "alert_closed"
                    self._publish(event, alert)

                if self._esp and alert.get("severity") == "high":
                    remaining = [a for a in self._db.find_open_alerts(camera_id)
                                 if a["severity"] == "high"]
                    if not remaining:
                        self._esp.set_led(False)
                        self._esp.set_buzzer(False)

    def acknowledge(self, alert_id, username):
        """Acknowledge an alert. Returns the updated alert dict or None."""
        result = self._db.acknowledge(alert_id, username)
        if result and self._mqtt:
            self._publish("alert_acknowledged", result)
        return result

    def _publish(self, event_type, alert):
        if self._ws_emit:
            try:
                self._ws_emit(event_type, dict(alert))
            except Exception as e:
                print(f"[alert_manager] WS emit error: {e}")

        if not self._mqtt:
            return
        try:
            payload = {
                "event": event_type,
                "alert": alert,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            self._mqtt._client.publish(
                MQTT_ALERTS_TOPIC, json.dumps(payload), qos=1
            )
        except Exception as e:
            print(f"[alert_manager] MQTT publish error: {e}")
