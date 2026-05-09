import logging
import json
from config import config
from groq import Groq

logger = logging.getLogger(__name__)

class ThreatClassifier:
    def __init__(self):
        self.api_key = config.GROQ_API_KEY
        self.model = config.GROQ_MODEL
        if not self.api_key:
            logger.warning("GROQ_API_KEY not found. Threat classification will use fallback keywords.")
            self.client = None
        else:
            self.client = Groq(api_key=self.api_key)
            logger.info(f"Initialized Groq-powered Threat Classifier with model: {self.model}")

        # Emergency keyword dictionary for fallback
        self.KEYWORD_MAP = {
            "FIRE": ["fire", "burning", "smoke", "flames", "blaze", "arson", "gas leak", "explosion"],
            "MEDICAL": ["heart attack", "ambulance", "bleeding", "unconscious", "seizure", 
                        "breathing", "injured", "hurt", "pain", "hospital", "doctor", 
                        "medical", "dying", "dead", "blood", "broken", "chest pain",
                        "stroke", "allergic", "overdose", "poison", "choking"],
            "ASSAULT": ["gun", "shoot", "shooting", "knife", "stab", "attack", "beat", 
                        "hitting", "kill", "murder", "weapon", "rob", "robbery", "threat",
                        "assault", "fight", "punch", "gunshot", "armed", "violent"],
            "KIDNAP": ["kidnap", "abduct", "taken", "hostage", "ransom", "tied up",
                       "locked", "trapped", "prisoner", "held against"],
            "ACCIDENT": ["accident", "crash", "collision", "vehicle", "car", "truck",
                         "motorcycle", "hit and run", "road", "traffic"],
            "PANIC": ["help", "help me", "scared", "afraid", "danger", "emergency",
                      "sos", "save me", "please help", "stalking", "following me",
                      "someone is following", "chasing"]
        }

    def classify(self, text: str) -> dict:
        """
        Classifies the transcript into emergency categories using Groq LLM.
        Now returns enriched classification with primary + secondary threat types.
        """
        if not text or text == "[No speech detected]":
            return {
                "threat_type": "FALSE_ALARM",
                "confidence": 0.0,
                "secondary_threats": [],
                "raw_label": "FALSE_ALARM"
            }

        if not self.client:
            return self._keyword_classify(text)

        system_prompt = """You are an emergency threat classifier for an SOS emergency response system.
Analyze the transcribed emergency audio and classify it.

PRIMARY CATEGORIES (choose the most severe/dominant):
- ASSAULT: Physical violence, weapons, shooting, stabbing, fighting
- KIDNAP: Abduction, hostage, held against will, trafficking
- FIRE: Fire, burning, smoke, gas leak, explosion
- MEDICAL: Health emergency, injury, cardiac, breathing, bleeding
- ACCIDENT: Vehicle crash, collision, traffic incident
- PANIC: General distress, fear, stalking, unknown danger
- FALSE_ALARM: No real emergency detected, accidental trigger

IMPORTANT RULES:
1. Choose the PRIMARY threat type — the most dangerous/urgent one
2. List any SECONDARY threats (e.g., a fire with injuries has primary=FIRE, secondary=["MEDICAL"])
3. Confidence should reflect how certain you are (0.0-1.0)
4. Be aggressive in classification — when in doubt, classify as MORE severe, not less
5. If someone says "fire" and mentions being hurt/trapped, both FIRE and MEDICAL apply

Always return valid JSON ONLY:
{
   "threat_type": "FIRE",
   "confidence": 0.95,
   "secondary_threats": ["MEDICAL"]
}"""

        try:
            completion = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"Emergency audio transcript:\n\"{text}\""}
                ],
                response_format={"type": "json_object"},
                temperature=0.1
            )
            
            raw_response = completion.choices[0].message.content
            parsed = json.loads(raw_response)
            
            # Normalize
            parsed.setdefault("threat_type", "FALSE_ALARM")
            parsed.setdefault("confidence", 0.5)
            parsed.setdefault("secondary_threats", [])
            
            # Ensure valid threat type
            valid_types = {"ASSAULT", "KIDNAP", "FIRE", "MEDICAL", "ACCIDENT", "PANIC", "FALSE_ALARM"}
            if parsed["threat_type"] not in valid_types:
                parsed["threat_type"] = "PANIC"
            
            logger.info(f"Groq Threat: {parsed['threat_type']} (conf={parsed['confidence']}) | "
                        f"Secondary: {parsed.get('secondary_threats', [])}")
            return parsed
            
        except Exception as e:
            logger.error(f"Groq classification failed: {e}. Falling back to keywords.")
            return self._keyword_classify(text)

    def _keyword_classify(self, text: str) -> dict:
        """Classify based on keyword presence. Returns the highest-priority match."""
        text_lower = text.lower()
        priority_order = ["ASSAULT", "KIDNAP", "FIRE", "MEDICAL", "ACCIDENT", "PANIC"]
        
        matches = {}
        for category in priority_order:
            keywords = self.KEYWORD_MAP[category]
            found = [kw for kw in keywords if kw in text_lower]
            if found:
                confidence = min(0.9, 0.5 + len(found) * 0.15)
                matches[category] = {
                    "threat_type": category,
                    "confidence": confidence,
                    "secondary_threats": []
                }
        
        if matches:
            primary = None
            secondary = []
            for category in priority_order:
                if category in matches:
                    if primary is None:
                        primary = matches[category]
                    else:
                        secondary.append(category)
            
            if primary:
                primary["secondary_threats"] = secondary
                return primary
        
        return {"threat_type": "FALSE_ALARM", "confidence": 0.1, "secondary_threats": []}
