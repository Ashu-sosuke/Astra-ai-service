#!/usr/bin/env bash
# exit on error
set -o errexit

pip install --upgrade pip
pip install -r requirements.txt

# Faster-Whisper requires specific shared libraries sometimes.
# If you encounter issues with libcusparse, we might need to adjust the requirements.
