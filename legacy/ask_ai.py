from openai import OpenAI
from dotenv import load_dotenv
import os
import subprocess

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

print("Robot is ready. Type 'exit' to stop.")

while True:
    question = input("\nAsk the robot: ")

    if question.lower() == "exit":
        print("Robot stopped.")
        break

    chat = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "system",
                "content": "You are a friendly campus guide robot. Keep answers short, clear, and helpful."
            },
            {
                "role": "user",
                "content": question
            }
        ]
    )

    answer = chat.choices[0].message.content
    print("Robot:", answer)

    with client.audio.speech.with_streaming_response.create(
        model="gpt-4o-mini-tts",
        voice="alloy",
        input=answer,
        response_format="wav"
    ) as response:
        response.stream_to_file("answer.wav")

    subprocess.run(["aplay", "-D", "plughw:2,0", "answer.wav"])
