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
    "person": "severe",
    "car": "severe",
    "truck": "severe",
    "bus": "severe",
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

    def __init__(self, alerts_db, mqtt_client=None, esp_sensor=None, grace_seconds=3.0):
        self._db = alerts_db
        self._mqtt = mqtt_client
        self._esp = esp_sensor
        self._grace = grace_seconds
        self._lock = threading.Lock()
        self._last_seen: dict[tuple, float] = {}

    def process_frame(self, camera_id, violations):
        """Called per frame with the list of zone violations.

        violations: list of dicts from ZoneChecker.check_detections()
        """
        now = time.monotonic()

        seen_keys = set()
        for v in violations:
            key = (camera_id, v["zone_id"], v["object_type"])
            seen_keys.add(key)

            with self._lock:
                self._last_seen[key] = now

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
            )

            if is_new:
                if self._mqtt:
                    self._publish("alert_new", alert)
                if severity in ("severe", "high") and self._esp:
                    self._esp.set_led(True)
                    self._esp.set_buzzer(True)

        self._close_stale(camera_id, seen_keys, now)

    def _close_stale(self, camera_id, seen_keys, now):
        """Close alerts whose object type has not been seen for > grace period."""
        open_alerts = self._db.find_open_alerts(camera_id)

        for alert in open_alerts:
            key = (alert["camera_id"], alert["zone_id"], alert["object_type"])
            if key in seen_keys:
                continue

            with self._lock:
                last = self._last_seen.get(key, 0)

            if (now - last) >= self._grace:
                self._db.close_alert(alert["id"])
                with self._lock:
                    self._last_seen.pop(key, None)
                if self._mqtt:
                    alert["status"] = "closed"
                    self._publish("alert_closed", alert)

                # Turn off LED+buzzer if no active severe/high alerts remain
                if self._esp and alert.get("severity") in ("severe", "high"):
                    remaining = [a for a in self._db.find_open_alerts(camera_id)
                                 if a["severity"] in ("severe", "high")]
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
