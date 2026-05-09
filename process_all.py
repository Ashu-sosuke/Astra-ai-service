import os
import sys
import logging
import time
from dotenv import load_dotenv

# Add current directory to path for imports
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from main import _run_pipeline, transcription_service, audio_stress_detector, threat_classifier, groq_filter
import main
from utils.supabase_client import supabase_client
from models.transcription import TranscriptionService
from models.emotion import AudioStressDetector
from models.threat_classifier import ThreatClassifier
from models.groq_filter import GroqFilter

# Configure Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("batch_processor")

def initialize_models():
    """Initializes the global models in the main module."""
    logger.info("Initializing AI models (this may take a minute)...")
    main.transcription_service = TranscriptionService()
    main.audio_stress_detector = AudioStressDetector()
    main.threat_classifier = ThreatClassifier()
    main.groq_filter = GroqFilter()
    logger.info("All models initialized successfully.")

def process_all_pending():
    # 1. Initialize models
    initialize_models()
    
    # 2. Fetch incidents
    logger.info("Fetching incidents from Supabase...")
    incidents = supabase_client.get_all_incidents()
    
    if not incidents:
        logger.info("No incidents found in database.")
        return

    # 3. Filter for unanalyzed ones
    to_process = [i for i in incidents if i.get("status") not in ["ANALYZED", "FAILED"]]
    
    logger.info(f"Found {len(incidents)} total incidents. {len(to_process)} need processing.")
    
    if not to_process:
        logger.info("All incidents are already analyzed.")
        return

    # 4. Process each
    success_count = 0
    fail_count = 0
    
    for idx, incident in enumerate(to_process):
        incident_id = str(incident.get("id"))
        audio_url = incident.get("audio_url") or incident.get("audioUrl")
        
        logger.info(f"\n--- Processing {idx+1}/{len(to_process)}: {incident_id} ---")
        
        try:
            # We pass existing data to avoid redundant lookups if possible
            # though _run_pipeline will fetch chunks automatically
            main._run_pipeline(
                incident_id=incident_id,
                audio_url=audio_url,
                latitude=float(incident.get("latitude") or 0),
                longitude=float(incident.get("longitude") or 0),
                timestamp=incident.get("timestamp") or int(time.time())
            )
            success_count += 1
            logger.info(f"Successfully processed {incident_id}")
        except Exception as e:
            fail_count += 1
            logger.error(f"Failed to process {incident_id}: {e}")

    logger.info(f"\nBatch processing complete!")
    logger.info(f"Total attempted: {len(to_process)} | Success: {success_count} | Failed: {fail_count}")

if __name__ == "__main__":
    load_dotenv()
    process_all_pending()
