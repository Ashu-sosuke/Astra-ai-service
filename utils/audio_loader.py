import requests
import tempfile
import os
import logging
from urllib.parse import urlparse
from config import config

logger = logging.getLogger(__name__)

class AudioLoader:
    @staticmethod
    def validate_url(url: str) -> bool:
        """Basic validation of the signed URL."""
        parsed = urlparse(url)
        return bool(parsed.scheme and parsed.netloc)

    @staticmethod
    def download_audio(url: str) -> str:
        """
        Downloads audio from a signed URL to a temporary file.
        Returns the path to the temporary file.
        Raises ValueError if download fails or format is invalid.
        """
        if not AudioLoader.validate_url(url):
            raise ValueError("Invalid audio URL format.")

        try:
            # Stream download to avoid loading large files into memory
            with requests.get(url, stream=True, timeout=10) as response:
                response.raise_for_status()
                
                content_type = response.headers.get('Content-Type', '').lower()
                # Basic check, though signed URLs might sometimes lack strict content-types or use application/octet-stream
                if content_type and content_type not in config.ALLOWED_AUDIO_TYPES and 'octet-stream' not in content_type:
                     logger.warning(f"Warning: Unexpected Content-Type {content_type}")

                # Create a temp file
                # Suffix is important for ffmpeg/whisper to detect format
                suffix = ".tmp" 
                if "wav" in url.lower(): suffix = ".wav"
                elif "mp3" in url.lower(): suffix = ".mp3"
                elif "ogg" in url.lower(): suffix = ".ogg"
                
                with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp_file:
                    for chunk in response.iter_content(chunk_size=8192):
                        tmp_file.write(chunk)
                    return tmp_file.name
                    
        except requests.RequestException as e:
            logger.error(f"Failed to download audio: {e}")
            raise ValueError(f"Failed to download audio: {str(e)}")

    @staticmethod
    def cleanup_file(path: str):
        """Removes the temporary file."""
        if path and os.path.exists(path):
            try:
                os.remove(path)
            except Exception as e:
                logger.error(f"Failed to delete temp file {path}: {e}")
