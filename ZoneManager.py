import json
import os
import cv2
import numpy as np


class ZoneManager:
    """Handles zone configuration, UI mouse interactions, and visual rendering."""

    def __init__(self, config_path: str):
        self.config_path = config_path
        self.spots = []
        self.current_points = []
        self.load_spots()

    def load_spots(self) -> None:
        if os.path.exists(self.config_path):
            with open(self.config_path, "r") as f:
                try:
                    self.spots = json.load(f)
                except json.JSONDecodeError:
                    self.spots = []

    def save_spots(self) -> None:
        os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
        with open(self.config_path, "w") as f:
            json.dump(self.spots, f, indent=4)

    def mouse_callback(self, event, x, y, flags, param) -> None:
        if self.spots and len(self.spots) == 1 and len(self.spots[0]) == 4:
            return  # Ignore clicks if already have 4 points

        """Handles OpenCV mouse events for drawing interactive zones."""
        if event == cv2.EVENT_LBUTTONDOWN:
            self.current_points.append([x, y])
            if len(self.current_points) == 4:
                self.spots.append(self.current_points.copy())
                self.current_points = []
                self.save_spots()

    def clear_all_spots(self) -> None:
        self.spots = []
        self.current_points = []
        self.save_spots()

    def render_ui(
        self,
        frame: np.ndarray,
        sector_stats: list[dict],
        total_free: int,
        total_capacity: int,
    ) -> np.ndarray:
        """Renders zone geometries, detected vehicle bounding boxes, and HUD text onto the frame."""
        # 1. Active drawing points
        for pt in self.current_points:
            cv2.circle(frame, tuple(pt), 5, (0, 0, 255), -1)

        # 2. No zones defined notification
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

        # 3. Render defined sectors and statistics
        for idx, stat in enumerate(sector_stats):
            spot = self.spots[idx]
            pts = np.array(spot, dtype=np.int32)

            # Highlight bounding box for active detections in this sector
            for car_box in stat["car_boxes"]:
                x1, y1, x2, y2 = car_box
                cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 0, 255), 2)

            # Zone boundary
            cv2.polylines(frame, [pts], isClosed=True, color=(255, 255, 0), thickness=2)

            # Zone label
            centroid = pts.mean(axis=0).astype(int)
            cv2.putText(
                frame,
                f"Zone #{idx+1}: {stat['free_cars']}/{stat['capacity']} Free",
                (centroid[0] - 50, centroid[1]),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (255, 255, 255),
                2,
            )

        # 4. HUD Banner
        cv2.putText(
            frame,
            f"TOTAL FREE SPOTS: {total_free} / {total_capacity}",
            (30, 40),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.9,
            (0, 255, 0) if total_free > 0 else (0, 0, 255),
            2,
        )

        return frame