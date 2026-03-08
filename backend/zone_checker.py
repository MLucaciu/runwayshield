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


def _expand_polygon(polygon, factor=0.30):
    """Expand a polygon outward from its centroid by *factor* (0.30 = 30%).

    Each vertex moves away from the centroid by (1 + factor) of its original
    distance. Works for convex and mildly concave polygons.
    """
    n = len(polygon)
    if n == 0:
        return polygon
    cx = sum(p[0] for p in polygon) / n
    cy = sum(p[1] for p in polygon) / n
    scale = 1.0 + factor
    return [[cx + (px - cx) * scale, cy + (py - cy) * scale] for px, py in polygon]


class ZoneChecker:
    """Tests detections against configured polygon zones for a set of cameras."""

    PROXIMITY_EXPAND = 0.30  # 30% expansion for the warning buffer zone

    def __init__(self, config_path=None):
        if config_path is None:
            config_path = os.path.join(os.path.dirname(__file__), "zones.json")
        self._config = {}
        self._expanded_cache: dict[str, list] = {}
        self._load(config_path)

    def _load(self, path):
        if not os.path.isfile(path):
            print(f"[zones] Config not found at {path}, zone checking disabled")
            return
        with open(path) as f:
            self._config = json.load(f)
        total_zones = sum(len(c.get("zones", [])) for c in self._config.values())
        print(f"[zones] Loaded {total_zones} zones for {len(self._config)} cameras")
        self._build_expanded_cache()

    def _build_expanded_cache(self):
        """Pre-compute 30%-expanded polygons for every zone."""
        self._expanded_cache = {}
        for cam_id, cam_cfg in self._config.items():
            for zone in cam_cfg.get("zones", []):
                if zone["polygon"] == "all":
                    continue
                key = f"{cam_id}:{zone['id']}"
                self._expanded_cache[key] = _expand_polygon(
                    zone["polygon"], self.PROXIMITY_EXPAND
                )

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
                tags = zone.get("tags")
                if tags and det["class_name"] not in tags:
                    continue
                polygon = zone["polygon"]
                in_zone = polygon == "all" or _point_in_polygon(bx, by, polygon)
                if in_zone:
                    lat, lng = pixel_to_gps(bx, by, gps_corners)
                    violations.append({
                        "zone_id": zone["id"],
                        "zone_name": zone.get("name", zone["id"]),
                        "object_type": det["class_name"],
                        "track_id": det.get("track_id"),
                        "bbox": bbox,
                        "gps_lat": lat,
                        "gps_lng": lng,
                        "severity_override": zone.get("severity_override"),
                    })

        return violations

    def check_proximity_warnings(self, camera_id, detections, current_violations):
        """Warn when a person is inside the 30%-expanded zone but not yet inside the zone."""
        cam_config = self._config.get(camera_id)
        if not cam_config:
            return []

        zones = cam_config.get("zones", [])
        if not zones:
            return []

        gps_corners = cam_config.get("gps_corners")

        violation_keys = {
            (v["zone_id"], v["object_type"]) for v in current_violations
        }

        warnings = []
        for det in detections:
            bbox = det["bbox"]
            bx, by = bbox_bottom_center(bbox)

            for zone in zones:
                zone_id = zone["id"]
                tags = zone.get("tags")
                if tags and det["class_name"] not in tags:
                    continue
                if (zone_id, det["class_name"]) in violation_keys:
                    continue

                # "all" zones always produce violations, never proximity warnings
                if zone["polygon"] == "all":
                    continue

                if _point_in_polygon(bx, by, zone["polygon"]):
                    continue

                expanded_poly = self._expanded_cache.get(f"{camera_id}:{zone_id}")
                if not expanded_poly:
                    continue

                if not _point_in_polygon(bx, by, expanded_poly):
                    continue

                lat, lng = pixel_to_gps(bx, by, gps_corners)
                warnings.append({
                    "zone_id": zone_id,
                    "zone_name": zone.get("name", zone_id),
                    "object_type": det["class_name"],
                    "track_id": det.get("track_id"),
                    "bbox": bbox,
                    "gps_lat": lat,
                    "gps_lng": lng,
                    "severity_override": zone.get("severity_override"),
                })

        return warnings
