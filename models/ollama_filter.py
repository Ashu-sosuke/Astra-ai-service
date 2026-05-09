import requests
import json
import logging
from config import config

logger = logging.getLogger(__name__)

class OllamaFilter:
    def __init__(self):
        self.url = f"{config.OLLAMA_BASE_URL}/api/generate"
        self.model = config.OLLAMA_MODEL
        logger.info(f"Initialized Ollama Filter with model: {self.model} at {self.url}")
        
        # Check if Ollama is available at startup
        self._available = self._check_availability()

    def _check_availability(self) -> bool:
        """Check if Ollama server is running."""
        try:
            resp = requests.get(config.OLLAMA_BASE_URL, timeout=3)
            if resp.status_code == 200:
                logger.info("Ollama server is available.")
                return True
        except Exception:
            pass
        logger.warning("Ollama server is NOT available. Summaries will be generated from transcript instead.")
        return False

    def filter_transcription(self, transcribed_text: str) -> dict:
        """
        Filters and summarizes the transcription using Ollama LLM.
        Falls back to a simple rule-based summary if Ollama is unavailable.
        """
        if not self._available:
            return self._fallback_summary(transcribed_text)
        
        system_prompt = """
        You are an emergency analysis AI for an SOS Companion app. 
        Your job is to read transcribed voice messages and filter the content.
        You must extract the intent, determine if it is an emergency, and provide a 1-sentence summary.
        
        Always return your response in valid JSON format ONLY, exactly like this:
        {
           "is_emergency": true,
           "intent": "medical",
           "summary": "User is experiencing chest pain."
        }
        """
        
        payload = {
            "model": self.model,
            "prompt": f"{system_prompt}\n\nInput: \"{transcribed_text}\"\nOutput:",
            "stream": False,
            "format": "json"
        }
        
        try:
            logger.info(f"Sending text to Ollama ({self.model}) for filtering...")
            response = requests.post(self.url, json=payload, timeout=30)
            response.raise_for_status()
            
            result = response.json()
            raw_response = result.get('response', '{}')
            
            # Basic cleanup in case of extra text
            if "```json" in raw_response:
                raw_response = raw_response.split("```json")[1].split("```")[0].strip()
            elif "{" in raw_response:
                raw_response = raw_response[raw_response.find("{"):raw_response.rfind("}")+1]
                
            parsed = json.loads(raw_response)
            logger.info(f"Ollama result: emergency={parsed.get('is_emergency')}, intent={parsed.get('intent')}")
            return parsed
        except requests.ConnectionError:
            logger.warning("Ollama connection refused. Using fallback summary.")
            self._available = False
            return self._fallback_summary(transcribed_text)
        except Exception as e:
            logger.error(f"Ollama filtering failed: {e}")
            return self._fallback_summary(transcribed_text)

    def _fallback_summary(self, text: str) -> dict:
        """Generate a simple rule-based summary when Ollama is unavailable."""
        if not text or text == "[No speech detected]":
            return {
                "is_emergency": False,
                "intent": "unknown",
                "summary": "No speech was detected in the recording."
            }
        
        text_lower = text.lower()
        
        # Simple keyword-based emergency detection
        emergency_words = ["help", "fire", "gun", "shoot", "kill", "blood", 
                           "ambulance", "dying", "attack", "kidnap", "emergency"]
        is_emergency = any(word in text_lower for word in emergency_words)
        
        # Simple intent detection
        intent = "general"
        if any(w in text_lower for w in ["fire", "burning", "smoke"]):
            intent = "fire"
        elif any(w in text_lower for w in ["blood", "hurt", "pain", "ambulance", "medical"]):
            intent = "medical"
        elif any(w in text_lower for w in ["gun", "shoot", "knife", "attack"]):
            intent = "assault"
        elif any(w in text_lower for w in ["kidnap", "taken", "hostage"]):
            intent = "kidnap"
        elif any(w in text_lower for w in ["help", "scared", "danger"]):
            intent = "panic"
        
        # Truncate for summary
        summary = text[:150] + ("..." if len(text) > 150 else "")
        
        return {
            "is_emergency": is_emergency,
            "intent": intent,
            "summary": summary
        }
