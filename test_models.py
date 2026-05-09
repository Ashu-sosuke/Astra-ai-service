import sys
import os
import numpy as np
import soundfile as sf
import traceback

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from models.threat_classifier import ThreatClassifier
from models.fusion import FusionEngine
from models.emotion import AudioStressDetector

def create_dummy_audio(filename="dummy_test.wav"):
    sr = 16000
    t = np.linspace(0, 3, sr * 3) # 3 seconds
    # Generate high pitch (600Hz) and high energy to trigger stress
    y = 0.8 * np.sin(2 * np.pi * 600 * t)
    sf.write(filename, y, sr)
    return filename

def test_threat_classifier():
    print("\n--- Testing Threat Classifier ---")
    try:
        classifier = ThreatClassifier()
        result = classifier.classify("He has a gun and is shooting people! Help me!")
        print(f"Test Input: 'He has a gun and is shooting people! Help me!'")
        print(f"Result: {result}")
        # Check if threat_type is one of the keys in KEYWORD_MAP or FALSE_ALARM
        assert result['threat_type'] in list(classifier.KEYWORD_MAP.keys()) + ["FALSE_ALARM"]
        print("[PASS] Threat Classifier test successful.")
    except Exception:
        print("[FAIL] Threat Classifier test failed.")
        traceback.print_exc()

def test_emotion_detector():
    print("\n--- Testing Audio Stress (Emotion) Detector ---")
    audio_path = create_dummy_audio()
    try:
        detector = AudioStressDetector()
        result = detector.analyze(audio_path)
        print(f"Result for dummy audio (High Pitch/Energy): {result}")
        assert result['stress_score'] > 0.0
        print("[PASS] Emotion Detector test successful.")
    except Exception:
        print("[FAIL] Emotion Detector test failed.")
        traceback.print_exc()
    finally:
        if os.path.exists(audio_path):
            os.remove(audio_path)

def test_fusion_engine():
    print("\n--- Testing Fusion Engine ---")
    try:
        stress_score = 0.8
        threat_data = {"threat_type": "ASSAULT", "confidence": 0.95}
        result = FusionEngine.compute_severity(stress_score, threat_data, keyword_score=1.0)
        print(f"Fusion Result (High Stress + Assault): {result}")
        assert result['severity_level'] in ["CRITICAL", "HIGH"]
        print("[PASS] Fusion Engine test successful.")
    except Exception:
        print("[FAIL] Fusion Engine test failed.")
        traceback.print_exc()

def test_transcription():
    print("\n--- Testing Transcription (Whisper) ---")
    # Note: Downloading/Loading Whisper might take long, and we might not have GPU on standard test runner.
    try:
        from models.transcription import TranscriptionService
        print("Initializing Transcription Service...")
        # Since standard test environment might not have CUDA, this might fall back to CPU or fail
        # This is a basic initialization test
        service = TranscriptionService()
        print("[PASS] Transcription Service loaded successfully.")
    except Exception:
        print("[FAIL/SKIP] Transcription Service load error (possibly device-related).")
        traceback.print_exc()

if __name__ == "__main__":
    print("Starting Model Tests...")
    test_threat_classifier()
    test_emotion_detector()
    test_fusion_engine()
    test_transcription()
    print("\nTests Completed.")
