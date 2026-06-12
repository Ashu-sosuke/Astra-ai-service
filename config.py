import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

class Config:
    # Model Paths (can be local paths or HuggingFace IDs)
    WHISPER_MODEL_SIZE = os.getenv("WHISPER_MODEL_SIZE", "small") # Using 'small' as default for 4GB VRAM
    THREAT_MODEL_ID = os.getenv("THREAT_MODEL_ID", "distilbert-base-uncased-finetuned-sst-2-english")
    OFFLINE_MODE = os.getenv("OFFLINE_MODE", "False").lower() == "true"
    
    # Audio Settings
    MAX_AUDIO_DURATION_SEC = 300  # 5 minutes
    ALLOWED_AUDIO_TYPES = ["audio/wav", "audio/mpeg", "audio/mp3", "audio/ogg", "audio/x-wav", "audio/mp4", "audio/m4a", "audio/x-m4a"]
    
    # Feature Toggles
    ENABLE_EMOTION_DETECTION = os.getenv("ENABLE_EMOTION_DETECTION", "True").lower() == "true"
    ENABLE_REALTIME_LISTENER = os.getenv("ENABLE_REALTIME_LISTENER", "True").lower() == "true"
    
    # Weights for Severity Fusion
    WEIGHT_STRESS = 0.4
    WEIGHT_THREAT = 0.3
    WEIGHT_KEYWORD = 0.2
    WEIGHT_LOCATION = 0.1

    # Groq Settings
    GROQ_API_KEY = os.getenv("GROQ_API_KEY")
    GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
    GROQ_WHISPER = os.getenv("GROQ_WHISPER", "False").lower() == "true"
    
    # API Security Settings
    AI_SERVICE_SECRET_KEY = os.getenv("AI_SERVICE_SECRET_KEY")

    # Legacy Ollama Settings
    OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1")

    # Supabase Settings (New)
    SUPABASE_URL = os.getenv("SUPABASE_URL")
    SUPABASE_KEY = os.getenv("SUPABASE_KEY")
    SUPABASE_BUCKET = os.getenv("SUPABASE_BUCKET", "incident-audio")

    # Firebase Settings (Legacy)
    FIREBASE_CREDENTIALS_PATH = os.getenv("FIREBASE_CREDENTIALS_PATH", "firebase-service-account.json")
    FIREBASE_STORAGE_BUCKET = os.getenv("FIREBASE_STORAGE_BUCKET", "astrasos-278a5.firebasestorage.app")
    FIRESTORE_COLLECTION = os.getenv("FIRESTORE_COLLECTION", "incidents")

    # Twilio Settings
    TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
    TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
    TWILIO_FROM_NUMBER = os.getenv("TWILIO_FROM_NUMBER")

config = Config()
