# from ultralytics import YOLO
# import cv2
#
# model = YOLO("yolo26n.pt")  # nano = fastest, good for laptop/phone
# cap = cv2.VideoCapture("http://192.168.2.130:8080/video")   # or IP camera URL
#
# while True:
#     ret, frame = cap.read()
#     results = model(frame)
#     annotated = results[0].plot()
#     cv2.imshow("Runway Detection", annotated)
#     if cv2.waitKey(1) == ord("q"):
#         break
import cv2
import threading
import numpy as np
from collections import defaultdict

from ultralytics import YOLO
model = YOLO("../yolo11n-seg.pt")

# Store track history: track_id -> list of (cx, cy) center points
track_history = defaultdict(lambda: [])
MAX_TRAIL_LENGTH = 30

class MJPEGCamera:
    def __init__(self, url):
        self.cap = cv2.VideoCapture(url)
        self.frame = None
        self.lock = threading.Lock()
        self.thread = threading.Thread(target=self._reader, daemon=True)
        self.thread.start()

    def _reader(self):
        while True:
            ret, frame = self.cap.read()
            if ret:
                with self.lock:
                    self.frame = frame

    def read(self):
        with self.lock:
            return self.frame

cam = MJPEGCamera("http://10.1.0.78:8080/video?x.mjpg")
print("Connecting...")

while True:
    frame = cam.read()
    if frame is None:
        continue

    # Use .track() instead of .predict() — enables ByteTrack by default
    results = model.track(frame, persist=True, verbose=False, tracker="bytetrack.yaml")
    annotated = results[0].plot()

    # Draw trajectory trails for each tracked object
    boxes = results[0].boxes
    if boxes is not None and boxes.id is not None:
        track_ids = boxes.id.int().cpu().tolist()
        for box, track_id in zip(boxes.xyxy.cpu(), track_ids):
            cx = int((box[0] + box[2]) / 2)
            cy = int((box[1] + box[3]) / 2)
            track_history[track_id].append((cx, cy))
            if len(track_history[track_id]) > MAX_TRAIL_LENGTH:
                track_history[track_id].pop(0)

            # Draw the trail
            points = track_history[track_id]
            for i in range(1, len(points)):
                thickness = int(np.sqrt(MAX_TRAIL_LENGTH / float(i + 1)) * 2)
                cv2.line(annotated, points[i - 1], points[i], (0, 255, 255), thickness)

            # Draw direction arrow if we have enough history
            if len(points) >= 5:
                dx = points[-1][0] - points[-5][0]
                dy = points[-1][1] - points[-5][1]
                tip = (points[-1][0] + dx * 2, points[-1][1] + dy * 2)
                cv2.arrowedLine(annotated, points[-1], tip, (0, 0, 255), 2, tipLength=0.4)

    cv2.imshow("OMR Runway Detection", annotated)
    if cv2.waitKey(1) == ord("q"):
        break