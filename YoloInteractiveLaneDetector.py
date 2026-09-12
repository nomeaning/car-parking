import json
import os
import time
import cv2
import numpy as np
from shapely.geometry import Polygon


class YoloInteractiveLaneDetector:

    def __init__(
        self,
        config_path: str,
        model_path: str = "yolov8n.pt",
        avg_car_area_ratio: float = 0.20,
        hold_time_seconds: float = 10.0,
    ):
        from ultralytics import YOLO

        self.config_path = config_path
        self.avg_car_area_ratio = avg_car_area_ratio
        self.hold_time_seconds = hold_time_seconds
        self.model = YOLO(model_path)

        self.spots = []
        self.current_points = []

        # Зберігаємо історію виявлених авто з часовою міткою: {zone_idx: [(car_poly, timestamp)]}
        self.active_cars_history = {}

        self.load_spots()

    def load_spots(self):
        if os.path.exists(self.config_path):
            with open(self.config_path, "r") as f:
                try:
                    self.spots = json.load(f)
                except json.JSONDecodeError:
                    self.spots = []

    def save_spots(self):
        os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
        with open(self.config_path, "w") as f:
            json.dump(self.spots, f, indent=4)

    def mouse_callback(self, event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN:
            self.current_points.append([x, y])
            if len(self.current_points) == 4:
                self.spots.append(self.current_points.copy())
                self.current_points = []
                self.save_spots()
        elif event == cv2.EVENT_RBUTTONDOWN:
            if self.spots:
                self.spots.pop()
                self.save_spots()

    def process_and_draw(self, frame):
        current_time = time.time()

        for pt in self.current_points:
            cv2.circle(frame, tuple(pt), 5, (0, 0, 255), -1)

        if not self.spots:
            cv2.putText(
                frame,
                "NO SECTORS DEFINED. Click 4 points to draw a zone | 'c' to clear",
                (30, 40),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (0, 255, 255),
                2,
            )
            return frame

        # 1. Детекція авто через YOLO
        results_iter = self.model(frame, classes=[2, 5, 7], verbose=False)
        result = next(iter(results_iter))

        detected_car_polys = []
        for box in result.boxes.xyxy.cpu().numpy():
            x1, y1, x2, y2 = map(int, box[:4])
            car_poly = Polygon([(x1, y1), (x2, y1), (x2, y2), (x1, y2)])
            detected_car_polys.append(car_poly)
            # Малюємо рамку навколо виявленого авто
            cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 0, 255), 2)

        total_free_cars = 0
        total_capacity = 0

        # 2. Обробка кожного виділеного сектора
        for idx, spot in enumerate(self.spots):
            lane_polygon = Polygon(spot)
            total_lane_area = lane_polygon.area

            if idx not in self.active_cars_history:
                self.active_cars_history[idx] = []

            # Оновлюємо історію: для нових детекцій зберігаємо точний час
            new_history = []

            # 1. Додаємо всі автомобілі, які YOLO бачить зараз
            for car_poly in detected_car_polys:
                if lane_polygon.intersects(car_poly):
                    new_history.append((car_poly, current_time))

            # 2. Додаємо старі автомобілі, з моменту зникання яких ще не минуло 10 секунд
            for old_car_poly, last_seen in self.active_cars_history[idx]:
                if current_time - last_seen < self.hold_time_seconds:
                    # Перевіряємо, чи цей старий полігон ще не перекривається новою детекцією
                    already_added = any(
                        old_car_poly.intersects(new_car) for new_car, _ in new_history
                    )
                    if not already_added:
                        new_history.append((old_car_poly, last_seen))

            self.active_cars_history[idx] = new_history

            # 3. Обчислюємо заповнену площу лише від реальних об'єктів усередині сектора
            occupied_area = 0.0
            for car_poly, _ in self.active_cars_history[idx]:
                if lane_polygon.intersects(car_poly):
                    intersection = lane_polygon.intersection(car_poly)
                    occupied_area += intersection.area

            occupied_area = min(occupied_area, total_lane_area)
            free_area = total_lane_area - occupied_area

            # Розрахунок вільних місць
            avg_car_area = total_lane_area * self.avg_car_area_ratio
            sector_capacity = int(round(1.0 / self.avg_car_area_ratio))
            sector_free_cars = int(free_area // avg_car_area)

            total_capacity += sector_capacity
            total_free_cars += sector_free_cars

            # Візуалізація смуги
            pts = np.array(spot, dtype=np.int32)
            cv2.polylines(frame, [pts], isClosed=True, color=(255, 255, 0), thickness=2)

            centroid = pts.mean(axis=0).astype(int)
            cv2.putText(
                frame,
                f"Zone #{idx+1}: {sector_free_cars}/{sector_capacity} Free",
                (centroid[0] - 50, centroid[1]),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (255, 255, 255),
                2,
            )

        # Інформаційне табло
        cv2.putText(
            frame,
            f"TOTAL FREE SPOTS: {total_free_cars} / {total_capacity}",
            (30, 40),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.9,
            (0, 255, 0) if total_free_cars > 0 else (0, 0, 255),
            2,
        )

        return frame