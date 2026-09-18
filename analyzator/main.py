import os
import cv2
import ssl
import time
import json
import base64
import queue
import logging
import threading
from datetime import datetime, timezone

import requests

from detectors.yolo_detector import YoloLaneDetector
from detectors.dinov2_detector import DinoV2LaneDetector
from ZoneManager import ZoneManager
from dotenv import load_dotenv

load_dotenv()

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

# --- Supabase reporting config ---
SUPABASE_URL = os.environ["SUPABASE_URL"].rstrip("/")
SUPABASE_ANON_KEY = os.environ["SUPABASE_ANON_KEY"]
DEVICE_EMAIL = os.environ["DEVICE_EMAIL"]
DEVICE_PASSWORD = os.environ["DEVICE_PASSWORD"]

FUNCTION_URL = f"{SUPABASE_URL}/functions/v1/report-parking-status"
AUTH_TOKEN_URL = f"{SUPABASE_URL}/auth/v1/token"
REPORT_INTERVAL_SECONDS = int(os.environ.get("REPORT_INTERVAL_SECONDS", 15))
TOKEN_REFRESH_BUFFER_SECONDS = 60
REPORT_MAX_RETRIES = 3
REPORT_TIMEOUT_SECONDS = 30


class DeviceSession:
    """Handles signing in as the device user and refreshing the session."""

    def __init__(self):
        self.access_token = None
        self.refresh_token = None
        self.expires_at = 0

    def _store(self, data: dict):
        self.access_token = data["access_token"]
        self.refresh_token = data["refresh_token"]
        self.expires_at = time.time() + data["expires_in"]
        self._log_role_claim()

    def _log_role_claim(self):
        try:
            payload_b64 = self.access_token.split(".")[1]
            padded = payload_b64 + "=" * (-len(payload_b64) % 4)
            claims = json.loads(base64.urlsafe_b64decode(padded))
            role = claims.get("role")
            log.info("Signed in. Token role claim = %r", role)
            if role not in ["device", "authenticated"]:
                log.warning(
                    "Expected role claim 'device' or 'authenticated' but got %r.",
                    role,
                )
        except Exception as e:
            log.warning("Could not decode token for sanity check: %s", e)

    def sign_in(self):
        resp = requests.post(
            AUTH_TOKEN_URL,
            params={"grant_type": "password"},
            headers={"apikey": SUPABASE_ANON_KEY, "Content-Type": "application/json"},
            json={"email": DEVICE_EMAIL, "password": DEVICE_PASSWORD},
            timeout=10,
        )
        resp.raise_for_status()
        self._store(resp.json())

    def refresh(self):
        resp = requests.post(
            AUTH_TOKEN_URL,
            params={"grant_type": "refresh_token"},
            headers={"apikey": SUPABASE_ANON_KEY, "Content-Type": "application/json"},
            json={"refresh_token": self.refresh_token},
            timeout=10,
        )
        resp.raise_for_status()
        self._store(resp.json())

    def get_valid_access_token(self) -> str:
        if self.access_token is None:
            self.sign_in()
        elif time.time() > self.expires_at - TOKEN_REFRESH_BUFFER_SECONDS:
            try:
                self.refresh()
            except requests.HTTPError:
                log.warning("Refresh failed, signing in fresh")
                self.sign_in()
        return self.access_token


def send_report(session: DeviceSession, captured_at: datetime, free_spaces: int, image_bytes: bytes):
    token = session.get_valid_access_token()

    for attempt in range(1, REPORT_MAX_RETRIES + 1):
        try:
            start = time.time()
            resp = requests.post(
                FUNCTION_URL,
                headers={
                    "apikey": SUPABASE_ANON_KEY,
                    "Authorization": f"Bearer {token}",
                },
                data={
                    "time": captured_at.isoformat(),
                    "free_spaces": str(free_spaces),
                },
                files={"image": ("snapshot.jpg", image_bytes, "image/jpeg")},
                timeout=REPORT_TIMEOUT_SECONDS,
            )
            elapsed = time.time() - start

            if resp.status_code == 200:
                log.info("Reported free_spaces=%d in %.1fs -> %s", free_spaces, elapsed, resp.json())
                return
            else:
                log.error(
                    "Report attempt %d/%d failed [%s] in %.1fs: %s",
                    attempt, REPORT_MAX_RETRIES, resp.status_code, elapsed, resp.text,
                )

        except requests.exceptions.RequestException as e:
            log.error("Report attempt %d/%d raised %s: %s", attempt, REPORT_MAX_RETRIES, type(e).__name__, e)

        if attempt < REPORT_MAX_RETRIES:
            backoff = 2 ** attempt
            log.info("Retrying in %ds...", backoff)
            time.sleep(backoff)

    log.error("Giving up on this report after %d attempts", REPORT_MAX_RETRIES)


def report_worker(session: DeviceSession, work_queue: "queue.Queue"):
    """Runs in a background thread so network retries never block the video loop."""
    while True:
        captured_at, free_spaces, image_bytes = work_queue.get()
        try:
            send_report(session, captured_at, free_spaces, image_bytes)
        except Exception:
            log.exception("Unexpected error in report worker")
        finally:
            work_queue.task_done()


def reset_detector_state(detector) -> None:
    """Clear cached analysis state on a detector (used on 'c' and on switch)."""
    detector.active_cars_history.clear()
    detector.cached_stats = []
    detector.cached_total_free = 0
    detector.cached_total_capacity = 0


def main():
    # Тимчасово вимикаємо строгу перевірку SSL-сертифікатів для torch.hub
    ssl._create_default_https_context = ssl._create_unverified_context

    os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp|stimeout;5000000"

    # --- Set up reporting: sign in once, then hand off to a worker thread ---
    session = DeviceSession()
    session.sign_in()
    report_queue: "queue.Queue" = queue.Queue()
    threading.Thread(target=report_worker, args=(session, report_queue), daemon=True).start()
    last_free_spaces = None
    last_report_check = 0.0

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

    cap = cv2.VideoCapture(RTSP_URL, cv2.CAP_FFMPEG)
    if not cap.isOpened():
        print("Error: Could not connect to stream.")
        return

    cv2.namedWindow(WINDOW_NAME)
    cv2.setMouseCallback(WINDOW_NAME, zone_manager.mouse_callback)

    print("Controls: 'y'=YOLO  'd'=DINOv2  'e'=calibrate DINOv2 empty baseline  'c'=clear zones  'q'=quit")

    consecutive_failures = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            consecutive_failures += 1
            if consecutive_failures >= 3:
                print("Stream disconnected or timed out. Attempting to reconnect...")
                cap.release()
                cv2.waitKey(2000)  # Wait 2 seconds before retrying
                cap = cv2.VideoCapture(RTSP_URL, cv2.CAP_FFMPEG)
                if not cap.isOpened():
                    print("Reconnection failed. Retrying in next iterations...")
                else:
                    print("Reconnected to stream successfully.")
                    consecutive_failures = 0
            else:
                cv2.waitKey(10)
            continue

        consecutive_failures = 0
        detector = detectors[current_mode]

        # 1. Only fully formed zones (4 points) go to the analytics engine
        valid_spots = [spot for spot in zone_manager.spots if len(spot) == 4]

        # 2. Run detection with the currently active engine
        sector_stats, total_free, total_capacity = detector.analyze_frame(
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

        cv2.imshow(WINDOW_NAME, display_frame)

        # 4. Report to Supabase only when the number of available spaces changes.
        #    Skip while no zones are calibrated yet (total_capacity == 0).
        if total_capacity > 0:
            should_send = (
                last_free_spaces is None 
                or total_free != last_free_spaces
            )
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
                    report_queue.put((datetime.now(timezone.utc), total_free, jpeg.tobytes()))
                else:
                    log.error("Failed to encode frame for reporting")
            last_free_spaces = total_free

        key = cv2.waitKey(1) & 0xFF
        if key == ord("c"):
            zone_manager.clear_all_spots()
            for d in detectors.values():
                reset_detector_state(d)
        elif key == ord("y") and current_mode != "yolo":
            current_mode = "yolo"
            reset_detector_state(detectors[current_mode])
            print("Switched to YOLO detector.")
        elif key == ord("d") and current_mode != "dinov2":
            current_mode = "dinov2"
            reset_detector_state(detectors[current_mode])
            print("Switched to DINOv2 detector.")
        elif key == ord("e"):
            if current_mode == "dinov2":
                valid_spots = [spot for spot in zone_manager.spots if len(spot) == 4]
                detectors["dinov2"].calibrate(frame, valid_spots)
            else:
                print("Calibration only applies to DINOv2 mode. Press 'd' first.")
        elif key == ord("q"):
            break

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
