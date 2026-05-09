import os
import tempfile
import logging
from supabase import create_client, Client
from config import config
from .crypto_utils import CryptoManager

logger = logging.getLogger(__name__)

class SupabaseClient:
    def __init__(self):
        self.client: Client = None
        self._initialize()

    def _initialize(self):
        try:
            if not config.SUPABASE_URL or not config.SUPABASE_KEY:
                logger.warning("Supabase URL or Key missing in config. Supabase integration will be disabled.")
                return
            
            self.client = create_client(config.SUPABASE_URL, config.SUPABASE_KEY)
            logger.info(f"Supabase client initialized at {config.SUPABASE_URL}")
        except Exception as e:
            logger.error(f"Failed to initialize Supabase client: {e}")

    def download_audio(self, storage_path_or_url: str) -> str:
        """
        Downloads a file from Supabase Storage to a temporary file.
        Accepts either a full URL or a storage path.
        """
        if not self.client:
            raise RuntimeError("Supabase client is not initialized.")

        try:
            raw_input = storage_path_or_url.strip()
            path = raw_input
            
            logger.info(f"download_audio received: {raw_input}")
            
            # If it's a full URL, we need to extract the path
            if path.startswith("http"):
                # Robust extraction: Find the bucket name in the URL and take everything after it
                bucket_marker = f"/{config.SUPABASE_BUCKET}/"
                if bucket_marker in path:
                    path = path.split(bucket_marker)[-1].split("?")[0]
                    logger.info(f"Parsed path from URL: {path}")
                else:
                    # Fallback: look for /object/public/ or similar
                    for marker in ["/public/", "/sign/", "/authenticated/"]:
                        if marker in path:
                            parts = path.split(marker)[-1].split("/", 1)
                            if len(parts) == 2:
                                # First part is bucket, second is path
                                _, path = parts
                                path = path.split("?")[0]
                                logger.info(f"Fallback parsed path: {path}")
                                break

            logger.info(f"Attempting download from bucket '{config.SUPABASE_BUCKET}', path '{path}'")
            
            # Detect file extension
            suffix = ".tmp"
            if path.lower().endswith(".m4a"): suffix = ".m4a"
            elif path.lower().endswith(".wav"): suffix = ".wav"
            elif path.lower().endswith(".mp3"): suffix = ".mp3"
            
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp_file:
                # Supabase storage download
                data = self.client.storage.from_(config.SUPABASE_BUCKET).download(path)
                with open(tmp_file.name, 'wb') as f:
                    f.write(data)
                
                logger.info(f"Successfully downloaded {len(data)} bytes to {tmp_file.name}")
                return tmp_file.name

        except Exception as e:
            logger.error(f"Failed to download from Supabase Storage: {e}")
            raise ValueError(f"Supabase Storage Download Failed: {str(e)}")

    def get_audio_chunks(self, incident_id: str) -> list:
        """
        Fetches all audio chunks associated with an incident from the audio_chunks table.
        """
        if not self.client:
            return []
        
        try:
            res = self.client.table("audio_chunks") \
                .select("chunk_url") \
                .eq("incident_id", incident_id) \
                .order("timestamp", desc=False) \
                .execute()
            
            chunks = [item["chunk_url"] for item in res.data if item.get("chunk_url")]
            logger.info(f"Found {len(chunks)} audio chunks for incident {incident_id}")
            return chunks
        except Exception as e:
            logger.error(f"Failed to fetch audio chunks: {e}")
            return []



    def get_location_risk(self, latitude: float, longitude: float, radius_deg: float = 0.05) -> float:
        """
        Calculates location risk based on nearby historical crime incidents.
        Returns a score from 0.0 to 1.0.
        """
        if not self.client or latitude is None or longitude is None:
            return 0.0

        try:
            # Simple bounding box query
            res = self.client.table("crime_data") \
                .select("severity") \
                .gte("lat", latitude - radius_deg) \
                .lte("lat", latitude + radius_deg) \
                .gte("lng", longitude - radius_deg) \
                .lte("lng", longitude + radius_deg) \
                .execute()

            incidents = res.data
            if not incidents:
                return 0.0

            # Calculate risk: More incidents and higher severity = higher risk
            # Max risk reached at 5 incidents with avg severity of 8
            total_severity = sum([int(i.get("severity", 5)) for i in incidents])
            risk_score = min(1.0, total_severity / 40.0)
            
            logger.info(f"Location risk calculated: {risk_score:.2f} based on {len(incidents)} nearby crimes.")
            return risk_score
        except Exception as e:
            logger.error(f"Failed to calculate location risk: {e}")
            return 0.0

    def update_incident(self, incident_id: str, analysis_data: dict) -> bool:
        """
        Updates the incident record in Postgres with AI analysis results.
        Supports both the new schema and the legacy schema via fallback.
        Ensures ALL scores and metadata are saved.
        """
        if not self.client:
            logger.error("Supabase client is uninitialized.")
            return False

        # 1. ATTEMPT NEW SCHEMA (Primary) with Retries
        for attempt in range(2):
            try:
                new_payload = {
                    "transcript": analysis_data.get("transcript"),
                    "stress_score": analysis_data.get("stress_score") or analysis_data.get("stressScore"),
                    "threat_type": analysis_data.get("threat_type") or analysis_data.get("threatType"),
                    "severity_score": analysis_data.get("severity_score") or analysis_data.get("severityScore"),
                    "final_severity": analysis_data.get("final_severity") or analysis_data.get("finalSeverity"),
                    "confidence": analysis_data.get("confidence"),
                    "recommended_action": analysis_data.get("recommended_action") or analysis_data.get("recommendedAction"),
                    "summary": analysis_data.get("summary"),
                    "is_emergency": analysis_data.get("is_emergency"),
                    "intent": analysis_data.get("intent"),
                    "services_needed": analysis_data.get("services_needed"),
                    "situation_details": analysis_data.get("situation_details"),
                    "victim_count": analysis_data.get("victim_count"),
                    "processing_time_sec": analysis_data.get("details", {}).get("processing_time_sec"),
                    "model_version": analysis_data.get("model_version", "v3.0.0"),
                    "is_override_triggered": analysis_data.get("is_override_triggered", False),
                    "latitude": analysis_data.get("latitude"),
                    "longitude": analysis_data.get("longitude"),
                    "timestamp": analysis_data.get("timestamp"),
                    "details": analysis_data.get("details"),
                    "status": "ANALYZED",
                    "updated_at": "now()"
                }
                
                res = self.client.table("incidents").update(new_payload).eq("id", incident_id).execute()
                if not res.data:
                    # Try by incident_id if id fails
                    res = self.client.table("incidents").update(new_payload).eq("incident_id", incident_id).execute()
                
                if res.data:
                    logger.info(f"Updated Supabase record {incident_id} successfully (NEW schema).")
                    return True
                break
            except Exception as e:
                err_str = str(e)
                if "PGRST204" in err_str or "column" in err_str.lower():
                    logger.warning(f"New schema update failed for {incident_id} (missing columns). Attempting legacy fallback...")
                    break # Go to legacy fallback
                
                logger.warning(f"Attempt {attempt+1} failed to update Supabase record (New Schema): {e}")
                if attempt == 0:
                    self._initialize() # Re-init client
                continue

        # 2. FALLBACK TO LEGACY SCHEMA
        try:
            legacy_payload = {
                "transcription": analysis_data.get("transcript"),
                "stress_level": str(analysis_data.get("stress_score") or analysis_data.get("stressScore")),
                "threat_type": analysis_data.get("threat_type") or analysis_data.get("threatType"),
                "fusion_score": analysis_data.get("severity_score") or analysis_data.get("severityScore"),
                "final_severity": analysis_data.get("final_severity") or analysis_data.get("finalSeverity"),
                "recommended_action": analysis_data.get("recommended_action") or analysis_data.get("recommendedAction"),
                "summary": analysis_data.get("summary"),
                "intent": analysis_data.get("intent"),
                "confidence": analysis_data.get("confidence"),
                "is_emergency": analysis_data.get("is_emergency"),
                "latitude": analysis_data.get("latitude"),
                "longitude": analysis_data.get("longitude"),
                "status": "ANALYZED",
                "last_updated": "now()"
            }
            
            res = self.client.table("incidents").update(legacy_payload).eq("id", incident_id).execute()
            if not res.data:
                res = self.client.table("incidents").update(legacy_payload).eq("incident_id", incident_id).execute()
            
            if res.data:
                logger.info(f"Updated Supabase record {incident_id} using LEGACY schema.")
                return True
            else:
                logger.error(f"No record found to update for {incident_id} in either schema.")
                return False
        except Exception as e:
            logger.error(f"Critical failure updating Supabase record (Legacy Fallback): {e}")
            return False

    def get_user_contacts(self, user_id: str) -> list:
        """
        Fetches all trusted contacts for a given user ID.
        """
        if not self.client:
            return []
        
        for attempt in range(2):
            try:
                res = self.client.table("trusted_contacts") \
                    .select("*") \
                    .eq("user_id", user_id) \
                    .execute()
                
                if res.data:
                    logger.info(f"Retrieved {len(res.data)} contacts. Fields: {list(res.data[0].keys())}")
                
                contacts = []
                for item in res.data:
                    encrypted_phone = item.get("phone_e164")
                    if encrypted_phone:
                        decrypted = CryptoManager.decrypt(encrypted_phone)
                        if decrypted:
                            item["phone_e164"] = decrypted
                            contacts.append(item)
                
                return contacts
            except Exception as e:
                logger.warning(f"Attempt {attempt+1} failed to fetch trusted contacts: {e}")
                if attempt == 0:
                    self._initialize() # Re-init client
                continue
        
        return []

    def get_all_incidents(self) -> list:
        """
        Fetches all incidents from the Postgres table.
        """
        if not self.client:
            return []
        
        try:
            res = self.client.table("incidents").select("*").order("created_at", desc=True).execute()
            return res.data
        except Exception as e:
            logger.error(f"Failed to fetch incidents from Supabase: {e}")
            return []

supabase_client = SupabaseClient()
