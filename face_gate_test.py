from picamera2 import Picamera2
import cv2
import time

picam2 = Picamera2()
picam2.preview_configuration.main.size = (640, 480)
picam2.preview_configuration.main.format = "RGB888"
picam2.configure("preview")
picam2.start()

face_cascade = cv2.CascadeClassifier(
    "/usr/share/opencv4/haarcascades/haarcascade_frontalface_default.xml"
)

print("Looking for a face... Press Esc to stop.")

while True:
    frame = picam2.capture_array()
    gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)

    faces = face_cascade.detectMultiScale(
        gray,
        scaleFactor=1.2,
        minNeighbors=5,
        minSize=(60, 60)
    )

    if len(faces) > 0:
        print("Face detected")
    else:
        print("No face")

    cv2.imshow("Face Gate Test", frame)

    if cv2.waitKey(1) & 0xFF == 27:
        break

    time.sleep(0.5)

cv2.destroyAllWindows()
picam2.stop()
