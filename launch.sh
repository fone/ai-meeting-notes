#!/bin/bash
# Meeting Notes TUI Launcher
# Runs the meeting-notes TUI from the virtual environment

cd ~/meeting-notes
source venv/bin/activate
python3 run.py "$@"
