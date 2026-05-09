from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.staticfiles import StaticFiles
from schemas import IncidentInput, IncidentOutput
from utils.audio_loader import AudioLoader, logger as audio_logger
from models.transcription import TranscriptionService, logger as trans_logger
from models.emotion import AudioStressDetector, logger as emotion_logger
from models.threat_classifier import ThreatClassifier, logger as threat_logger
from models.fusion import FusionEngine
from models.groq_filter import GroqFilter, logger as groq_logger
from utils.supabase_client import supabase_client
from utils.sms_client import sms_client
from supabase import acreate_client
import logging
import os
from config import config

# Handle Offline Mode before importing models that use HuggingFace
if config.OFFLINE_MODE:
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["HF_DATASETS_OFFLINE"] = "1"
    os.environ["HF_HUB_OFFLINE"] = "1"

import uvicorn
import time
import threading
import asyncio

# Configure Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("main")



# Global models (loaded on startup)
transcription_service = None
audio_stress_detector = None
threat_classifier = None
groq_filter = None

# Track incidents currently being processed to avoid duplicates
_processing_lock = threading.Lock()
_processing_set = set()


def _run_pipeline(incident_id: str, audio_url: str, latitude: float = None,
                  longitude: float = None, timestamp: int = None, document_path: str = None) -> dict:
    """
    Core processing pipeline. Used by both the API endpoint and the Firestore listener.
    Returns a dict with the full analysis results.
    """
    logger.info(f"▶ Pipeline started for incident: {incident_id}")
    start_time = time.time()
    temp_audio_path = None

    try:
        # 1. Gather all audio chunks for this incident
        logger.info(f"Step 1: Gathering all audio segments for incident {incident_id}...")
        all_urls = supabase_client.get_audio_chunks(incident_id)
        
        # If no chunks in audio_chunks table, fallback to the single audio_url provided
        if not all_urls and audio_url:
            all_urls = [audio_url]
        
        if not all_urls:
            raise ValueError("No audio segments found for this incident.")

        full_transcript = []
        max_stress_score = 0.0
        best_emotion_details = {}
        
        # Process each chunk
        for idx, url in enumerate(all_urls):
            logger.info(f"Processing segment {idx+1}/{len(all_urls)}: {url}")
            chunk_path = None
            try:
                chunk_path = supabase_client.download_audio(url)
                
                # 2. Transcription
                transcription_result = transcription_service.transcribe(chunk_path)
                full_transcript.append(transcription_result["text"])
                
                # 3. Emotion/Stress Analysis
                emotion_result = audio_stress_detector.analyze(chunk_path)
                current_stress = emotion_result.get("stress_score", 0.0)
                if current_stress >= max_stress_score:
                    max_stress_score = current_stress
                    best_emotion_details = emotion_result.get("details", {})
                
            finally:
                if chunk_path and os.path.exists(chunk_path):
                    os.remove(chunk_path)

        transcript_text = " ".join(full_transcript)
        stress_score = max_stress_score

        # 2.5 Groq Deep Analysis
        logger.info("Step 2.5: Groq AI deep analysis (multi-service routing + severity)...")
        groq_result = groq_filter.filter_transcription(transcript_text)
        groq_severity = groq_result.get("severity")  # 1-10 scale from Groq
        services_needed = groq_result.get("services_needed", [])

        # 4. Threat Classification
        logger.info("Step 4: Classifying threat...")
        threat_result = threat_classifier.classify(transcript_text)
        secondary_threats = threat_result.get("secondary_threats", [])
        logger.info(f"Threat result: type={threat_result.get('threat_type')}, conf={threat_result.get('confidence')}, secondary={secondary_threats}")

        # 5. Fusion with Groq severity integration
        logger.info("Step 5: Computing fusion score (v3.0 with Groq severity)...")
        location_risk = supabase_client.get_location_risk(latitude, longitude)

        # Compute keyword_score dynamically based on threat classification
        keyword_score = 0.0
        threat_type = threat_result.get('threat_type', 'FALSE_ALARM')
        if threat_type in ['ASSAULT', 'KIDNAP']:
            keyword_score = 1.0
        elif threat_type in ['FIRE', 'MEDICAL', 'ACCIDENT']:
            keyword_score = 0.8
        elif threat_type == 'PANIC':
            keyword_score = 0.6

        fusion_result = FusionEngine.compute_severity(
            stress_score=stress_score,
            threat_data=threat_result,
            keyword_score=keyword_score,
            location_risk=location_risk,
            groq_severity=groq_severity
        )
        logger.info(f"Fusion v3.0: score={fusion_result.get('final_score')}, severity={fusion_result.get('severity_level')}")

        # Build enriched threat_type string for dashboard filtering
        # Format: "FIRE (Conf: 98.0%)" — keeps backward compat
        threat_type_display = f"{threat_result['threat_type']}"
        if threat_result.get('confidence'):
            threat_type_display += f" (Conf: {threat_result['confidence']*100:.1f}%)"

        result = {
            "incidentId": incident_id,
            "transcript": transcript_text,
            "stressScore": stress_score,
            "threatType": threat_type_display,
            "severityScore": fusion_result["final_score"],
            "finalSeverity": fusion_result["severity_level"],
            "confidence": threat_result["confidence"],
            "recommendedAction": fusion_result["recommended_action"],
            "is_override_triggered": fusion_result.get("is_override_triggered", False),
            "model_version": "v3.0.0",
            "summary": groq_result.get("summary", ""),
            "is_emergency": groq_result.get("is_emergency", False),
            "intent": groq_result.get("intent", "general"),
            "services_needed": services_needed,
            "secondary_threats": secondary_threats,
            "situation_details": groq_result.get("situation_details", ""),
            "victim_count": groq_result.get("victim_count", 0),
            "details": {
                "processing_time_sec": round(time.time() - start_time, 2),
                "emotion_details": best_emotion_details,
                "fusion_breakdown": fusion_result.get("breakdown"),
                "groq_severity": groq_severity,
                "groq_recommended_action": groq_result.get("recommended_action"),
            },
            "latitude": latitude,
            "longitude": longitude,
            "timestamp": timestamp,
            "audio_url": audio_url,
        }

        # Detailed Logging
        logger.info(f"Final results for {incident_id}:")
        logger.info(f"  - Transcript: {transcript_text[:100]}...")
        logger.info(f"  - Stress: {stress_score}")
        logger.info(f"  - Threat: {threat_result['threat_type']} (conf={threat_result['confidence']})")
        logger.info(f"  - Fusion: {fusion_result['final_score']} ({fusion_result['severity_level']})")
        logger.info(f"  - Location: lat={latitude}, lon={longitude}")
        
        # 6. Save to Supabase Database
        logger.info("Step 6: Saving analysis results to Supabase...")
        supabase_client.update_incident(incident_id, result)

        # 7. Notify Trusted Contacts (Cloud Backup SMS)
        try:
            # Fetch user_id and manual is_emergency flag from incident
            db_res = supabase_client.client.table("incidents").select("user_id, is_emergency").eq("id", incident_id).execute()
            if db_res.data:
                user_id = db_res.data[0].get("user_id")
                db_is_emergency = db_res.data[0].get("is_emergency", False)
                
                contacts = supabase_client.get_user_contacts(user_id)
                
                if contacts:
                    logger.info(f"Found {len(contacts)} trusted contacts for user {user_id}")
                    severity = result.get("finalSeverity") or result.get("final_severity") or "UNKNOWN"
                    summary = result.get("summary", "No summary available.")
                    ai_is_emergency = result.get("is_emergency", False)
                    
                    # UPDATED: Always notify trusted contacts for any analyzed incident
                    should_notify = True
                    
                    logger.info(f"Notification Logic: severity={severity}, ai_emergency={ai_is_emergency}, manual_emergency={db_is_emergency} -> should_notify={should_notify}")
                    
                    # Alert if severity is high or explicitly an emergency
                    if should_notify:
                        sms_msg = f"🚨 AstraSOS Alert: {severity} Emergency detected.\nSummary: {summary}\nTracking: https://astrasos-278a5.web.app/?incident={incident_id}"
                        
                        for contact in contacts:
                            notify = contact.get("notify_on_sos")
                            if notify is not False:
                                phone = contact.get("phone_e164")
                                if phone:
                                    logger.info(f"Sending Cloud SMS to {contact.get('name')} ({phone})")
                                    sms_client.send_sms(phone, sms_msg)
                                else:
                                    logger.warning(f"Skipping contact {contact.get('name')}: No phone number found.")
                            else:
                                logger.info(f"Skipping contact {contact.get('name')}: notify_on_sos is False.")
                    else:
                        logger.info(f"Skipping SMS alerts: Incident severity ({severity}) is not HIGH/CRITICAL and is_emergency is False.")
                else:
                    logger.info(f"No trusted contacts found for user {user_id}. Skipping SMS alerts.")
            else:
                logger.warning(f"Could not find user_id for incident {incident_id}. Skipping SMS alerts.")
        except Exception as e:
            logger.error(f"Failed to send cloud notifications: {e}")

        logger.info(f"✔ Pipeline complete for {incident_id}. Severity: {fusion_result['severity_level']}")
        return result

    except Exception as e:
        logger.error(f"✘ Pipeline error for {incident_id}: {e}")
        # Mark the incident as failed
        try:
            supabase_client.update_incident(incident_id, {
                "status": "FAILED",
                "error_message": str(e)
            })
        except Exception:
            pass
        raise

    finally:
        if temp_audio_path and os.path.exists(temp_audio_path):
            try:
                os.remove(temp_audio_path)
            except Exception:
                pass


def _process_from_supabase(doc_id: str, doc_data: dict):
    """
    Called by the Supabase listener when a new/updated incident is detected.
    FIX: Removed old status-based gating; on_change now handles audio_url gating.
    """
    with _processing_lock:
        if doc_id in _processing_set:
            return
        _processing_set.add(doc_id)

    try:
        audio_url = doc_data.get("audio_url") or doc_data.get("audioUrl") or ""
        latitude = doc_data.get("latitude")
        longitude = doc_data.get("longitude")
        timestamp = doc_data.get("timestamp")

        # FIX: Clear log showing doc_id and first 60 chars of audio_url
        logger.info(f"🧵 Thread processing incident {doc_id} | Audio: {audio_url[:60]}...")

        _run_pipeline(doc_id, audio_url, latitude, longitude, timestamp)

    except Exception as e:
        logger.error(f"Supabase-triggered processing failed for {doc_id}: {e}")
    finally:
        with _processing_lock:
            _processing_set.discard(doc_id)


async def _start_supabase_listener():
    """
    Starts a real-time Supabase listener on the incidents table with retry logic.
    Falls back to polling mode if WebSocket connection repeatedly fails.
    """
    from config import config
    if not config.SUPABASE_URL or not config.SUPABASE_KEY:
        logger.warning("Supabase credentials missing — cannot start listener.")
        return

    retry_delay = 5
    consecutive_failures = 0
    FALLBACK_THRESHOLD = 3  # Switch to polling after 3 consecutive WebSocket failures

    while True:
        # If too many WebSocket failures, use REST polling instead
        if consecutive_failures >= FALLBACK_THRESHOLD:
            logger.warning(f"⚠ WebSocket failed {consecutive_failures} times. Switching to REST POLLING mode...")
            await _polling_listener()
            return  # polling_listener runs forever, so this won't return normally

        try:
            async_client = await acreate_client(config.SUPABASE_URL, config.SUPABASE_KEY)
            
            def on_change(payload):
                logger.info(f"🔔 Realtime change detected: {payload}")
                raw_type = payload.get("data", {}).get("type") or payload.get("eventType")
                event_type = str(raw_type).upper() if raw_type else ""
                
                if "INSERT" in event_type or "UPDATE" in event_type:
                    new_data = payload.get("data", {}).get("record") or payload.get("new", {})
                    doc_id = str(new_data.get("id"))
                    audio_url = new_data.get("audio_url") or new_data.get("audioUrl")
                    status = new_data.get("status")

                    if audio_url:
                        if status == "ANALYZED":
                            logger.info(f"✅ Skipping {doc_id}: Already analyzed.")
                            return
                        logger.info(f"🚀 Audio URL found! ID: {doc_id} | Status: {status} | URL: {audio_url[:60]}...")
                        thread = threading.Thread(
                            target=_process_from_supabase,
                            args=(doc_id, new_data),
                            daemon=True
                        )
                        thread.start()
                    else:
                        logger.info(f"⏳ Skipping {doc_id}: audio_url is missing (waiting for upload).")

            channel = async_client.channel("db-changes")
            channel.on_postgres_changes(event="*", schema="public", table="incidents", callback=on_change)
            await channel.subscribe()
            
            logger.info("👁 Subscribed to Supabase Realtime (WebSocket) successfully.")
            consecutive_failures = 0  # Reset on success
            
            # Keep alive
            while True:
                await asyncio.sleep(30)
                
        except asyncio.TimeoutError:
            consecutive_failures += 1
            logger.error(f"✘ Realtime Handshake Timed Out. (Attempt {consecutive_failures}/{FALLBACK_THRESHOLD})")
            await asyncio.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, 60)
        except Exception as e:
            consecutive_failures += 1
            logger.error(f"❌ Realtime Listener error ({consecutive_failures}/{FALLBACK_THRESHOLD}): {type(e).__name__}: {e}")
            await asyncio.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, 60)


async def _polling_listener():
    """
    REST API polling fallback. Polls Supabase every 10s for new READY_FOR_ANALYSIS incidents.
    Works even when WebSocket/Realtime is blocked by firewalls or DNS issues.
    """
    logger.info("🔄 POLLING MODE ACTIVE — Checking Supabase REST API every 10s for new incidents...")
    POLL_INTERVAL = 10  # seconds

    while True:
        try:
            # Fetch all incidents that are READY_FOR_ANALYSIS and have an audio_url
            response = supabase_client.client.table("incidents") \
                .select("id, audio_url, latitude, longitude, timestamp, status") \
                .eq("status", "READY_FOR_ANALYSIS") \
                .not_.is_("audio_url", "null") \
                .execute()

            if response.data:
                for incident in response.data:
                    doc_id = str(incident.get("id"))
                    audio_url = incident.get("audio_url")

                    # Skip if already being processed
                    with _processing_lock:
                        if doc_id in _processing_set:
                            continue

                    logger.info(f"📡 POLL: Found unanalyzed incident {doc_id} — queuing...")
                    thread = threading.Thread(
                        target=_process_from_supabase,
                        args=(doc_id, incident),
                        daemon=True
                    )
                    thread.start()
            else:
                logger.debug("📡 POLL: No new incidents found.")

        except Exception as e:
            logger.error(f"📡 POLL error: {e}")

        await asyncio.sleep(POLL_INTERVAL)



from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    global transcription_service, audio_stress_detector, threat_classifier, groq_filter
    logger.info("Initializing models...")
    try:
        transcription_service = TranscriptionService()
        audio_stress_detector = AudioStressDetector()
        threat_classifier = ThreatClassifier()
        groq_filter = GroqFilter()
        logger.info("All models initialized successfully.")
    except Exception as e:
        logger.critical(f"Model initialization failed: {e}")
        raise e

    # Start the Supabase real-time listener as a background task if enabled
    listener_task = None
    if config.ENABLE_REALTIME_LISTENER:
        logger.info("Starting Supabase Realtime Listener...")
        listener_task = asyncio.create_task(_start_supabase_listener())
    else:
        logger.info("Supabase Realtime Listener is DISABLED (ENABLE_REALTIME_LISTENER=False)")
    
    yield
    
    # Shutdown: Cancel the listener task to avoid "Event loop is closed" errors
    if listener_task:
        logger.info("Shutting down: cancelling Supabase listener...")
        listener_task.cancel()
        try:
            await listener_task
        except asyncio.CancelledError:
            logger.info("Supabase listener task cancelled successfully.")

app = FastAPI(title="SOS Intelligence AI Service", version="1.0.0", lifespan=lifespan)

# Mount static files for the admin panel
if not os.path.exists("static"):
    os.makedirs("static")
app.mount("/admin", StaticFiles(directory="static", html=True), name="static")


@app.get("/health")
def health_check():
    """Health check endpoint for Cloud Run."""
    if not (transcription_service and audio_stress_detector and threat_classifier):
        raise HTTPException(status_code=503, detail="Models not fully loaded")
    return {"status": "healthy", "version": "1.0.0"}

@app.get("/api/incidents")
def get_incidents():
    """Retrieve all incidents from Supabase."""
    incidents = supabase_client.get_all_incidents()
    return {"incidents": incidents}

@app.post("/api/process-all")
async def trigger_process_all(background_tasks: BackgroundTasks):
    """Triggers batch processing of all pending incidents."""
    from process_all import process_all_pending
    background_tasks.add_task(process_all_pending)
    return {"message": "Batch processing started in background"}

@app.post("/process-incident", response_model=IncidentOutput)
async def process_incident(incident: IncidentInput, background_tasks: BackgroundTasks):
    """
    Manual processing endpoint for SOS incidents.
    Also used as a fallback if the Firestore listener is not active.
    """
    logger.info(f"Received manual processing request for incident: {incident.incidentId}")

    try:
        result = _run_pipeline(
            incident_id=incident.incidentId,
            audio_url=incident.audioUrl,
            latitude=incident.latitude,
            longitude=incident.longitude,
            timestamp=incident.timestamp
        )

        return IncidentOutput(**result)

    except Exception as e:
        logger.error(f"Error processing incident {incident.incidentId}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
