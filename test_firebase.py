import sys
import os
import traceback
import tempfile
import soundfile as sf
import numpy as np

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from utils.firebase_client import firebase_client

def create_dummy_audio(filename="firebase_test.wav"):
    sr = 16000
    t = np.linspace(0, 2, sr * 2) # 2 seconds
    y = 0.5 * np.sin(2 * np.pi * 440 * t)
    sf.write(filename, y, sr)
    return filename

def test_firebase_upload_and_download():
    print("\n--- Testing Firebase Storage ---")
    dummy_wav = create_dummy_audio()
    uploaded_path = "test_audio/firebase_test.wav"
    downloaded_path = None
    
    try:
        # Pre-requisite: We need to upload it first to test download
        if not firebase_client.bucket:
            print("[FAIL] Firebase bucket not initialized. Is the JSON key correct?")
            return
            
        print("1. Uploading dummy test file to Firebase Storage...")
        blob = firebase_client.bucket.blob(uploaded_path)
        blob.upload_from_filename(dummy_wav)
        print(f"   Successfully uploaded to gs://{firebase_client.bucket.name}/{uploaded_path}")
        
        print("2. Testing `download_audio` method...")
        # Test with gs:// path
        gs_path = f"gs://{firebase_client.bucket.name}/{uploaded_path}"
        downloaded_path = firebase_client.download_audio(gs_path)
        
        if downloaded_path and os.path.exists(downloaded_path):
            print(f"   [PASS] Successfully downloaded back to temporary file: {downloaded_path}")
        else:
            print("   [FAIL] Downloaded file not found.")
            
    except Exception as e:
        print(f"   [FAIL] Firebase Storage Test Failed.")
        traceback.print_exc()
    finally:
        # Cleanup
        if os.path.exists(dummy_wav):
            os.remove(dummy_wav)
        if downloaded_path and os.path.exists(downloaded_path):
            os.remove(downloaded_path)

def test_firestore():
    print("\n--- Testing Firestore ---")
    try:
        if not firebase_client.db:
            print("[FAIL] Firestore not initialized.")
            return

        test_incident_id = "TEST-INCIDENT-001"
        test_data = {
            "transcript": "This is a test transcript for Firebase integration.",
            "stressScore": 0.85,
            "threatType": "ASSAULT",
            "severityScore": 0.92,
            "finalSeverity": "CRITICAL",
            "confidence": 0.95,
            "recommendedAction": "EMERGENCY_DISPATCH"
        }
        
        print(f"1. Saving test incident '{test_incident_id}' to Firestore...")
        success = firebase_client.save_incident_analysis(test_incident_id, test_data)
        
        if success:
             print("   [PASS] Successfully saved test document to Firestore.")
             
             # Verify it's actually there
             doc = firebase_client.db.collection("incidents").document(test_incident_id).get()
             if doc.exists:
                 print(f"   [PASS] Verified document exists in Firestore. Content status: {doc.to_dict().get('status')}")
                 
                 # Clean up the test document
                 firebase_client.db.collection("incidents").document(test_incident_id).delete()
                 print("   [INFO] Cleaned up test document.")
             else:
                 print("   [FAIL] Document was not created in Firestore.")
        else:
            print("   [FAIL] `save_incident_analysis` returned False.")
            
    except Exception as e:
        print(f"   [FAIL] Firestore Test Failed.")
        traceback.print_exc()

if __name__ == "__main__":
    print("Starting Firebase Integration Tests...")
    test_firebase_upload_and_download()
    test_firestore()
    print("\nTests Completed.")
