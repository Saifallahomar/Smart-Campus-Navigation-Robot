from openai import OpenAI
from dotenv import load_dotenv
import os
import subprocess
import sounddevice as sd
from scipy.io.wavfile import write
import numpy as np
import time
import pygame
import threading
import random
from picamera2 import Picamera2
import cv2

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

MIC_DEVICE = 1
SPEAKER_DEVICE = "plughw:2,0"

SAMPLE_RATE = 16000
CHUNK_SECONDS = 0.2
CHUNK_SAMPLES = int(SAMPLE_RATE * CHUNK_SECONDS)

VOICE_THRESHOLD = 500
SILENCE_TO_STOP = 0.9
MAX_RECORD_SECONDS = 10

pygame.display.init()
screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
pygame.display.set_caption("Robot Face")

BLACK = (0, 0, 0)
BLUE = (0, 180, 255)
WHITE = (255, 255, 255)
YELLOW = (255, 220, 80)
GREEN = (0, 255, 120)

next_blink_time = time.time() + random.uniform(2, 5)

# Camera setup
picam2 = Picamera2()
picam2.preview_configuration.main.size = (640, 480)
picam2.preview_configuration.main.format = "RGB888"
picam2.configure("preview")
picam2.start()

face_cascade = cv2.CascadeClassifier(
    "/usr/share/opencv4/haarcascades/haarcascade_frontalface_default.xml"
)

messages = [
    {
        "role": "system",
        "content": (
            "You are a professional and friendly university campus guide robot. "
            "Keep answers short, clear, and easy to understand. "
            "Help with campus directions, student questions, open days, and explaining the robot project. "
            "If you are not sure about something, say you are not fully sure instead of guessing. "
            "Do not give long answers unless the user asks. "
            "Robot project facts: "
            "Name: Smart Campus Guide Robot. "
            "Built by: Saif Allah Omar. "
            "Course: Mechatronics at UWE Bristol. "
            "Purpose: help visitors and students with directions, questions, and basic campus guidance. "
            "Features: voice interaction, AI answers, touchscreen, obstacle avoidance, camera face detection, and autonomous navigation development. "
            "Hardware: Raspberry Pi 5, EMEET microphone and speaker, Camera Module 3 Wide, Arduino or ESP32 for control. "
        )
    }
]

def draw_face(mode="idle", mouth_open=False, blink=False):
    screen.fill(BLACK)
    width, height = screen.get_size()

    eye_color = BLUE
    if mode == "thinking":
        eye_color = YELLOW
    elif mode == "face_detected":
        eye_color = GREEN

    if blink:
        pygame.draw.line(screen, eye_color, (width * 0.25, height * 0.32), (width * 0.25 + 120, height * 0.32), 10)
        pygame.draw.line(screen, eye_color, (width * 0.60, height * 0.32), (width * 0.60 + 120, height * 0.32), 10)
    else:
        pygame.draw.ellipse(screen, eye_color, (width * 0.25, height * 0.25, 120, 80))
        pygame.draw.ellipse(screen, eye_color, (width * 0.60, height * 0.25, 120, 80))

    if mouth_open:
        pygame.draw.ellipse(screen, WHITE, (width * 0.42, height * 0.60, 160, 80))
    else:
        pygame.draw.arc(screen, WHITE, (width * 0.38, height * 0.58, 220, 120), 3.3, 6.1, 8)

    pygame.display.flip()

def idle_face_with_blink(mode="idle"):
    global next_blink_time
    now = time.time()

    if now >= next_blink_time:
        draw_face(mode, False, True)
        time.sleep(0.15)
        next_blink_time = time.time() + random.uniform(2, 5)
    else:
        draw_face(mode, False, False)

def face_detected():
    frame = picam2.capture_array()
    gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)

    faces = face_cascade.detectMultiScale(
        gray,
        scaleFactor=1.2,
        minNeighbors=5,
        minSize=(60, 60)
    )

    return len(faces) > 0

def wait_for_face():
    print("\nWaiting for a person...")

    while True:
        for event in pygame.event.get():
            if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                raise KeyboardInterrupt

        if face_detected():
            print("Face detected.")
            draw_face("face_detected")
            time.sleep(0.5)
            return

        idle_face_with_blink("idle")
        time.sleep(0.2)

def record_until_silence(filename="voice.wav"):
    print("Listening...")

    frames = []
    started = False
    silence_time = 0
    total_time = 0

    with sd.InputStream(
        samplerate=SAMPLE_RATE,
        channels=1,
        dtype="int16",
        device=MIC_DEVICE
    ) as stream:

        while True:
            audio, overflowed = stream.read(CHUNK_SAMPLES)
            volume = np.sqrt(np.mean(audio.astype(np.float32) ** 2))

            if volume > VOICE_THRESHOLD:
                if not started:
                    started = True
                    draw_face("face_detected", True)

                frames.append(audio.copy())
                silence_time = 0
                total_time += CHUNK_SECONDS

            elif started:
                frames.append(audio.copy())
                silence_time += CHUNK_SECONDS
                total_time += CHUNK_SECONDS

                if silence_time >= SILENCE_TO_STOP:
                    print("Stopped listening.")
                    break

            if started and total_time >= MAX_RECORD_SECONDS:
                print("Maximum recording time reached.")
                break

    if not frames:
        return None

    recorded_audio = np.concatenate(frames, axis=0)
    write(filename, SAMPLE_RATE, recorded_audio)
    return filename

def speak_with_face(audio_file="answer.wav"):
    speaking = True

    def play_audio():
        nonlocal speaking
        subprocess.run(["aplay", "-D", SPEAKER_DEVICE, audio_file])
        speaking = False

    threading.Thread(target=play_audio).start()

    while speaking:
        draw_face("speaking", True)
        time.sleep(0.15)
        draw_face("speaking", False)
        time.sleep(0.15)

    draw_face("idle", False)

print("Robot voice AI is ready.")
print("Camera will detect a face before listening.")
print("Press Ctrl + C or Esc to stop.")
draw_face("idle")

try:
    while True:
        wait_for_face()

        audio_file_path = record_until_silence("voice.wav")

        if audio_file_path is None:
            continue

        draw_face("thinking")
        print("Understanding...")

        with open(audio_file_path, "rb") as audio_file:
            transcript = client.audio.transcriptions.create(
                model="gpt-4o-mini-transcribe",
                file=audio_file
            )

        question = transcript.text.strip()
        print("You said:", question)

        if question == "":
            continue

        if "stop" in question.lower() or "exit" in question.lower():
            print("Robot stopped.")
            break

        messages.append({"role": "user", "content": question})

        chat = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages
        )

        answer = chat.choices[0].message.content
        print("Robot:", answer)

        messages.append({"role": "assistant", "content": answer})

        with client.audio.speech.with_streaming_response.create(
            model="gpt-4o-mini-tts",
            voice="alloy",
            input=answer,
            response_format="wav"
        ) as response:
            response.stream_to_file("answer.wav")

        speak_with_face("answer.wav")

except KeyboardInterrupt:
    print("Robot stopped.")

picam2.stop()
pygame.quit()