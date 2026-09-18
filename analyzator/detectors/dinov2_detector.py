import time
import cv2
import numpy as np
import torch
import torch.nn.functional as F
import torchvision.transforms as T


class DinoV2LaneDetector:
    """
    Occupancy detector using DINOv2 *dense patch features* as a lightweight
    semantic segmentation: every 14x14 patch of the frame is classified as
    "car" or "background" by comparing it to a per-zone empty baseline,
    instead of comparing one embedding for the whole zone crop.

    This is self-contained (no mmcv/mmsegmentation, no external ADE20K
    checkpoint) — it calibrates directly against your camera/zones, which
    is both simpler to install and more accurate for a fixed camera than a
    generic pretrained segmentation head would be.

    External interface matches YoloLaneDetector so it's a drop-in
    replacement in main.py:
      - analyze_frame(frame, valid_spots) -> (sector_stats, total_free, total_capacity)
      - active_cars_history, cached_stats, cached_total_free, cached_total_capacity
    """

    PATCH_SIZE = 14  # fixed by the dinov2 ViT architecture

    def __init__(
        self,
        model_name: str = "dinov2_vits14",
        capacity_per_zone: int = 1,
        input_size: int = 518,          # must be a multiple of PATCH_SIZE
        similarity_threshold: float = 0.75,  # per-patch cosine similarity cutoff
        occupied_area_ratio: float = 0.35,   # fraction of a zone's patches that must look "different" to call it occupied
        hold_time_seconds: float = 10.0,
        fps_limit: float = 1.0,
    ):
        assert input_size % self.PATCH_SIZE == 0, "input_size must be a multiple of 14"

        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.model = torch.hub.load("facebookresearch/dinov2", model_name)
        self.model.eval().to(self.device)

        self.capacity_per_zone = capacity_per_zone
        self.input_size = input_size
        self.grid_size = input_size // self.PATCH_SIZE  # e.g. 518 // 14 = 37
        self.similarity_threshold = similarity_threshold
        self.occupied_area_ratio = occupied_area_ratio
        self.hold_time_seconds = hold_time_seconds
        self.fps_limit = fps_limit

        self.transform = T.Compose(
            [
                T.ToTensor(),
                T.Resize((input_size, input_size)),
                T.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
            ]
        )

        # zone_idx -> (num_patches, C) tensor of "empty" baseline patch embeddings
        self.reference_patch_embeddings: dict[int, torch.Tensor] = {}
        # zone_idx -> list[(row, col)] patch grid cells that fall inside the zone
        self.zone_patch_cells: dict[int, list[tuple[int, int]]] = {}

        self.active_cars_history: dict[int, dict] = {}

        self._last_infer_time = 0.0
        self.cached_stats: list[dict] = []
        self.cached_total_free = 0
        self.cached_total_capacity = 0

    # ------------------------------------------------------------------
    # Dense feature extraction (one forward pass per frame, reused by all zones)
    # ------------------------------------------------------------------
    def _extract_patch_grid(self, frame: np.ndarray) -> torch.Tensor:
        """Returns patch embeddings reshaped to (grid_h, grid_w, C)."""
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        tensor = self.transform(rgb).unsqueeze(0).to(self.device)
        with torch.no_grad():
            out = self.model.forward_features(tensor)
            patch_tokens = out["x_norm_patchtokens"]  # (1, grid_h*grid_w, C)
        c = patch_tokens.shape[-1]
        grid = patch_tokens.reshape(self.grid_size, self.grid_size, c)
        return F.normalize(grid, dim=-1)  # normalize once so later dot products = cosine sim

    def _zone_to_patch_cells(self, spot: list, frame_shape: tuple) -> list:
        """Map a zone polygon (in original frame coords) to the set of
        (row, col) patch-grid cells whose centers fall inside it."""
        fh, fw = frame_shape[:2]
        sx = self.grid_size / fw
        sy = self.grid_size / fh

        poly = np.array([[p[0] * sx, p[1] * sy] for p in spot], dtype=np.float32)

        cells = []
        x_min = max(0, int(np.floor(poly[:, 0].min())))
        x_max = min(self.grid_size - 1, int(np.ceil(poly[:, 0].max())))
        y_min = max(0, int(np.floor(poly[:, 1].min())))
        y_max = min(self.grid_size - 1, int(np.ceil(poly[:, 1].max())))

        for row in range(y_min, y_max + 1):
            for col in range(x_min, x_max + 1):
                center = (col + 0.5, row + 0.5)
                if cv2.pointPolygonTest(poly, center, False) >= 0:
                    cells.append((row, col))
        return cells

    # ------------------------------------------------------------------
    # Calibration
    # ------------------------------------------------------------------
    def calibrate(self, frame: np.ndarray, valid_spots: list) -> None:
        """Capture each zone's current (assumed empty) patches as the
        per-patch baseline. Call once, right after drawing zones, while
        they are actually empty."""
        grid = self._extract_patch_grid(frame)  # (grid_h, grid_w, C)

        self.reference_patch_embeddings.clear()
        self.zone_patch_cells.clear()

        for idx, spot in enumerate(valid_spots):
            cells = self._zone_to_patch_cells(spot, frame.shape)
            if not cells:
                continue
            self.zone_patch_cells[idx] = cells
            embeds = torch.stack([grid[r, c] for r, c in cells])  # (num_patches, C)
            self.reference_patch_embeddings[idx] = embeds

        print(
            f"[DINOv2] Calibrated {len(self.reference_patch_embeddings)} zone(s) "
            f"as empty baseline ({sum(len(c) for c in self.zone_patch_cells.values())} patches total)."
        )

    # ------------------------------------------------------------------
    # Core analysis
    # ------------------------------------------------------------------
    def analyze_frame(self, frame: np.ndarray, valid_spots: list):
        now = time.time()
        if valid_spots and (now - self._last_infer_time) < (1.0 / self.fps_limit):
            return self.cached_stats, self.cached_total_free, self.cached_total_capacity, self._last_infer_time
        self._last_infer_time = now

        sector_stats = []
        total_free = 0
        total_capacity = 0

        grid = self._extract_patch_grid(frame) if valid_spots else None
        fh, fw = frame.shape[:2]

        for idx, spot in enumerate(valid_spots):
            capacity = self.capacity_per_zone
            total_capacity += capacity

            occupied = False
            car_boxes = []

            cells = self.zone_patch_cells.get(idx)
            baseline = self.reference_patch_embeddings.get(idx)

            if cells and baseline is not None:
                current = torch.stack([grid[r, c] for r, c in cells])  # (N, C)
                sims = (current * baseline).sum(dim=-1)  # cosine sim per patch (both normalized)
                car_mask = sims < self.similarity_threshold  # patches that no longer look "empty"

                car_ratio = car_mask.float().mean().item()
                occupied = car_ratio >= self.occupied_area_ratio

                if occupied:
                    car_boxes = [
                        self._patches_to_bbox(cells, car_mask.cpu().numpy(), fw, fh)
                    ]
                    car_boxes = [b for b in car_boxes if b is not None]

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
        return sector_stats, total_free, total_capacity, now

    def _patches_to_bbox(self, cells, mask, frame_w, frame_h):
        """Bounding box (in original frame pixels) of the patches flagged
        as 'car' within a zone — tighter than the full zone rectangle."""
        flagged = [cells[i] for i in range(len(cells)) if mask[i]]
        if not flagged:
            return None
        rows = [r for r, c in flagged]
        cols = [c for r, c in flagged]
        px = frame_w / self.grid_size
        py = frame_h / self.grid_size
        x1 = int(min(cols) * px)
        y1 = int(min(rows) * py)
        x2 = int((max(cols) + 1) * px)
        y2 = int((max(rows) + 1) * py)
        return [x1, y1, x2, y2]

    # ------------------------------------------------------------------
    # Debounce (avoid flicker between frames)
    # ------------------------------------------------------------------
    def _debounce(self, idx: int, occupied_now: bool, now: float) -> bool:
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

    def reset_state(self) -> None:
        self.active_cars_history.clear()
        self.reference_patch_embeddings.clear()
        self.zone_patch_cells.clear()
        self.cached_stats = []
        self.cached_total_free = 0
        self.cached_total_capacity = 0
        self._last_infer_time = 0.0
