import firebase_admin
from firebase_admin import credentials, storage, firestore
import tempfile
import os
import logging
from config import config

logger = logging.getLogger(__name__)

class FirebaseClient:
    def __init__(self):
        self.bucket = None
        self.db = None
        self._initialize()

    def _initialize(self):
        try:
            if not firebase_admin._apps:
                cred_path = config.FIREBASE_CREDENTIALS_PATH
                if not os.path.exists(cred_path):
                    logger.warning(f"Firebase credentials not found at {cred_path}. Downstream Firebase calls will fail.")
                    return
                
                cred = credentials.Certificate(cred_path)
                firebase_admin.initialize_app(cred, {
                    'storageBucket': config.FIREBASE_STORAGE_BUCKET
                })
                logger.info(f"Firebase Admin SDK initialized. Bucket: {config.FIREBASE_STORAGE_BUCKET}")
            
            self.bucket = storage.bucket()
            self.db = firestore.client()
        except Exception as e:
            logger.error(f"Failed to initialize Firebase Admin SDK: {e}")

    def download_audio(self, storage_path_or_url: str) -> str:
        """
        Downloads a file from Firebase Storage to a temporary file.
        Accepts either a full URL or a storage path.
        Returns the path to the downloaded temporary file.
        
        Supported URL formats:
        - gs://bucket/path/to/file.m4a
        - https://firebasestorage.googleapis.com/v0/b/[bucket]/o/[encoded_path]?alt=media&token=...
        - Direct storage path: users/uid/incidents/file.m4a
        """
        if not self.bucket:
            raise RuntimeError("Firebase is not initialized. Check credentials and bucket config.")

        try:
            import urllib.parse
            
            path = storage_path_or_url.strip()
            logger.info(f"Resolving audio source: {path[:120]}...")
            
            if path.startswith("gs://"):
                # gs://bucket-name/path/to/file
                path = path.replace(f"gs://{config.FIREBASE_STORAGE_BUCKET}/", "")
                
            elif "firebasestorage.googleapis.com" in path or "firebasestorage.app" in path:
                # Format: https://firebasestorage.googleapis.com/v0/b/[bucket]/o/[ENCODED_PATH]?alt=media&token=...
                parsed = urllib.parse.urlparse(path)
                # parsed.path = /v0/b/bucket/o/users%2Fuid%2Fincidents%2Ffile.m4a
                if '/o/' in parsed.path:
                    encoded_path = parsed.path.split('/o/')[-1]
                    path = urllib.parse.unquote(encoded_path)
                else:
                    logger.warning(f"Firebase URL missing '/o/' segment: {path[:120]}")
            
            logger.info(f"Resolved storage path: {path}")
            
            blob = self.bucket.blob(path)
            if not blob.exists():
                raise ValueError(f"File '{path}' does not exist in bucket '{config.FIREBASE_STORAGE_BUCKET}'")
            
            # Detect file extension for proper downstream handling
            suffix = ".tmp"
            path_lower = path.lower()
            if path_lower.endswith(".wav"): suffix = ".wav"
            elif path_lower.endswith(".mp3"): suffix = ".mp3"
            elif path_lower.endswith(".ogg"): suffix = ".ogg"
            elif path_lower.endswith(".m4a"): suffix = ".m4a"

            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp_file:
                logger.info(f"Downloading '{path}' from Firebase Storage...")
                blob.download_to_filename(tmp_file.name)
                logger.info(f"Downloaded to temp file: {tmp_file.name}")
                return tmp_file.name
                
        except Exception as e:
            logger.error(f"Failed to download audio from Firebase Storage: {e}")
            raise ValueError(f"Firebase Storage Download Failed: {str(e)}")

    def save_incident_analysis(self, incident_id: str, analysis_data: dict) -> bool:
        """
        Saves or updates the specific incident result in Firestore.
        """
        if not self.db:
            logger.error("Firestore client is uninitialized. Cannot save analysis.")
            return False
            
        try:
            collection = config.FIRESTORE_COLLECTION
            doc_ref = self.db.collection(collection).document(incident_id)
            
            # Use set with merge=True to update existing or create new if not present
            doc_ref.set({
                "ai_analysis": analysis_data,
                "status": "ANALYZED",
            }, merge=True)
            
            logger.info(f"Successfully saved analysis for incident {incident_id} to Firestore '{collection}' collection.")
            return True
        except Exception as e:
            logger.error(f"Failed to save to Firestore for incident {incident_id}: {e}")
            return False

    def get_all_incidents(self) -> list:
        """
        Retrieves all incidents from Firestore.
        """
        if not self.db:
            logger.error("Firestore client is uninitialized. Cannot fetch incidents.")
            return []
            
        try:
            # The admin panel now needs to fetch from the new "files" collection group
            collection = "files"
            docs = self.db.collection_group(collection).stream()
            
            incidents = []
            for doc in docs:
                data = doc.to_dict()
                data['id'] = doc.id
                
                # Try to fetch live location from the parent incident document
                # Path: users/{uid}/incidents/{incidentId}/media/audio/files/{fileId}
                try:
                    parent_ref = doc.reference.parent.parent.parent.parent
                    if parent_ref:
                        parent_doc = parent_ref.get()
                        if parent_doc.exists:
                            parent_data = parent_doc.to_dict()
                            
                            if 'lastLocation' in parent_data:
                                loc = parent_data['lastLocation']
                                data['latitude'] = loc.get('lat') or loc.get('latitude')
                                data['longitude'] = loc.get('lng') or loc.get('longitude')
                            else:
                                data['latitude'] = parent_data.get('latitude')
                                data['longitude'] = parent_data.get('longitude')
                except Exception as e:
                    logger.warning(f"Could not fetch parent location for {doc.id}: {e}")

                incidents.append(data)
                
            return incidents
        except Exception as e:
            logger.error(f"Failed to fetch incidents from Firestore: {e}")
            return []

firebase_client = FirebaseClient()
