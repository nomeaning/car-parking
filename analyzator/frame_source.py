from pathlib import Path

import cv2


class FrameSource:
    """Read frames from either the RTSP stream or numbered test images."""

    def __init__(self, stream_url: str, image_dir: str = "images"):
        self.stream_url = stream_url
        self.image_paths = sorted(
            Path(image_dir).glob("*.jpg"),
            key=lambda path: int(path.stem) if path.stem.isdigit() else path.stem,
        )
        self.image_index = 0
        self.mode = "video"
        self.capture = None

    @property
    def image_name(self) -> str:
        if not self.image_paths:
            return ""
        return self.image_paths[self.image_index].name

    def start(self, mode: str = "video") -> None:
        if mode == "image":
            self.switch_to_image()
        elif mode == "video":
            self.switch_to_video()
        else:
            raise ValueError(f"Unsupported input mode: {mode}")

    def read(self):
        if self.mode == "image":
            frame = cv2.imread(str(self.image_paths[self.image_index]))
            return frame is not None, frame

        if self.capture is None:
            self.capture = cv2.VideoCapture(self.stream_url, cv2.CAP_FFMPEG)
        return self.capture.read()

    def switch_to_image(self, index: int | None = None) -> None:
        if not self.image_paths:
            raise FileNotFoundError("No JPG test images found in the images directory")
        if index is not None:
            self.image_index = index % len(self.image_paths)
        self._release_capture()
        self.mode = "image"
        print(f"Using test image: {self.image_name}")

    def switch_to_video(self) -> None:
        self._release_capture()
        self.mode = "video"
        self.capture = cv2.VideoCapture(self.stream_url, cv2.CAP_FFMPEG)
        if not self.capture.isOpened():
            print("Error: Could not connect to stream.")

    def next_image(self, step: int) -> None:
        if self.image_paths:
            self.switch_to_image(self.image_index + step)

    def reconnect_video(self) -> bool:
        self._release_capture()
        self.capture = cv2.VideoCapture(self.stream_url, cv2.CAP_FFMPEG)
        return self.capture.isOpened()

    def close(self) -> None:
        self._release_capture()

    def _release_capture(self) -> None:
        if self.capture is not None:
            self.capture.release()
            self.capture = None
