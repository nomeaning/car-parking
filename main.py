import os
import cv2
from detector import ParkingDetector

# 1. Налаштування підключення до камери Imou
RTSP_URL = "rtsp://admin:L23524A0@192.168.88.250:554/cam/realmonitor?channel=1&subtype=0"
CONFIG_PATH = "config/parking_spots.json"


def main():
    # Налаштування TCP для запобігання таймаутів RTSP
    os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp"

    # 2. Ініціалізація детектора паркомісць
    detector = ParkingDetector(config_path=CONFIG_PATH, pixel_threshold=200)

    # 3. Відкриття відеопотоку з камери
    cap = cv2.VideoCapture(RTSP_URL, cv2.CAP_FFMPEG)

    if not cap.isOpened():
        print("Помилка: Не вдалося підключитися до камери Imou.")
        return

    print("Запуск моніторингу парковки. Натисніть 'q' для виходу.")

    # 4. Головний цикл обробки кадрів у реальному часі
    while True:
        ret, frame = cap.read()
        if not ret:
            print("Помилка отримання кадру. Повторна спроба...")
            continue

        # ВЛАСТИВО ВИКЛИК: main.py викликає метод обробки з detector.py
        processed_frame = detector.process_and_draw(frame)

        # Відображення результату
        cv2.imshow("Real-Time Parking Detector", processed_frame)

        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()