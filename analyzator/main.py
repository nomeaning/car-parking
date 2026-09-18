import os
import cv2
import ssl
import time
import queue
import threading
import logging
from datetime import datetime, timezone

from report_sender import ReportSender
from report_worker import report_worker
from frame_source import FrameSource
from detectors.yolo_detector import YoloLaneDetector
from detectors.dinov2_detector import DinoV2LaneDetector
from ZoneManager import ZoneManager
from device_session import DeviceSession

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("main")

# NOTE: credentials are hardcoded in the URL below — fine for local testing,
# but move this to an env var before this code goes anywhere public/shared.
RTSP_URL = os.environ.get(
    "RTSP_URL",
    "rtsp://admin:L23524A0@192.168.88.250:554/cam/realmonitor?channel=1&subtype=0",
)
CONFIG_PATH = "config/parking_spots.json"
WINDOW_NAME = "Smart Parking Monitor"
INPUT_MODE = os.environ.get("INPUT_MODE", "video").lower()
IMAGE_DIR = os.environ.get("IMAGE_DIR", "images")


def main():
    # Тимчасово вимикаємо строгу перевірку SSL-сертифікатів для torch.hub
    ssl._create_default_https_context = ssl._create_unverified_context

    os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp|stimeout;5000000"

    # --- Set up reporting: sign in once, then hand off to a worker thread ---
    session = DeviceSession()
    session.sign_in()
    report_queue: "queue.Queue" = queue.Queue()
    report_sender = ReportSender()
    threading.Thread(
        target=report_worker,
        args=(session, report_sender, report_queue),
        daemon=True,
    ).start()
    last_free_spaces = None
    state_change_time = time.time()
    app_start_time = time.time()

    # Instantiate decoupled components
    zone_manager = ZoneManager(config_path=CONFIG_PATH)

    detectors = {
        "yolo": YoloLaneDetector(
            model_path="yolov8/yolov8x.pt",
            avg_car_area_ratio=0.20,
            hold_time_seconds=10.0,
            fps_limit=1.0,
        ),
        "dinov2": DinoV2LaneDetector(
            model_name="dinov2_vits14",
            capacity_per_zone=1,
            similarity_threshold=0.80,
            hold_time_seconds=10.0,
            fps_limit=1.0,
        ),
    }
    current_mode = "yolo"

    frame_source = FrameSource(RTSP_URL, IMAGE_DIR)
    try:
        frame_source.start(INPUT_MODE)
    except (FileNotFoundError, ValueError) as error:
        print(f"Input setup failed: {error}")
        return

    cv2.namedWindow(WINDOW_NAME)
    cv2.setMouseCallback(WINDOW_NAME, zone_manager.mouse_callback)

    print(
        "Controls: 'y'=YOLO  'd'=DINOv2  'e'=calibrate  "
        "'i'=test image  'v'=video  '['/']'=previous/next image  "
        "'c'=clear zones  'q'=quit"
    )

    consecutive_failures = 0
    while True:
        ret, frame = frame_source.read()
        if not ret:
            if frame_source.mode == "image":
                print(f"Could not read test image: {frame_source.image_name}")
                break
            consecutive_failures += 1
            if consecutive_failures >= 3:
                print("Stream disconnected or timed out. Attempting to reconnect...")
                cv2.waitKey(2000)  # Wait 2 seconds before retrying
                if not frame_source.reconnect_video():
                    print("Reconnection failed. Retrying in next iterations...")
                else:
                    print("Reconnected to stream successfully.")
                    consecutive_failures = 0
            else:
                cv2.waitKey(10)
            continue

        consecutive_failures = 0
        detector = detectors[current_mode]
        now = time.time()

        # 1. Only fully formed zones (4 points) go to the analytics engine
        valid_spots = [spot for spot in zone_manager.spots if len(spot) == 4]

        # 2. Run detection with the currently active engine
        sector_stats, total_free, total_capacity, event_timestamp = detector.analyze_frame(
            frame, valid_spots
        )

        # 3. Render all spots (including in-progress ones) plus engine label
        display_frame = zone_manager.render_ui(
            frame, sector_stats, total_free, total_capacity
        )
        cv2.putText(
            display_frame,
            f"ENGINE: {current_mode.upper()}",
            (30, display_frame.shape[0] - 20),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (0, 255, 255),
            2,
        )
        source_label = (
            f"IMAGE: {frame_source.image_name}"
            if frame_source.mode == "image"
            else "SOURCE: VIDEO"
        )
        cv2.putText(
            display_frame,
            source_label,
            (30, display_frame.shape[0] - 50),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (0, 255, 255),
            2,
        )

        cv2.imshow(WINDOW_NAME, display_frame)

        # 4. Report to Supabase only when the number of available spaces changes.
        #    Skip during initial warmup (12s) to allow detection stabilization.
        if total_capacity > 0:
            if now - app_start_time < 12.0:
                # Still in warmup, skip reporting but update UI
                if int(now) % 3 == 0: # Print every 3 seconds
                    print(f"[Detector] Warming up... stabilization in {int(12 - (now - app_start_time))}s")
                should_send = False
                state_change_time = now # Keep resetting until stable
            else:
                if total_free != last_free_spaces:
                    state_change_time = now
                    should_send = True
                else:
                    should_send = False

            if should_send:
                # Optimize image size: resize to max width of 1280px and compress to 75% quality
                h, w = display_frame.shape[:2]
                max_w = 1280
                if w > max_w:
                    scale = max_w / w
                    upload_frame = cv2.resize(display_frame, (max_w, int(h * scale)), interpolation=cv2.INTER_AREA)
                else:
                    upload_frame = display_frame

                ok, jpeg = cv2.imencode(".jpg", upload_frame, [int(cv2.IMWRITE_JPEG_QUALITY), 75])
                if ok:
                    # captured_at reflects exactly when the free space count changed
                    captured_dt = datetime.fromtimestamp(state_change_time, tz=timezone.utc)
                    report_queue.put((captured_dt, total_free, jpeg.tobytes()))
                else:
                    log.error("Failed to encode frame for reporting")
            last_free_spaces = total_free

        key = cv2.waitKey(1) & 0xFF
        if key == ord("c"):
            zone_manager.clear_all_spots()
            for d in detectors.values():
                d.reset_state()
        elif key == ord("y") and current_mode != "yolo":
            current_mode = "yolo"
            detectors[current_mode].reset_state()
            print("Switched to YOLO detector.")
        elif key == ord("d") and current_mode != "dinov2":
            current_mode = "dinov2"
            detectors[current_mode].reset_state()
            print("Switched to DINOv2 detector.")
        elif key == ord("e"):
            if current_mode == "dinov2":
                valid_spots = [spot for spot in zone_manager.spots if len(spot) == 4]
                detectors["dinov2"].calibrate(frame, valid_spots)
            else:
                print("Calibration only applies to DINOv2 mode. Press 'd' first.")
        elif key == ord("i"):
            try:
                frame_source.switch_to_image()
                for d in detectors.values():
                    d.reset_state()
            except FileNotFoundError as error:
                print(f"Input setup failed: {error}")
        elif key == ord("v"):
            frame_source.switch_to_video()
            for d in detectors.values():
                d.reset_state()
        elif key == ord("]") and frame_source.mode == "image":
            frame_source.next_image(1)
            for d in detectors.values():
                d.reset_state()
        elif key == ord("[") and frame_source.mode == "image":
            frame_source.next_image(-1)
            for d in detectors.values():
                d.reset_state()
        elif key == ord("q"):
            break

    frame_source.close()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
