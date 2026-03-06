# Airport Runway Hazard Detection — Brainstorm

## Current Architecture

- Fixed cam input (video upload / live stream)
- Object detection (YOLO) + 2D map correlation
- Motion detection + sensors
- Alert system (Severe / Medium / Low) → User validation → Actions
  - Severe → Deploy robot inspection
  - Medium → Enhance 2-4X image
  - Low → Night to day
- Alert history + weather sensors (humidity, temp, rain)
- Reports (daily / weekly)

---

## Additional Feature Ideas (ranked by hackathon feasibility)

### Quick wins (a few hours each)

1. **Zone-based threat scoring** — Draw polygons on the camera view for "runway", "taxiway", "grass". Same object detected on runway = Severe, on grass = Low. Just coordinate math on top of YOLO bounding boxes.

2. **Audio alert + TTS** — When a detection hits Severe, play an alarm sound and use `pyttsx3` or `gTTS` to announce "Bird detected on Runway 2". Cheap but impressive in a demo.

3. **Detection confidence filtering + cooldown** — Avoid alert spam by requiring N consecutive frames with confidence > threshold before triggering. Simple state machine, big UX improvement.

4. **Screenshot + auto-crop on detection** — When something is detected, save a cropped image of the object, timestamp it, store it. Instant evidence log / audit trail with zero extra hardware.

5. **Simple web dashboard** — Flask/FastAPI + a single HTML page showing the live annotated stream (MJPEG served from Python), a sidebar with recent alerts, and a map placeholder. Judges love a UI.

### Medium effort (half a day)

6. **Multi-camera stitching / split view** — If you have 2+ phones, show a grid view and correlate detections to a shared runway map. Even a simple split-screen with labeled zones is compelling.

7. **Object tracking + trajectory prediction** — Use YOLO + ByteTrack or BoTSORT (built into ultralytics: `model.track(frame)`). Show predicted path of a bird/animal with a vector arrow. This directly answers "is it heading toward the runway?"

8. **Heatmap overlay** — Accumulate detection positions over time, render a heatmap on the runway map showing hotspots. Tells airport ops "birds cluster near Taxiway C at dawn." Just a numpy accumulator + OpenCV colormap.

9. **LLM-powered alert summarization** — Feed detection metadata (object class, location, time, weather) to an LLM API to generate a human-readable incident summary: *"At 14:32, a flock of 5 birds was detected moving NE across Runway 09L during light rain. Risk: HIGH."*

10. **Simulated drone dispatch** — On Severe alert, show an animation on the map of a drone being dispatched to the coordinates. You don't need a real drone — just the logic + visualization to show the concept.

### High impact demo features

11. **Night/thermal simulation** — Take the live feed, apply OpenCV filters (grayscale + colormap = fake thermal view), run YOLO on it anyway. Demonstrates the concept of 24/7 operation even without a real thermal camera.

12. **Telegram/Slack bot integration** — On detection, push an alert with the cropped image to a Telegram bot. Takes ~30 min with `python-telegram-bot`. Great for the "real-time notification" story.

13. **Historical playback + timeline scrubber** — Store frames with detections in SQLite. Build a simple timeline UI where you can scrub through past incidents. Combines History + Reports.

---

## Recommended Stack for Maximum Demo Impact

```
Phone camera → YOLO detection + tracking → Zone-based severity scoring
    → Web dashboard (live stream + alert feed + runway map with dots)
    → Telegram alert with cropped image on Severe
    → LLM summary of each incident
    → Heatmap of historical detections
```

This hits detection, classification, alerting, reporting, and AI — all the boxes the judges care about.