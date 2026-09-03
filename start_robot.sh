#!/bin/bash
# Auto-start script for the Smart Campus Navigation Robot.

echo "Waiting for Wi-Fi..."
sleep 20

# Move into the folder this script lives in, wherever you cloned the project.
cd "$(dirname "$0")" || exit 1

# Activate the virtual environment if it exists.
if [ -d "venv" ]; then
    source venv/bin/activate
fi

echo "Starting robot AI..."
python run.py

echo ""
echo "Robot stopped or an error happened."
echo "Press Enter to close this window."
read
