import time
import cv2
import numpy as np
import torch
import torch.nn.functional as F
import torchvision.transforms as T


class DinoV2LaneDetector:
    """
    Occupancy detector using DINOv2 embeddings instead of object detection.

    Unlike YOLO, DINOv2 has no notion of "car" — it only extracts visual
    features. Occupancy is inferred by comparing each zone's current crop
    against a stored *empty* reference embedding (cosine similarity). This
    means each zone must be calibrated once, while empty, via `calibrate()`.

    Exposes the same external interface as YoloLaneDetector so it's a
    drop-in replacement in main.py:
      - analyze_frame(frame, valid_spots) -> (sector_stats, total_free, total_capacity)
      - active_cars_history, cached_stats, cached_total_free, cached_total_capacity
    """

    def __init__(
        self,
        model_name: str = "dinov2_vits14",
        capacity_per_zone: int = 1,
        similarity_threshold: float = 0.80,
        hold_time_seconds: float = 10.0,
        fps_limit: float = 1.0,
        crop_size: int = 98,  # multiple of 14 (DINOv2 patch size)
    ):
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.model = torch.hub.load("facebookresearch/dinov2", model_name)
        self.model.eval().to(self.device)

        self.capacity_per_zone = capacity_per_zone
        self.similarity_threshold = similarity_threshold
        self.hold_time_seconds = hold_time_seconds
        self.fps_limit = fps_limit
        self.crop_size = crop_size

        self.transform = T.Compose(
            [
                T.ToTensor(),
                T.Resize((crop_size, crop_size)),
                T.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
            ]
        )

        # zone_idx -> baseline "empty" embedding
        self.reference_embeddings: dict[int, torch.Tensor] = {}

        # zone_idx -> last time state changed / debounce bookkeeping
        self.active_cars_history: dict[int, dict] = {}

        # Cache so we don't reprocess every frame if fps_limit is low
        self._last_infer_time = 0.0
        self.cached_stats: list[dict] = []
        self.cached_total_free = 0
        self.cached_total_capacity = 0

    # ------------------------------------------------------------------
    # Calibration
    # ------------------------------------------------------------------
    def calibrate(self, frame: np.ndarray, valid_spots: list) -> None:
        """Capture the current (assumed empty) appearance of every zone
        as the reference baseline. Call this once, right after drawing
        zones, while they are actually empty."""
        for idx, spot in enumerate(valid_spots):
            crop = self._extract_zone_crop(frame, spot)
            if crop is None:
                continue
            self.reference_embeddings[idx] = self._embed(crop)
        print(f"[DINOv2] Calibrated {len(self.reference_embeddings)} zone(s) as empty baseline.")

    # ------------------------------------------------------------------
    # Core analysis
    # ------------------------------------------------------------------
    def analyze_frame(self, frame: np.ndarray, valid_spots: list):
        now = time.time()
        if valid_spots and (now - self._last_infer_time) < (1.0 / self.fps_limit):
            return self.cached_stats, self.cached_total_free, self.cached_total_capacity
        self._last_infer_time = now

        sector_stats = []
        total_free = 0
        total_capacity = 0

        for idx, spot in enumerate(valid_spots):
            capacity = self.capacity_per_zone
            total_capacity += capacity

            crop = self._extract_zone_crop(frame, spot)
            occupied = False
            car_boxes = []

            if crop is not None and idx in self.reference_embeddings:
                emb = self._embed(crop)
                sim = F.cosine_similarity(emb, self.reference_embeddings[idx], dim=0).item()
                occupied = sim < self.similarity_threshold
                if occupied:
                    xs = [p[0] for p in spot]
                    ys = [p[1] for p in spot]
                    car_boxes = [[min(xs), min(ys), max(xs), max(ys)]]
            elif crop is not None and idx not in self.reference_embeddings:
                # No calibration yet — treat as free but flag via console once.
                pass

            occupied = self._debounce(idx, occupied, now)

            free_cars = 0 if occupied else capacity
            total_free += free_cars

            sector_stats.append(
                {
                    "free_cars": free_cars,
                    "capacity": capacity,
                    "car_boxes": car_boxes,
                }
            )

        self.cached_stats = sector_stats
        self.cached_total_free = total_free
        self.cached_total_capacity = total_capacity
        return sector_stats, total_free, total_capacity

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _debounce(self, idx: int, occupied_now: bool, now: float) -> bool:
        """Require a state to persist for hold_time_seconds before flipping,
        to avoid flicker between frames (mirrors YOLO's hold_time behavior)."""
        state = self.active_cars_history.setdefault(
            idx, {"stable": False, "pending": occupied_now, "since": now}
        )

        if occupied_now != state["pending"]:
            state["pending"] = occupied_now
            state["since"] = now

        if occupied_now == state["stable"]:
            return state["stable"]

        if now - state["since"] >= self.hold_time_seconds:
            state["stable"] = occupied_now

        return state["stable"]

    def _extract_zone_crop(self, frame: np.ndarray, spot: list) -> np.ndarray | None:
        pts = np.array(spot, dtype=np.int32)
        x, y, w, h = cv2.boundingRect(pts)
        if w <= 0 or h <= 0:
            return None
        x = max(0, x)
        y = max(0, y)
        crop = frame[y : y + h, x : x + w]
        if crop.size == 0:
            return None
        return cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)

    def _embed(self, rgb_crop: np.ndarray) -> torch.Tensor:
        tensor = self.transform(rgb_crop).unsqueeze(0).to(self.device)
        with torch.no_grad():
            feat = self.model(tensor)  # (1, D) CLS-token embedding
        return F.normalize(feat.squeeze(0), dim=0)
