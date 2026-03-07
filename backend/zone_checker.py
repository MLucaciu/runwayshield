"""Zone boundary checking for camera detections.

Loads polygon zones from zones.json and tests whether detected objects
(by their bounding box bottom-center) fall inside any zone.
"""

import json
import os

from geo import pixel_to_gps, bbox_bottom_center


def _point_in_polygon(px, py, polygon):
    """Ray-casting algorithm for point-in-polygon test.

    polygon: list of [x, y] pairs forming a closed polygon.
    Returns True if (px, py) is inside the polygon.
    """
    n = len(polygon)
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        if ((yi > py) != (yj > py)) and (px < (xj - xi) * (py - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


class ZoneChecker:
    """Tests detections against configured polygon zones for a set of cameras."""

    def __init__(self, config_path=None):
        if config_path is None:
            config_path = os.path.join(os.path.dirname(__file__), "zones.json")
        self._config = {}
        self._load(config_path)

    def _load(self, path):
        if not os.path.isfile(path):
            print(f"[zones] Config not found at {path}, zone checking disabled")
            return
        with open(path) as f:
            self._config = json.load(f)
        total_zones = sum(len(c.get("zones", [])) for c in self._config.values())
        print(f"[zones] Loaded {total_zones} zones for {len(self._config)} cameras")

    def get_zones(self, camera_id=None):
        """Return zone configs. If camera_id given, only that camera's zones."""
        if camera_id:
            cam = self._config.get(camera_id, {})
            return cam.get("zones", [])
        return self._config

    def get_gps_corners(self, camera_id):
        cam = self._config.get(camera_id, {})
        return cam.get("gps_corners")

    def check_detections(self, camera_id, detections):
        """Test each detection against all zones for this camera.

        Returns list of dicts:
            {zone_id, zone_name, object_type, bbox, gps_lat, gps_lng, severity_override}
        """
        cam_config = self._config.get(camera_id)
        if not cam_config:
            return []

        zones = cam_config.get("zones", [])
        if not zones:
            return []

        gps_corners = cam_config.get("gps_corners")
        violations = []

        for det in detections:
            bbox = det["bbox"]
            bx, by = bbox_bottom_center(bbox)

            for zone in zones:
                if _point_in_polygon(bx, by, zone["polygon"]):
                    lat, lng = pixel_to_gps(bx, by, gps_corners)
                    violations.append({
                        "zone_id": zone["id"],
                        "zone_name": zone.get("name", zone["id"]),
                        "object_type": det["class_name"],
                        "bbox": bbox,
                        "gps_lat": lat,
                        "gps_lng": lng,
                        "severity_override": zone.get("severity_override"),
                    })

        return violations
