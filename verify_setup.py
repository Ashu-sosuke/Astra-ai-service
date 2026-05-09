import sys
import os

print("1. Checking imports...")
try:
    from fastapi import FastAPI
    from faster_whisper import WhisperModel
    import librosa
    import torch
    from transformers import DistilBertTokenizer
    import pydantic
    print("   [PASS] All major imports successful.")
except ImportError as e:
    print(f"   [FAIL] Missing dependency: {e}")
    sys.exit(1)

print("\n2. Checking Project Structure...")
required_files = [
    "main.py",
    "config.py",
    "schemas.py",
    "Dockerfile",
    "requirements.txt",
    "utils/audio_loader.py",
    "models/transcription.py",
    "models/emotion.py",
    "models/threat_classifier.py",
    "models/fusion.py"
]
missing = []
for f in required_files:
    if not os.path.exists(f):
        missing.append(f)

if missing:
    print(f"   [FAIL] Missing files: {missing}")
else:
    print("   [PASS] All key files present.")

print("\n3. Verifying Config...")
try:
    from config import config
    print(f"   [PASS] Config loaded. Whisper Model: {config.WHISPER_MODEL_SIZE}")
except Exception as e:
    print(f"   [FAIL] Config load error: {e}")

print("\n4. Verification Complete (Static Checks).")
print("   To fully verify, build the Docker container and run the tests.")
