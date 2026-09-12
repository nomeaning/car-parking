import os
import cv2

# Force FFmpeg to use TCP for RTSP transport (prevents UDP timeouts)
os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp"

RTSP_URL = "rtsp://admin:L23524A0@192.168.88.250:554/cam/realmonitor?channel=1&subtype=0"

def start_camera_stream():
    print("Connecting to camera via TCP...")
    cap = cv2.VideoCapture(RTSP_URL, cv2.CAP_FFMPEG)

    if not cap.isOpened():
        print("Error: Could not open connection to Imou camera.")
        return

    print("Stream connected! Press 'q' to quit.")
    
    while True:
        ret, frame = cap.read()
        if not ret:
            print("Failed to receive frame. Retrying...")
            break

        cv2.imshow("Imou Camera Stream", frame)
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    start_camera_stream()