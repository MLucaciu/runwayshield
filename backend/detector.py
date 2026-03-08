import os
import cv2
import numpy as np
from collections import defaultdict

from ultralytics import YOLO

# When False (default), only draw bounding boxes/trails for tracks that
# triggered an active alert or proximity warning.
SHOW_ALL_DETECTIONS = os.getenv("SHOW_ALL_DETECTIONS", "false").lower() in ("1", "true", "yes")


class Detector:
    """YOLO segmentation + ByteTrack tracking wrapper."""

    # COCO class IDs to detect
    CLASSES = [0, 2, 4, 7, 14, 16, 63, 67]
    #          person car airplane truck bird dog laptop cell_phone

    def __init__(self, model_path, confidence=0.25):
        self.model = YOLO(model_path)
        self.confidence = confidence
        self.track_history = defaultdict(list)
        self.max_trail = 30

    def process(self, frame, alerted_track_ids=None):
        """Run YOLO tracking on a frame.

        Returns (annotated_frame, detections_list).
        Each detection: {track_id, class_name, confidence, bbox}.

        When SHOW_ALL_DETECTIONS is False (default), only bounding boxes and
        trails for track IDs in alerted_track_ids are drawn.
        """
        results = self.model.track(
            frame, persist=True, verbose=False,
            conf=self.confidence, tracker="bytetrack.yaml",
            classes=self.CLASSES,
        )

        if SHOW_ALL_DETECTIONS or alerted_track_ids is None:
            annotated = results[0].plot()
        else:
            # Start from the original frame; only annotate alerted tracks
            annotated = results[0].orig_img.copy()

        detections = []
        boxes = results[0].boxes
        if boxes is not None and boxes.id is not None:
            track_ids = boxes.id.int().cpu().tolist()
            classes = boxes.cls.int().cpu().tolist()
            confs = boxes.conf.cpu().tolist()
            for box, track_id, cls_id, conf in zip(
                boxes.xyxy.cpu(), track_ids, classes, confs
            ):
                x1, y1, x2, y2 = box.tolist()
                cx = int((x1 + x2) / 2)
                cy = int((y1 + y2) / 2)

                # Trajectory trail (always update history, only draw when relevant)
                self.track_history[track_id].append((cx, cy))
                if len(self.track_history[track_id]) > self.max_trail:
                    self.track_history[track_id].pop(0)

                points = self.track_history[track_id]

                draw = SHOW_ALL_DETECTIONS or (alerted_track_ids is None) or (track_id in alerted_track_ids)

                if draw:
                    for i in range(1, len(points)):
                        thickness = int(np.sqrt(self.max_trail / float(i + 1)) * 2)
                        cv2.line(annotated, points[i - 1], points[i],
                                 (0, 255, 255), thickness)

                tip = None
                if len(points) >= 5:
                    dx = points[-1][0] - points[-5][0]
                    dy = points[-1][1] - points[-5][1]
                    tip = (points[-1][0] + dx * 2, points[-1][1] + dy * 2)
                    if draw:
                        cv2.arrowedLine(annotated, points[-1], tip,
                                        (0, 0, 255), 2, tipLength=0.4)

                if draw and not SHOW_ALL_DETECTIONS and alerted_track_ids is not None:
                    # Manually draw bbox and label for this alerted track
                    class_name = self.model.names.get(cls_id, str(cls_id))
                    cv2.rectangle(annotated, (int(x1), int(y1)), (int(x2), int(y2)),
                                  (0, 0, 255), 2)
                    label = f"{class_name} {conf:.2f}"
                    cv2.putText(annotated, label, (int(x1), int(y1) - 6),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)

                class_name = self.model.names.get(cls_id, str(cls_id))
                predicted_tip = None
                if tip is not None:
                    predicted_tip = [tip[0], tip[1]]

                detections.append({
                    "track_id": track_id,
                    "class_name": class_name,
                    "confidence": round(conf, 3),
                    "bbox": [round(x1, 1), round(y1, 1),
                             round(x2, 1), round(y2, 1)],
                    "predicted_tip": predicted_tip,
                })

        return annotated, detections
