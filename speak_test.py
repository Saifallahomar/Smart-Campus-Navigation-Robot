from openai import OpenAI
from dotenv import load_dotenv
import os
import subprocess

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

text = "Hello, I am your campus guide robot. How can I help you today?"

with client.audio.speech.with_streaming_response.create(
    model="gpt-4o-mini-tts",
    voice="alloy",
    input=text
) as response:
    response.stream_to_file("speech.wav")

subprocess.run(["aplay", "-D", "plughw:2,0", "speech.wav"])

