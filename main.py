import os
import cv2
import ssl

from detectors.yolo_detector import YoloLaneDetector
from detectors.dinov2_detector import DinoV2LaneDetector
from ZoneManager import ZoneManager


RTSP_URL = "rtsp://admin:L23524A0@192.168.88.250:554/cam/realmonitor?channel=1&subtype=0"
CONFIG_PATH = "config/parking_spots.json"
WINDOW_NAME = "Smart Parking Monitor"


def reset_detector_state(detector) -> None:
    """Clear cached analysis state on a detector (used on 'c' and on switch)."""
    detector.active_cars_history.clear()
    detector.cached_stats = []
    detector.cached_total_free = 0
    detector.cached_total_capacity = 0


def main():
    # Тимчасово вимикаємо строгу перевірку SSL-сертифікатів для torch.hub
    ssl._create_default_https_context = ssl._create_unverified_context
    
    os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp"

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

    while True:
        ret, frame = cap.read()
        if not ret:
            continue

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
