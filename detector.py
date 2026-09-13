import time
import cv2
import numpy as np
from shapely.geometry import Polygon


class YoloLaneDetector:
    def __init__(
        self,
        model_path: str = "yolov8s.pt",
        avg_car_area_ratio: float = 0.25,
        hold_time_seconds: float = 10.0,
        fps_limit: float = 1.0,
    ):
        from ultralytics import YOLO

        self.avg_car_area_ratio = avg_car_area_ratio
        self.hold_time_seconds = hold_time_seconds
        self.fps_limit = fps_limit
        self.analysis_interval = 1.0 / fps_limit if fps_limit > 0 else 0

        self.model = YOLO(model_path)
        self.active_cars_history = {}

        self.last_analysis_time = 0.0
        self.cached_stats = []
        self.cached_total_free = 0
        self.cached_total_capacity = 0

    def _get_birds_eye_polygon(self, spot_pts, target_width=800, target_height=200):
        src_pts = np.array(spot_pts, dtype=np.float32)
        dst_pts = np.array(
            [[0, 0], [target_width, 0], [target_width, target_height], [0, target_height]],
            dtype=np.float32,
        )
        matrix = cv2.getPerspectiveTransform(src_pts, dst_pts)
        return matrix, target_width, target_height

    def _transform_bbox_to_topdown(
            self, bbox: tuple[int, int, int, int], matrix: np.ndarray, target_w: int = 800, target_h: int = 200
        ) -> Polygon:
            """Створює проекцію автомобіля у Bird's-Eye View просторі."""
            x1, y1, x2, y2 = bbox
            
            # Точка контакту коліс із дорогою (нижня частина рамки)
            cx = (x1 + x2) / 2.0
            cy = float(y2)
            
            bottom_point = np.array([[[cx, cy]]], dtype=np.float32)
            transformed_pt = cv2.perspectiveTransform(bottom_point, matrix).squeeze()
            tx, ty = transformed_pt[0], transformed_pt[1]

            # Фізичний розмір авто в ізометричній сітці: 
            # 1 авто з 4 займає не менше 23% довжини (184px) та майже всю ширину (180px)
            car_length = target_w * 0.23
            car_width = target_h * 0.90

            half_l = car_length / 2.0
            half_w = car_width / 2.0

            return Polygon(
                [
                    (tx - half_l, ty - half_w),
                    (tx + half_l, ty - half_w),
                    (tx + half_l, ty + half_w),
                    (tx - half_l, ty + half_w),
                ]
            )

    def analyze_frame(self, frame: np.ndarray, spots: list[list[list[int]]]):
        if not spots:
            return [], 0, 0

        current_time = time.time()

        if (current_time - self.last_analysis_time) < self.analysis_interval:
            return (
                self.cached_stats,
                self.cached_total_free,
                self.cached_total_capacity,
            )

        self.last_analysis_time = current_time

        results_iter = self.model(frame, classes=[2, 5, 7], verbose=False)
        result = next(iter(results_iter))

        detected_cars = []
        for box in result.boxes.xyxy.numpy():
            x1, y1, x2, y2 = map(int, box[:4])
            car_poly_2d = Polygon([(x1, y1), (x2, y1), (x2, y2), (x1, y2)])
            detected_cars.append((car_poly_2d, (x1, y1, x2, y2)))

        sector_stats = []
        total_free_cars = 0
        total_capacity = 0

        for idx, spot in enumerate(spots):
            target_w, target_h = 800, 200
            matrix, _, _ = self._get_birds_eye_polygon(spot, target_w, target_h)
            topdown_lane_polygon = Polygon([(0, 0), (target_w, 0), (target_w, target_h), (0, target_h)])
            total_lane_area = topdown_lane_polygon.area

            if idx not in self.active_cars_history:
                self.active_cars_history[idx] = []

            new_history = []
            active_boxes = []

            for car_poly_2d, bbox in detected_cars:
                if Polygon(spot).intersects(car_poly_2d):
                    topdown_car_poly = self._transform_bbox_to_topdown(bbox, matrix, target_w, target_h)
                    new_history.append((topdown_car_poly, current_time))
                    active_boxes.append(bbox)

            for old_topdown_poly, last_seen in self.active_cars_history[idx]:
                if current_time - last_seen < self.hold_time_seconds:
                    already_added = any(old_topdown_poly.intersects(new_car) for new_car, _ in new_history)
                    if not already_added:
                        new_history.append((old_topdown_poly, last_seen))

            self.active_cars_history[idx] = new_history

            occupied_area = 0.0
            for topdown_car_poly, _ in self.active_cars_history[idx]:
                if topdown_lane_polygon.intersects(topdown_car_poly):
                    intersection = topdown_lane_polygon.intersection(topdown_car_poly)
                    occupied_area += intersection.area

            occupied_area = min(occupied_area, total_lane_area)
            free_area = total_lane_area - occupied_area

            # 3.5. Прямий підрахунок за кількістю виявлених об'єктів та площею
            sector_capacity = 4  # Загальна ємність цієї ділянки
            
            # Обчислюємо частку вільної площі
            free_ratio = free_area / total_lane_area

            # Динамічний поріг: якщо знайдено 4 авто АБО вільна площа менша за 25%
            num_detected_cars = len(self.active_cars_history[idx])
            
            if num_detected_cars >= sector_capacity or free_ratio < 0.25:
                sector_free_cars = 0
            else:
                sector_free_cars = max(0, sector_capacity - num_detected_cars)

            total_capacity += sector_capacity
            total_free_cars += sector_free_cars

            sector_stats.append(
                {
                    "free_cars": sector_free_cars,
                    "capacity": sector_capacity,
                    "car_boxes": active_boxes,
                }
            )

        self.cached_stats = sector_stats
        self.cached_total_free = total_free_cars
        self.cached_total_capacity = total_capacity

        return sector_stats, total_free_cars, total_capacity