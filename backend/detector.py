import cv2
import numpy as np
from collections import defaultdict

from ultralytics import YOLO


class Detector:
    """YOLO segmentation + ByteTrack tracking wrapper."""

    def __init__(self, model_path, confidence=0.25):
        self.model = YOLO(model_path)
        self.confidence = confidence
        self.track_history = defaultdict(list)
        self.max_trail = 30

    def process(self, frame):
        """Run YOLO tracking on a frame.

        Returns (annotated_frame, detections_list).
        Each detection: {track_id, class_name, confidence, bbox}.
        """
        results = self.model.track(
            frame, persist=True, verbose=False,
            conf=self.confidence, tracker="bytetrack.yaml",
        )
        annotated = results[0].plot()

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

                # Trajectory trail
                self.track_history[track_id].append((cx, cy))
                if len(self.track_history[track_id]) > self.max_trail:
                    self.track_history[track_id].pop(0)

                points = self.track_history[track_id]
                for i in range(1, len(points)):
                    thickness = int(np.sqrt(self.max_trail / float(i + 1)) * 2)
                    cv2.line(annotated, points[i - 1], points[i],
                             (0, 255, 255), thickness)

                if len(points) >= 5:
                    dx = points[-1][0] - points[-5][0]
                    dy = points[-1][1] - points[-5][1]
                    tip = (points[-1][0] + dx * 2, points[-1][1] + dy * 2)
                    cv2.arrowedLine(annotated, points[-1], tip,
                                    (0, 0, 255), 2, tipLength=0.4)

                class_name = self.model.names.get(cls_id, str(cls_id))
                detections.append({
                    "track_id": track_id,
                    "class_name": class_name,
                    "confidence": round(conf, 3),
                    "bbox": [round(x1, 1), round(y1, 1),
                             round(x2, 1), round(y2, 1)],
                })

        return annotated, detections
