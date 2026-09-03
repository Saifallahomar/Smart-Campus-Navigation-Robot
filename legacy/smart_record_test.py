import sounddevice as sd
from scipy.io.wavfile import write
import numpy as np

samplerate = 16000
duration = 8
filename = "smart_voice.wav"

print("Recording... speak now.")
audio = sd.rec(int(duration * samplerate), samplerate=samplerate, channels=1, dtype="int16", device=1)
sd.wait()

write(filename, samplerate, audio)
print("Saved:", filename)
