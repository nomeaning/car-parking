import os
import cv2

from YoloInteractiveLaneDetector import YoloInteractiveLaneDetector


RTSP_URL = "rtsp://admin:L23524A0@192.168.88.250:554/cam/realmonitor?channel=1&subtype=0"
CONFIG_PATH = "config/parking_spots.json"
WINDOW_NAME = "Smart Parking Monitor"


def main():
    os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp"

    # Ініціалізація універсального детектора
    detector = YoloInteractiveLaneDetector(
        config_path=CONFIG_PATH, model_path="yolov8n.pt", avg_car_area_ratio=0.20
    )

    cap = cv2.VideoCapture(RTSP_URL, cv2.CAP_FFMPEG)

    if not cap.isOpened():
        print("Помилка: Не вдалося відкрити відеопотік.")
        return

    # Створюємо вікно та підключаємо до нього callback миші
    cv2.namedWindow(WINDOW_NAME)
    cv2.setMouseCallback(WINDOW_NAME, detector.mouse_callback)

    print("Запуск. Інструкція з управління:")
    print(" - Ліва кнопка миші (ЛКМ): Поставити точку (4 точки = новий сектор)")
    print(" - Права кнопка миші (ПКМ): Видалити останній сектор")
    print(" - Клавіша 'c': Очистити всі сектори")
    print(" - Клавіша 'q': Вихід")

    while True:
        ret, frame = cap.read()
        if not ret:
            continue

        # Обробка каду (розпізнавання запускається тільки за наявності секторів)
        processed_frame = detector.process_and_draw(frame)

        cv2.imshow(WINDOW_NAME, processed_frame)

        key = cv2.waitKey(1) & 0xFF
        if key == ord("c"):
            detector.spots = []
            detector.current_points = []
            detector.save_spots()
            print("Усі сектори видалено.")
        elif key == ord("q"):
            break

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()