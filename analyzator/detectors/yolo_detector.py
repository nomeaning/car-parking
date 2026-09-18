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

        import torch
        self.model = YOLO(model_path)
        
        # Hardware acceleration for Apple Silicon
        if torch.backends.mps.is_available():
            self.model.to('mps')
            print(f"[YOLO] Using MPS acceleration on Mac")
        elif torch.cuda.is_available():
            self.model.to('cuda')
            print(f"[YOLO] Using CUDA acceleration")
        self.active_cars_history = {}

        self.last_analysis_time = 0.0
        self.cached_stats = []
        self.cached_total_free = 0
        self.cached_total_capacity = 0
        self.cached_event_time = time.time()
        self._warped_debug_saved = False

    def _get_birds_eye_polygon(self, spot_pts, target_width=800, target_height=200):
        src_pts = np.array(spot_pts, dtype=np.float32)
        dst_pts = np.array([
            [0, target_height],
            [target_width, target_height],
            [target_width, 0],
            [0, 0],
        ], dtype=np.float32)
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
            return [], 0, 0, time.time()

        current_time = time.time()

        if (current_time - self.last_analysis_time) < self.analysis_interval:
            return (
                self.cached_stats,
                self.cached_total_free,
                self.cached_total_capacity,
                self.cached_event_time,
            )

        self.last_analysis_time = current_time

        if not self._warped_debug_saved and spots:
            first_spot = spots[0]
            matrix, target_w, target_h = self._get_birds_eye_polygon(
                first_spot, 800, 200
            )
            warped_frame = cv2.warpPerspective(frame, matrix, (target_w, target_h))
            cv2.imwrite("test/warped_view.png", warped_frame)
            self._warped_debug_saved = True
            print("Saved warped_view.png for the first analysis pass.")

        results_iter = self.model(frame, classes=[2, 5, 7], verbose=False)
        result = next(iter(results_iter))

        detected_cars = []
        for box in result.boxes.xyxy.cpu().numpy(): # type: ignore
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
                self.active_cars_history[idx] = [] # List of {'poly': P, 'first_seen': T, 'last_seen': T}

            current_frame_history = []
            active_boxes = []

            # 1. Match current detections with history
            for car_poly_2d, bbox in detected_cars:
                if Polygon(spot).intersects(car_poly_2d):
                    topdown_car_poly = self._transform_bbox_to_topdown(bbox, matrix, target_w, target_h)
                    
                    matched = False
                    for entry in self.active_cars_history[idx]:
                        if topdown_car_poly.intersects(entry['poly']):
                            # Update existing tracker
                            entry['poly'] = topdown_car_poly
                            entry['last_seen'] = current_time
                            current_frame_history.append(entry)
                            matched = True
                            break
                    
                    if not matched:
                        # Create new tracker for new potential car
                        new_entry = {
                            'poly': topdown_car_poly,
                            'first_seen': current_time,
                            'last_seen': current_time
                        }
                        current_frame_history.append(new_entry)
                    
                    active_boxes.append(bbox)

            # 2. Cleanup and Persistence
            # Keep trackers that were either seen this frame OR were seen very recently (flicker protection)
            updated_history = []
            
            # Add all currently seen
            updated_history.extend(current_frame_history)
            
            # Add recently missing (but only if they were confirmed parked previously)
            # to prevent passing cars from staying in history
            for old_entry in self.active_cars_history[idx]:
                if old_entry not in current_frame_history:
                    time_since_last_seen = current_time - old_entry['last_seen']
                    time_present = old_entry['last_seen'] - old_entry['first_seen']
                    
                    # If it was parked (present >= 10s), allow it to stay in history for 10s (occlusion/noise)
                    # If it was just passing (present < 10s), drop it immediately (1s buffer)
                    if time_present >= self.hold_time_seconds:
                        if time_since_last_seen < self.hold_time_seconds: 
                            updated_history.append(old_entry)
                    else:
                        if time_since_last_seen < 1.0:
                            updated_history.append(old_entry)

            self.active_cars_history[idx] = updated_history

            # 3. Calculate metrics based only on STABLE detections (present > 10s)
            confirmed_cars = [
                e for e in updated_history 
                if (current_time - e['first_seen']) >= self.hold_time_seconds
            ]

            occupied_area = 0.0
            for entry in confirmed_cars:
                if topdown_lane_polygon.intersects(entry['poly']):
                    intersection = topdown_lane_polygon.intersection(entry['poly'])
                    occupied_area += intersection.area

            occupied_area = min(occupied_area, total_lane_area)
            free_area = total_lane_area - occupied_area

            # 3.5. Counting
            sector_capacity = 4 
            free_ratio = free_area / total_lane_area
            num_detected_cars = len(confirmed_cars)
            
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

        # 4. Determine Event Basis (the earliest timestamp among confirmed cars)
        # If no cars confirmed, use current frame time as baseline
        event_timestamp = current_time
        all_confirmed_times = []
        for zone_history in self.active_cars_history.values():
            for entry in zone_history:
                if (current_time - entry['first_seen']) >= self.hold_time_seconds:
                    all_confirmed_times.append(entry['first_seen'])
        
        if all_confirmed_times:
            # Baseline is the most recent car to arrive (or earliest, depending on logic)
            # Usually we want the 'earliest' car to define the state if it's the first car
            # But the user wants 'Time since last free spot'. 
            # If total_free > 0, we want the first seen of the most recent free period start.
            # This is hard to calculate exactly here, so we pick the min (oldest car).
            event_timestamp = min(all_confirmed_times)

        self.cached_stats = sector_stats
        self.cached_total_free = total_free_cars
        self.cached_total_capacity = total_capacity
        self.cached_event_time = event_timestamp

        return sector_stats, total_free_cars, total_capacity, event_timestamp

    def reset_state(self) -> None:
        self.active_cars_history.clear()
        self.cached_stats = []
        self.cached_total_free = 0
        self.cached_total_capacity = 0
        self.cached_event_time = time.time()