import cv2
import numpy as np
from collections import defaultdict

from ultralytics import YOLO


class SimpleIOUTracker:
    """Minimal IoU-based tracker to assign persistent IDs across frames."""

    def __init__(self, iou_threshold=0.3, max_lost=30):
        self.iou_threshold = iou_threshold
        self.max_lost = max_lost
        self.next_id = 1
        self.tracks = {}  # id -> {'bbox': [x1,y1,x2,y2], 'lost': int}

    @staticmethod
    def _iou(a, b):
        x1 = max(a[0], b[0])
        y1 = max(a[1], b[1])
        x2 = min(a[2], b[2])
        y2 = min(a[3], b[3])
        inter = max(0, x2 - x1) * max(0, y2 - y1)
        area_a = (a[2] - a[0]) * (a[3] - a[1])
        area_b = (b[2] - b[0]) * (b[3] - b[1])
        union = area_a + area_b - inter
        return inter / union if union > 0 else 0

    def update(self, bboxes):
        """Match bboxes to existing tracks. Returns list of (track_id, det_index)."""
        for tid in self.tracks:
            self.tracks[tid]['lost'] += 1

        used_tracks = set()
        used_dets = set()
        matched = []

        pairs = []
        for di, det in enumerate(bboxes):
            for tid, track in self.tracks.items():
                iou = self._iou(det, track['bbox'])
                if iou >= self.iou_threshold:
                    pairs.append((iou, tid, di))
        pairs.sort(reverse=True)

        for iou, tid, di in pairs:
            if tid in used_tracks or di in used_dets:
                continue
            self.tracks[tid]['bbox'] = bboxes[di]
            self.tracks[tid]['lost'] = 0
            matched.append((tid, di))
            used_tracks.add(tid)
            used_dets.add(di)

        for di, det in enumerate(bboxes):
            if di not in used_dets:
                tid = self.next_id
                self.next_id += 1
                self.tracks[tid] = {'bbox': det, 'lost': 0}
                matched.append((tid, di))

        self.tracks = {tid: t for tid, t in self.tracks.items()
                       if t['lost'] <= self.max_lost}
        return matched


class Detector:
    """YOLO segmentation + ByteTrack tracking wrapper."""

    # COCO class IDs to detect
    CLASSES = [0, 2, 4, 7, 14, 16, 63, 67]
    #          person car airplane truck bird dog laptop cell_phone

    def __init__(self, model_path, confidence=0.25, use_sahi=False,
                 sahi_slice_size=640, sahi_overlap=0.2):
        self.model = YOLO(model_path)
        self.confidence = confidence
        self.track_history = defaultdict(list)
        self.max_trail = 30
        self.use_sahi = use_sahi

        if use_sahi:
            from sahi import AutoDetectionModel
            self.sahi_model = AutoDetectionModel.from_pretrained(
                model_type='ultralytics',
                model_path=model_path,
                confidence_threshold=confidence,
            )
            self.sahi_slice_size = sahi_slice_size
            self.sahi_overlap = sahi_overlap
            self.iou_tracker = SimpleIOUTracker()

    def process(self, frame):
        """Run detection on a frame.

        Returns (annotated_frame, detections_list).
        Each detection: {track_id, class_name, confidence, bbox, predicted_tip}.
        """
        if self.use_sahi:
            return self._process_sahi(frame)
        return self._process_track(frame)

    def _process_track(self, frame):
        """Standard YOLO + ByteTrack tracking."""
        results = self.model.track(
            frame, persist=True, verbose=False,
            conf=self.confidence, tracker="bytetrack.yaml",
            classes=self.CLASSES,
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
                self._annotate_track(annotated, track_id, cls_id, conf,
                                     x1, y1, x2, y2, detections)

        return annotated, detections

    def _process_sahi(self, frame):
        """SAHI sliced prediction + IoU tracking."""
        from sahi.predict import get_sliced_prediction

        result = get_sliced_prediction(
            frame,
            self.sahi_model,
            slice_height=self.sahi_slice_size,
            slice_width=self.sahi_slice_size,
            overlap_height_ratio=self.sahi_overlap,
            overlap_width_ratio=self.sahi_overlap,
            verbose=0,
        )

        allowed_names = {self.model.names[c] for c in self.CLASSES
                         if c in self.model.names}
        name_to_id = {v: k for k, v in self.model.names.items()}

        sahi_boxes = []
        sahi_cls = []
        sahi_confs = []
        for pred in result.object_prediction_list:
            name = pred.category.name
            if name not in allowed_names:
                continue
            sahi_boxes.append(pred.bbox.to_xyxy())
            sahi_cls.append(name_to_id[name])
            sahi_confs.append(pred.score.value)

        matches = self.iou_tracker.update(sahi_boxes)
        annotated = frame.copy()
        detections = []

        for track_id, di in matches:
            x1, y1, x2, y2 = sahi_boxes[di]
            cls_id = sahi_cls[di]
            conf = sahi_confs[di]

            color = (0, 255, 0)
            label = f"{self.model.names.get(cls_id, str(cls_id))} {conf:.2f} ID:{track_id}"
            cv2.rectangle(annotated, (int(x1), int(y1)), (int(x2), int(y2)),
                          color, 2)
            cv2.putText(annotated, label, (int(x1), int(y1) - 8),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)

            self._annotate_track(annotated, track_id, cls_id, conf,
                                 x1, y1, x2, y2, detections)

        return annotated, detections

    def _annotate_track(self, annotated, track_id, cls_id, conf,
                        x1, y1, x2, y2, detections):
        """Draw trajectory trail and build detection dict."""
        cx = int((x1 + x2) / 2)
        cy = int((y1 + y2) / 2)

        self.track_history[track_id].append((cx, cy))
        if len(self.track_history[track_id]) > self.max_trail:
            self.track_history[track_id].pop(0)

        points = self.track_history[track_id]
        for i in range(1, len(points)):
            thickness = int(np.sqrt(self.max_trail / float(i + 1)) * 2)
            cv2.line(annotated, points[i - 1], points[i],
                     (0, 255, 255), thickness)

        predicted_tip = None
        if len(points) >= 5:
            dx = points[-1][0] - points[-5][0]
            dy = points[-1][1] - points[-5][1]
            tip = (points[-1][0] + dx * 2, points[-1][1] + dy * 2)
            cv2.arrowedLine(annotated, points[-1], tip,
                            (0, 0, 255), 2, tipLength=0.4)
            predicted_tip = [tip[0], tip[1]]

        class_name = self.model.names.get(cls_id, str(cls_id))
        detections.append({
            "track_id": track_id,
            "class_name": class_name,
            "confidence": round(conf, 3),
            "bbox": [round(x1, 1), round(y1, 1),
                     round(x2, 1), round(y2, 1)],
            "predicted_tip": predicted_tip,
        })
