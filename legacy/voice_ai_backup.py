from openai import OpenAI
from dotenv import load_dotenv
import os
import subprocess
import sounddevice as sd
from scipy.io.wavfile import write
import numpy as np
import time

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

MIC_DEVICE = 1
SPEAKER_DEVICE = "plughw:2,0"

SAMPLE_RATE = 16000
CHUNK_SECONDS = 0.2
CHUNK_SAMPLES = int(SAMPLE_RATE * CHUNK_SECONDS)

VOICE_THRESHOLD = 500
SILENCE_TO_STOP = 1.2
MAX_RECORD_SECONDS = 12
WAIT_FOR_SPEECH_SECONDS = 30

print("Robot voice AI is ready.")
print("Speak to the robot. Press Ctrl + C to stop.")

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
            "Features: voice interaction, AI answers, touchscreen, obstacle avoidance, and autonomous navigation development. "
            "Hardware: Raspberry Pi 5, EMEET microphone and speaker, camera module, Arduino or ESP32 for control. "
        )
    }
]

def record_until_silence(filename="voice.wav"):
    print("\nWaiting for speech...")

    frames = []
    started = False
    silence_time = 0
    total_time = 0
    wait_time = 0

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
                    print("Listening...")
                    started = True

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

            else:
                wait_time += CHUNK_SECONDS
                if wait_time >= WAIT_FOR_SPEECH_SECONDS:
                    return None

            if started and total_time >= MAX_RECORD_SECONDS:
                print("Maximum recording time reached.")
                break

    if not frames:
        return None

    recorded_audio = np.concatenate(frames, axis=0)
    write(filename, SAMPLE_RATE, recorded_audio)
    return filename

while True:
    audio_file_path = record_until_silence("voice.wav")

    if audio_file_path is None:
        continue

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

    subprocess.run(["aplay", "-D", SPEAKER_DEVICE, "answer.wav"])

    time.sleep(0.5)