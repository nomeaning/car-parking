import os
import cv2

from detector import YoloLaneDetector
from ZoneManager import ZoneManager


RTSP_URL = "rtsp://admin:L23524A0@192.168.88.250:554/cam/realmonitor?channel=1&subtype=0"
CONFIG_PATH = "config/parking_spots.json"
WINDOW_NAME = "Smart Parking Monitor"


def main():
    os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp"

    # Instantiate decoupled components
    zone_manager = ZoneManager(config_path=CONFIG_PATH)
    detector = YoloLaneDetector(
        model_path="yolov8x.pt", avg_car_area_ratio=0.20, hold_time_seconds=10.0, fps_limit=1.0
    )

    cap = cv2.VideoCapture(RTSP_URL, cv2.CAP_FFMPEG)
    if not cap.isOpened():
        print("Error: Could not connect to stream.")
        return

    cv2.namedWindow(WINDOW_NAME)
    cv2.setMouseCallback(WINDOW_NAME, zone_manager.mouse_callback)

    while True:
        ret, frame = cap.read()
        if not ret:
            continue

        # 1. Для аналітичного двигуна передаємо ТІЛЬКИ повністю сформовані зони (4 точки)
        valid_spots = [spot for spot in zone_manager.spots if len(spot) == 4]

        # 2. Детекція запускається тільки для валідних зон
        sector_stats, total_free, total_capacity = detector.analyze_frame(
            frame, valid_spots
        )

        # 3. Для UI рендеру передаємо УСІ spots, щоб бачити процеси малювання (червоні точки/лінії)
        display_frame = zone_manager.render_ui(
            frame, sector_stats, total_free, total_capacity
        )

        cv2.imshow(WINDOW_NAME, display_frame)

        key = cv2.waitKey(1) & 0xFF
        if key == ord("c"):
            zone_manager.clear_all_spots()
            detector.active_cars_history.clear()
            detector.cached_stats = []
            detector.cached_total_free = 0
            detector.cached_total_capacity = 0
        elif key == ord("q"):
            break

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()