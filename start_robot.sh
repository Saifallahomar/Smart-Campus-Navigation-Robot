#!/bin/bash

echo "Waiting for Wi-Fi..."
sleep 20

cd /home/saifallah/robot_ai
source venv/bin/activate

echo "Starting robot AI..."
python voice_ai.py

echo ""
echo "Robot stopped or error happened."
echo "Press Enter to close this window."
read
