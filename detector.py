import time
import numpy as np
from shapely.geometry import Polygon


class YoloLaneDetector:
    """Pure analytical engine with internal FPS throttling for Raspberry Pi efficiency."""

    def __init__(
        self,
        model_path: str = "yolov8n.pt",
        avg_car_area_ratio: float = 0.20,
        hold_time_seconds: float = 10.0,
        fps_limit: float = 1.0,  # За замовчуванням 1 аналіз на секунду
    ):
        from ultralytics import YOLO

        self.avg_car_area_ratio = avg_car_area_ratio
        self.hold_time_seconds = hold_time_seconds
        self.fps_limit = fps_limit
        self.analysis_interval = 1.0 / fps_limit if fps_limit > 0 else 0

        self.model = YOLO(model_path)
        self.active_cars_history = {}

        # КЕШ результатів для кадрів між детекціями
        self.last_analysis_time = 0.0
        self.cached_stats = []
        self.cached_total_free = 0
        self.cached_total_capacity = 0

    def analyze_frame(self, frame: np.ndarray, spots: list[list[list[int]]]):
        if not spots:
            return [], 0, 0

        current_time = time.time()

        # Якщо з моменту останнього запуску YOLO минуло менше 1 сек (1/FPS) —
        # повертаємо збережені результати без навантаження CPU
        if (current_time - self.last_analysis_time) < self.analysis_interval:
            return (
                self.cached_stats,
                self.cached_total_free,
                self.cached_total_capacity,
            )

        # Оновлюємо таймер запуску YOLO
        self.last_analysis_time = current_time

        # 1. Інференс YOLO (виконується 1 раз на секунду)
        results_iter = self.model(frame, classes=[2, 5, 7], verbose=False)
        result = next(iter(results_iter))

        detected_cars = []
        for box in result.boxes.xyxy.cpu().numpy():
            x1, y1, x2, y2 = map(int, box[:4])
            car_poly = Polygon([(x1, y1), (x2, y1), (x2, y2), (x1, y2)])
            detected_cars.append((car_poly, (x1, y1, x2, y2)))

        sector_stats = []
        total_free_cars = 0
        total_capacity = 0

        # 2. Розрахунок геометрії та часу
        for idx, spot in enumerate(spots):
            lane_polygon = Polygon(spot)
            total_lane_area = lane_polygon.area

            if idx not in self.active_cars_history:
                self.active_cars_history[idx] = []

            new_history = []
            active_boxes = []

            for car_poly, bbox in detected_cars:
                if lane_polygon.intersects(car_poly):
                    new_history.append((car_poly, current_time))
                    active_boxes.append(bbox)

            for old_car_poly, last_seen in self.active_cars_history[idx]:
                if current_time - last_seen < self.hold_time_seconds:
                    already_added = any(
                        old_car_poly.intersects(new_car) for new_car, _ in new_history
                    )
                    if not already_added:
                        new_history.append((old_car_poly, last_seen))

            self.active_cars_history[idx] = new_history

            occupied_area = 0.0
            for car_poly, _ in self.active_cars_history[idx]:
                if lane_polygon.intersects(car_poly):
                    intersection = lane_polygon.intersection(car_poly)
                    occupied_area += intersection.area

            occupied_area = min(occupied_area, total_lane_area)
            free_area = total_lane_area - occupied_area

            avg_car_area = total_lane_area * self.avg_car_area_ratio
            sector_capacity = int(round(1.0 / self.avg_car_area_ratio))
            sector_free_cars = int(free_area // avg_car_area)

            total_capacity += sector_capacity
            total_free_cars += sector_free_cars

            sector_stats.append(
                {
                    "free_cars": sector_free_cars,
                    "capacity": sector_capacity,
                    "car_boxes": active_boxes,
                }
            )

        # Зберігаємо нові дані в КЕШ
        self.cached_stats = sector_stats
        self.cached_total_free = total_free_cars
        self.cached_total_capacity = total_capacity

        return sector_stats, total_free_cars, total_capacity