import json
import os
import cv2
import numpy as np  # <--- Додайте імпорт NumPy

class ParkingSpotPicker:

    def __init__(self, rtsp_url: str, config_path: str):
        self.rtsp_url = rtsp_url
        self.config_path = config_path
        self.spots = []
        self.current_points = []

        if os.path.exists(self.config_path):
            with open(self.config_path, "r") as f:
                self.spots = json.load(f)

    def mouse_callback(self, event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN:
            self.current_points.append([x, y])
            if len(self.current_points) == 4:
                self.spots.append(self.current_points.copy())
                self.current_points = []
                print(f"Додано паркомісце #{len(self.spots)}")

    def run(self):
        # Налаштування TCP для стабільного RTSP
        os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp"

        cap = cv2.VideoCapture(self.rtsp_url, cv2.CAP_FFMPEG)
        ret, frame = cap.read()
        cap.release()

        

        if not ret:
            print("Не вдалося отримати кадр для розмітки.")
            return

        cv2.namedWindow("Select Parking Spots")
        cv2.setMouseCallback("Select Parking Spots", self.mouse_callback)

        while True:
            temp_frame = frame.copy()

            self.draw_parking_spots(temp_frame)
            self.draw_points(temp_frame)

            cv2.imshow("Select Parking Spots", temp_frame)
            key = cv2.waitKey(1) & 0xFF

            if key == ord("s"):
                os.makedirs(
                    os.path.dirname(self.config_path), exist_ok=True
                )
                with open(self.config_path, "w") as f:
                    json.dump(self.spots, f, indent=4)
                print(f"Збережено {len(self.spots)} місць у {self.config_path}")
            elif key == ord("c"):
                self.spots = []
                self.current_points = []
                print("Очищено всі місця.")
            elif key == ord("q"):
                break

        cv2.destroyAllWindows()

    def draw_parking_spots(self, temp_frame):
        # Малювання збережених місць
        for spot in self.spots:
                # ВАЖЛИВО: Перетворення списку в np.int32 масив запобігає падінню OpenCV
            pts = np.array(spot, dtype=np.int32).reshape((-1, 1, 2))
            cv2.polylines(
                    temp_frame, [pts], isClosed=True, color=(0, 255, 0), thickness=2
                )

    def draw_points(self, temp_frame):
        # Малювання поточних кліків (червоні точки)
        for pt in self.current_points:
            cv2.circle(
                    temp_frame,
                    tuple(pt),
                    radius=5,
                    color=(0, 0, 255),
                    thickness=-1,
                )