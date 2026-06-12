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
        Matches the LIVE database schema and gracefully handles column mismatches.
        """
        if not self.client:
            logger.error("Supabase client is uninitialized.")
            return False

        import json

        # ── Build payload matching live DB columns ────────────────────────────
        stress_val = analysis_data.get("stress_score") or analysis_data.get("stressScore")
        severity_val = analysis_data.get("severity_score") or analysis_data.get("severityScore")
        threat_val = analysis_data.get("threat_type") or analysis_data.get("threatType")
        final_sev = analysis_data.get("final_severity") or analysis_data.get("finalSeverity")
        rec_action = analysis_data.get("recommended_action") or analysis_data.get("recommendedAction")
        transcript_val = analysis_data.get("transcript")

        # Extract processing_time from nested details or top-level
        processing_time = analysis_data.get("processing_time_sec")
        details_dict = analysis_data.get("details")
        if processing_time is None and isinstance(details_dict, dict):
            processing_time = details_dict.get("processing_time_sec")

        payload = {
            "status": analysis_data.get("status", "ANALYZED"),
            "updated_at": "now()",
            "last_updated": "now()",
        }

        # Text fields (both new and legacy aliases)
        if transcript_val is not None:
            payload["transcript"] = transcript_val
            payload["transcription"] = transcript_val  # legacy alias

        if analysis_data.get("summary") is not None:
            payload["summary"] = analysis_data["summary"]

        if analysis_data.get("intent") is not None:
            payload["intent"] = analysis_data["intent"]

        if analysis_data.get("error_message") is not None:
            payload["error_message"] = analysis_data["error_message"]

        if rec_action is not None:
            payload["recommended_action"] = rec_action

        if threat_val is not None:
            payload["threat_type"] = threat_val

        if final_sev is not None:
            payload["final_severity"] = final_sev

        # Numeric fields (both new and legacy aliases)
        if stress_val is not None:
            payload["stress_score"] = float(stress_val)
            payload["stress_level"] = str(stress_val)  # legacy alias

        if severity_val is not None:
            payload["fusion_score"] = float(severity_val)  # live DB column name

        if analysis_data.get("confidence") is not None:
            payload["confidence"] = float(analysis_data["confidence"])

        if processing_time is not None:
            payload["processing_time_sec"] = float(processing_time)

        if analysis_data.get("latitude") is not None:
            payload["latitude"] = float(analysis_data["latitude"])

        if analysis_data.get("longitude") is not None:
            payload["longitude"] = float(analysis_data["longitude"])

        # Boolean fields
        if analysis_data.get("is_emergency") is not None:
            payload["is_emergency"] = bool(analysis_data["is_emergency"])

        if analysis_data.get("is_override_triggered") is not None:
            payload["is_override_triggered"] = bool(analysis_data["is_override_triggered"])

        # JSONB / complex fields
        if details_dict is not None:
            # Serialize to JSON string for the JSONB column
            try:
                payload["details"] = json.dumps(details_dict) if isinstance(details_dict, dict) else details_dict
            except (TypeError, ValueError):
                pass

        # Optional new columns (may not exist yet on live DB)
        optional_columns = {}
        services_needed = analysis_data.get("services_needed")
        if services_needed is not None:
            optional_columns["services_needed"] = json.dumps(services_needed) if isinstance(services_needed, list) else services_needed

        secondary_threats = analysis_data.get("secondary_threats")
        if secondary_threats is not None:
            optional_columns["secondary_threats"] = json.dumps(secondary_threats) if isinstance(secondary_threats, list) else secondary_threats

        if analysis_data.get("situation_details") is not None:
            optional_columns["situation_details"] = analysis_data["situation_details"]

        if analysis_data.get("victim_count") is not None:
            optional_columns["victim_count"] = int(analysis_data["victim_count"])

        if analysis_data.get("model_version") is not None:
            optional_columns["model_version"] = analysis_data["model_version"]

        # ── Execute Update ────────────────────────────────────────────────────
        # First try with all columns (core + optional)
        full_payload = {**payload, **optional_columns}
        logger.info(f"Updating incident {incident_id} with {len(full_payload)} fields: {list(full_payload.keys())}")

        for attempt in range(2):
            try:
                current_payload = full_payload if attempt == 0 else payload
                if attempt == 1:
                    logger.info(f"Retry with core-only payload ({len(payload)} fields)")

                res = self.client.table("incidents").update(current_payload).eq("id", incident_id).execute()

                if res.data:
                    logger.info(f"Updated Supabase record {incident_id} successfully ({len(current_payload)} fields).")
                    return True
                else:
                    logger.warning(f"Update returned no data for {incident_id}. Record may not exist.")
                    return False

            except Exception as e:
                err_str = str(e)
                if "column" in err_str.lower() and "does not exist" in err_str.lower():
                    logger.warning(f"Column mismatch on attempt {attempt+1}: {err_str[:120]}")
                    # Fall through to retry with core-only payload
                    continue
                else:
                    logger.error(f"Attempt {attempt+1} failed to update incident {incident_id}: {e}")
                    if attempt == 0:
                        self._initialize()
                    continue

        logger.error(f"All attempts to update incident {incident_id} have failed.")
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
