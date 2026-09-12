import json
import os
import cv2
import numpy as np


class ParkingDetector:

    def __init__(self, config_path: str, pixel_threshold: int = 500):
        self.config_path = config_path
        self.pixel_threshold = pixel_threshold
        self.spots = []

        if os.path.exists(self.config_path):
            with open(self.config_path, "r") as f:
                self.spots = json.load(f)
        else:
            print(f"Попередження: Файл {self.config_path} не знайдено.")

    def preprocess_frame(self, frame):
        """Підготовка кадру з вирівнюванням освітленості (CLAHE)."""
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        # 1. Застосування CLAHE для вирівнювання яскравості (прибирає засвітлення та висвітлює тіні)
        clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
        equalized = clahe.apply(gray)

        # 2. Розмиття для усунення цифрового шуму камери
        blur = cv2.GaussianBlur(equalized, (5, 5), 1)

        # 3. Адаптивний поріг для виділення контурів
        thresh = cv2.adaptiveThreshold(
            blur,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY_INV,
            25,
            16,
        )

        # 4. Морфологічна фільтрація для видалення дрібного шуму
        kernel = np.ones((3, 3), np.uint8)
        thresh = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, kernel)

        return thresh

    def process_and_draw(self, frame):
        """Аналіз та накладання індикаторів."""
        thresh = self.preprocess_frame(frame)
        free_spots_count = 0

        for idx, spot in enumerate(self.spots):
            pts = np.array(spot, dtype=np.int32)

            # Створення маски конкретного паркомісця
            mask = np.zeros(thresh.shape, dtype=np.uint8)
            cv2.fillPoly(mask, [pts], (255,))

            # Виділення потрібного фрагмента та підрахунок білих пікселів
            spot_crop = cv2.bitwise_and(thresh, thresh, mask=mask)
            count = cv2.countNonZero(spot_crop)

            # Оскільки освітленість вирівняна, працює єдиний поріг
            if count < self.pixel_threshold:
                color = (0, 255, 0)  # Зелений — Вільне
                status = "Free"
                free_spots_count += 1
            else:
                color = (0, 0, 255)  # Червоний — Зайняте
                status = "Occupied"

            # Малювання полігону навколо місця
            cv2.polylines(frame, [pts], isClosed=True, color=color, thickness=2)

            # Відображення номера місця та кількості пікселів
            centroid = pts.mean(axis=0).astype(int)
            cv2.putText(
                frame,
                f"#{idx+1}: {count}",
                (centroid[0] - 20, centroid[1]),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.4,
                (255, 255, 255),
                1,
            )

        # Статистика на екрані
        total_spots = len(self.spots)
        cv2.putText(
            frame,
            f"FREE SPOTS: {free_spots_count} / {total_spots}",
            (30, 40),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.0,
            (0, 255, 0) if free_spots_count > 0 else (0, 0, 255),
            2,
        )

        return frame


if __name__ == "__main__":
    detector = ParkingDetector("config/parking_spots.json", pixel_threshold=900)

    # Тестовий запуск на фото або відеопотоці
    frame = cv2.imread("images/2.jpg")
    if frame is not None:
        processed_frame = detector.process_and_draw(frame)
        cv2.imshow("Parking Detection", processed_frame)
        cv2.waitKey(0)
        cv2.destroyAllWindows()