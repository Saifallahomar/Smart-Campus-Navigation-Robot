import subprocess

print("Recording for 5 seconds... Speak now.")

subprocess.run([
    "arecord",
    "-D", "plughw:2,0",
    "-f", "cd",
    "-d", "5",
    "voice.wav"
])

print("Playing back your recording...")

subprocess.run([
    "aplay",
    "-D", "plughw:2,0",
    "voice.wav"
])
