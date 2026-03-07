"""Pixel-to-GPS coordinate mapping via bilinear interpolation.

Uses four calibration corner points (pixel + GPS pairs) that define the
camera's field of view mapped onto a GPS plane.  The mapping uses inverse
bilinear interpolation to handle perspective-like distortion better than
a simple affine transform.

Calibration dict format (per camera in zones.json):
    "gps_corners": {
        "top_left":     {"px": [0, 0],       "gps": [lat, lng]},
        "top_right":    {"px": [W, 0],       "gps": [lat, lng]},
        "bottom_left":  {"px": [0, H],       "gps": [lat, lng]},
        "bottom_right": {"px": [W, H],       "gps": [lat, lng]}
    }
"""


def _normalize(px_x, px_y, corners):
    """Map pixel coords to [0,1] x [0,1] within the calibration quad."""
    tl = corners["top_left"]["px"]
    tr = corners["top_right"]["px"]
    bl = corners["bottom_left"]["px"]
    br = corners["bottom_right"]["px"]

    w_top = tr[0] - tl[0] if tr[0] != tl[0] else 1
    w_bot = br[0] - bl[0] if br[0] != bl[0] else 1
    h_left = bl[1] - tl[1] if bl[1] != tl[1] else 1
    h_right = br[1] - tr[1] if br[1] != tr[1] else 1

    u_top = (px_x - tl[0]) / w_top
    u_bot = (px_x - bl[0]) / w_bot
    v_left = (px_y - tl[1]) / h_left
    v_right = (px_y - tr[1]) / h_right

    v = (v_left + v_right) / 2.0
    u = u_top * (1 - v) + u_bot * v

    return max(0.0, min(1.0, u)), max(0.0, min(1.0, v))


def pixel_to_gps(px_x, px_y, gps_corners):
    """Convert pixel (x, y) to (lat, lng) using bilinear interpolation.

    Returns (lat, lng) as floats.  If gps_corners is None or incomplete,
    returns (None, None).
    """
    if not gps_corners:
        return None, None

    required = ("top_left", "top_right", "bottom_left", "bottom_right")
    for key in required:
        if key not in gps_corners:
            return None, None

    u, v = _normalize(px_x, px_y, gps_corners)

    tl_gps = gps_corners["top_left"]["gps"]
    tr_gps = gps_corners["top_right"]["gps"]
    bl_gps = gps_corners["bottom_left"]["gps"]
    br_gps = gps_corners["bottom_right"]["gps"]

    lat = (
        tl_gps[0] * (1 - u) * (1 - v)
        + tr_gps[0] * u * (1 - v)
        + bl_gps[0] * (1 - u) * v
        + br_gps[0] * u * v
    )
    lng = (
        tl_gps[1] * (1 - u) * (1 - v)
        + tr_gps[1] * u * (1 - v)
        + bl_gps[1] * (1 - u) * v
        + br_gps[1] * u * v
    )

    return round(lat, 7), round(lng, 7)


def bbox_bottom_center(bbox):
    """Return the (x, y) pixel coords of the bottom-center of a bbox [x1,y1,x2,y2]."""
    x1, y1, x2, y2 = bbox
    return (x1 + x2) / 2.0, y2
