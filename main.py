from fastapi import FastAPI, HTTPException, BackgroundTasks, Request
from fastapi.responses import JSONResponse
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
from geocoding import reverse_geocode
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
import asyncio
from contextlib import asynccontextmanager

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

# Track background tasks to prevent "Event loop is closed" errors on shutdown
_background_tasks = set()

# Track incidents currently being processed to avoid duplicates
_processing_set = set()

async def _run_pipeline_async(incident_id: str, audio_url: str, latitude: float = None,
                              longitude: float = None, timestamp: int = None) -> dict:
    """
    Core processing pipeline (Asynchronous).
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
                # Wrap blocking download in run_in_executor
                loop = asyncio.get_event_loop()
                chunk_path = await loop.run_in_executor(None, supabase_client.download_audio, url)
                
                # 2. Transcription (Async)
                transcription_result = await transcription_service.transcribe(chunk_path)
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
        
        # 6. Save to Supabase Database (run blocking update in thread pool)
        logger.info("Step 6: Saving analysis results to Supabase...")
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, supabase_client.update_incident, incident_id, result)

        # 7. Notify Trusted Contacts (Cloud Backup SMS)
        try:
            # Fetch user_id and manual is_emergency flag from incident
            db_res = supabase_client.client.table("incidents").select("user_id, is_emergency").eq("id", incident_id).execute()
            if db_res.data:
                user_id = db_res.data[0].get("user_id")
                db_is_emergency = db_res.data[0].get("is_emergency", False)
                
                # Fetch contacts (uses crypto decryption, run in executor)
                contacts = await loop.run_in_executor(None, supabase_client.get_user_contacts, user_id)
                
                if contacts:
                    logger.info(f"Found {len(contacts)} trusted contacts for user {user_id}")
                    severity = result.get("finalSeverity") or result.get("final_severity") or "UNKNOWN"
                    ai_is_emergency = result.get("is_emergency", False)
                    
                    should_notify = True
                    logger.info(f"Notification Logic: severity={severity}, ai_emergency={ai_is_emergency}, manual_emergency={db_is_emergency} -> should_notify={should_notify}")
                    
                    if should_notify:
                        # FIX 7: Call Nominatim reverse-geocoding
                        address = await reverse_geocode(latitude, longitude)
                        threat_clean = threat_result.get("threat_type", "UNKNOWN")
                        severity_clean = fusion_result.get("severity_level", "UNKNOWN")
                        
                        sms_msg = (
                            f"🚨 SOS ALERT | Threat: {threat_clean} | Severity: {severity_clean}\n"
                            f"📍 {address}\n"
                            f"🔗 Track live: https://astrasos-278a5.web.app/?incident={incident_id}"
                        )
                        
                        for contact in contacts:
                            notify = contact.get("notify_on_sos")
                            if notify is not False:
                                phone = contact.get("phone_e164")
                                if phone:
                                    logger.info(f"Sending Cloud SMS to {contact.get('name')} ({phone})")
                                    # send_sms is quick, but wrapping it in thread is safe
                                    await loop.run_in_executor(None, sms_client.send_sms, phone, sms_msg)
                                else:
                                    logger.warning(f"Skipping contact {contact.get('name')}: No phone number found.")
                            else:
                                logger.info(f"Skipping contact {contact.get('name')}: notify_on_sos is False.")
                    else:
                        logger.info(f"Skipping SMS alerts: Incident severity ({severity}) is not high/critical.")
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
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, supabase_client.update_incident, incident_id, {
                "status": "FAILED",
                "error_message": str(e)
            })
        except Exception:
            pass
        raise

def _run_pipeline(incident_id: str, audio_url: str, latitude: float = None,
                  longitude: float = None, timestamp: int = None) -> dict:
    """
    Synchronous wrapper for _run_pipeline_async (used by batch script process_all.py).
    """
    return asyncio.run(_run_pipeline_async(incident_id, audio_url, latitude, longitude, timestamp))

async def _process_from_supabase_async(doc_id: str, doc_data: dict):
    """
    Asynchronous runner for Supabase database changes.
    """
    if doc_id in _processing_set:
        return
    _processing_set.add(doc_id)

    try:
        audio_url = doc_data.get("audio_url") or doc_data.get("audioUrl") or ""
        latitude = doc_data.get("latitude")
        longitude = doc_data.get("longitude")
        timestamp = doc_data.get("timestamp")

        logger.info(f"🚀 Async task processing incident {doc_id} | Audio: {audio_url[:60]}...")
        await _run_pipeline_async(doc_id, audio_url, latitude, longitude, timestamp)

    except Exception as e:
        logger.error(f"Supabase-triggered processing failed for {doc_id}: {e}")
    finally:
        _processing_set.discard(doc_id)

async def _start_supabase_listener():
    """
    Starts a real-time Supabase listener on the incidents table with retry logic.
    Falls back to polling mode if WebSocket connection repeatedly fails.
    """
    if not config.SUPABASE_URL or not config.SUPABASE_KEY:
        logger.warning("Supabase credentials missing — cannot start listener.")
        return

    retry_delay = 5
    consecutive_failures = 0
    FALLBACK_THRESHOLD = 3

    while True:
        if consecutive_failures >= FALLBACK_THRESHOLD:
            logger.warning(f"⚠ WebSocket failed {consecutive_failures} times. Switching to REST POLLING mode...")
            await _polling_listener()
            return

        try:
            async_client = await acreate_client(config.SUPABASE_URL, config.SUPABASE_KEY)
            
            def on_change(payload):
                try:
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
                            
                            # Replace raw thread with asyncio task registered in background tasks
                            task = asyncio.create_task(_process_from_supabase_async(doc_id, new_data))
                            _background_tasks.add(task)
                            task.add_done_callback(_background_tasks.discard)
                        else:
                            logger.info(f"⏳ Skipping {doc_id}: audio_url is missing (waiting for upload).")
                except Exception as cb_err:
                    logger.error(f"Error in on_change callback: {cb_err}")

            channel = async_client.channel("db-changes")
            channel.on_postgres_changes(event="*", schema="public", table="incidents", callback=on_change)
            await channel.subscribe()
            
            logger.info("👁 Subscribed to Supabase Realtime (WebSocket) successfully.")
            consecutive_failures = 0  # Reset
            
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
    """
    logger.info("🔄 POLLING MODE ACTIVE — Checking Supabase REST API every 10s for new incidents...")
    POLL_INTERVAL = 10

    while True:
        try:
            # Run blocking supabase REST call in thread executor
            loop = asyncio.get_event_loop()
            def fetch_pending():
                return supabase_client.client.table("incidents") \
                    .select("id, audio_url, latitude, longitude, timestamp, status") \
                    .eq("status", "READY_FOR_ANALYSIS") \
                    .not_.is_("audio_url", "null") \
                    .execute()
                    
            response = await loop.run_in_executor(None, fetch_pending)

            if response.data:
                for incident in response.data:
                    doc_id = str(incident.get("id"))
                    
                    if doc_id in _processing_set:
                        continue

                    logger.info(f"📡 POLL: Found unanalyzed incident {doc_id} — queuing...")
                    task = asyncio.create_task(_process_from_supabase_async(doc_id, incident))
                    _background_tasks.add(task)
                    task.add_done_callback(_background_tasks.discard)
            else:
                logger.debug("📡 POLL: No new incidents found.")

        except Exception as e:
            logger.error(f"📡 POLL error: {e}")

        await asyncio.sleep(POLL_INTERVAL)

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

    # Explicit startup initialization of Supabase client
    if supabase_client.client is None:
        logger.info("Initializing Supabase client on startup...")
        supabase_client._initialize()
    logger.info("AI Service ready")

    # Start the Supabase real-time listener as a background task if enabled
    if config.ENABLE_REALTIME_LISTENER:
        logger.info("Starting Supabase Realtime Listener...")
        listener_task = asyncio.create_task(_start_supabase_listener())
        _background_tasks.add(listener_task)
        listener_task.add_done_callback(_background_tasks.discard)
    else:
        logger.info("Supabase Realtime Listener is DISABLED (ENABLE_REALTIME_LISTENER=False)")
    
    yield
    
    # Shutdown: Cancel all tracked background tasks to avoid "Event loop is closed" errors
    logger.info("Shutting down AI Service: gathering active background tasks...")
    if _background_tasks:
        task_count = len(_background_tasks)
        logger.info(f"Cancelling {task_count} active background tasks...")
        for task in list(_background_tasks):
            task.cancel()
            
        try:
            # Wait with a 5-second timeout for cleanup
            await asyncio.wait_for(
                asyncio.gather(*list(_background_tasks), return_exceptions=True),
                timeout=5.0
            )
            logger.info("Background tasks cleaned up successfully.")
        except asyncio.TimeoutError:
            logger.warning("Timed out waiting for background tasks to terminate during shutdown.")
            
        cancelled = sum(1 for t in _background_tasks if t.cancelled())
        completed = len(_background_tasks) - cancelled
        logger.info(f"Shutdown complete. Tasks cancelled: {cancelled}, completed: {completed}")

app = FastAPI(title="SOS Intelligence AI Service", version="1.0.0", lifespan=lifespan)

# Mount static files for the admin panel
if not os.path.exists("static"):
    os.makedirs("static")
app.mount("/admin", StaticFiles(directory="static", html=True), name="static")

# Middleware: API Key verification for `/api/*` routes
@app.middleware("http")
async def api_key_middleware(request: Request, call_next):
    if request.url.path.startswith("/api/"):
        secret_key = config.AI_SERVICE_SECRET_KEY
        client_key = request.headers.get("X-Service-Key")
        if not secret_key or client_key != secret_key:
            logger.warning(f"Unauthorized API request blocked to {request.url.path} from host {request.client.host}")
            return JSONResponse(status_code=401, content={"detail": "Unauthorized"})
    response = await call_next(request)
    return response

@app.get("/health")
def health_check():
    """Health check endpoint for Cloud Run."""
    if not (transcription_service and audio_stress_detector and threat_classifier):
        raise HTTPException(status_code=503, detail="Models not fully loaded")
        
    backend = "groq" if (transcription_service.groq_whisper and config.GROQ_API_KEY) else "local"
    return {
        "status": "healthy", 
        "version": "1.0.0",
        "transcription_backend": backend
    }

@app.get("/api/incidents")
async def get_incidents(status: str = None, limit: int = 20, offset: int = 0):
    """Retrieve filtered, paginated list of incidents from Supabase with safety restrictions."""
    if not supabase_client.client:
        raise HTTPException(status_code=503, detail="Supabase client not initialized")
    try:
        # Request only safe columns. Never expose phone, email, user_id, or audio_url.
        query = supabase_client.client.table("incidents").select(
            "id, status, threat_type, severity_score, services_needed, created_at"
        )
        if status:
            query = query.ilike("status", status)
            
        loop = asyncio.get_event_loop()
        res = await loop.run_in_executor(
            None,
            lambda: query.order("created_at", desc=True).range(offset, offset + limit - 1).execute()
        )
        return {"incidents": res.data}
    except Exception as e:
        logger.error(f"Error fetching incidents API: {e}")
        raise HTTPException(status_code=500, detail=str(e))

_last_process_all_time = 0.0

@app.post("/api/process-all")
async def trigger_process_all(background_tasks: BackgroundTasks):
    """Triggers batch processing of all pending incidents with rate limiting."""
    global _last_process_all_time
    now = time.time()
    if now - _last_process_all_time < 30.0:
        raise HTTPException(status_code=429, detail="Rate limit exceeded. Please wait 30 seconds.")
    _last_process_all_time = now
    
    if not supabase_client.client:
        raise HTTPException(status_code=503, detail="Supabase client not initialized")
        
    try:
        # Get count of pending/failed/unanalyzed incidents in thread
        loop = asyncio.get_event_loop()
        def check_pending():
            return supabase_client.client.table("incidents").select("id").not_.in_("status", ["ANALYZED", "FAILED"]).execute()
            
        res = await loop.run_in_executor(None, check_pending)
        pending_count = len(res.data) if res.data else 0
        
        # Trigger processing in the background (FastAPI thread pool)
        from process_all import process_all_pending
        background_tasks.add_task(process_all_pending)
        
        return {"queued": pending_count}
    except Exception as e:
        logger.error(f"Error triggering batch processing: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/process-incident", response_model=IncidentOutput)
async def process_incident(incident: IncidentInput, background_tasks: BackgroundTasks):
    """
    Manual processing endpoint for SOS incidents.
    """
    logger.info(f"Received manual processing request for incident: {incident.incidentId}")

    try:
        result = await _run_pipeline_async(
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
