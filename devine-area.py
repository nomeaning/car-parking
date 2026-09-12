from ParkingSpotPicker import ParkingSpotPicker


if __name__ == "__main__":
    RTSP_URL = "rtsp://admin:L23524A0@192.168.88.250:554/cam/realmonitor?channel=1&subtype=0"
    picker = ParkingSpotPicker(RTSP_URL, "config/parking_spots.json")
    picker.run()