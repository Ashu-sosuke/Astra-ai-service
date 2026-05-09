import os
import json
import logging
from groq import Groq
from config import config

logger = logging.getLogger(__name__)

class GroqFilter:
    def __init__(self):
        self.api_key = config.GROQ_API_KEY
        self.model = config.GROQ_MODEL
        if not self.api_key:
            logger.warning("GROQ_API_KEY not found. LLM filtering will be disabled (using fallback).")
            self.client = None
        else:
            self.client = Groq(api_key=self.api_key)
            logger.info(f"Initialized Groq Filter with model: {self.model}")

    def filter_transcription(self, transcribed_text: str) -> dict:
        """
        Performs deep AI analysis of the transcription using Groq LLM.
        Returns comprehensive emergency analysis with multi-service routing,
        severity assessment, and actionable intelligence.
        """
        if not self.client:
            return self._fallback_summary(transcribed_text)
        
        system_prompt = """You are AstraSOS Emergency Intelligence — an advanced AI that analyzes emergency voice transcriptions from an SOS app.

Your job is to deeply understand the caller's situation and produce a comprehensive, actionable emergency report.

ANALYSIS REQUIREMENTS:
1. **is_emergency**: Is this a genuine emergency requiring immediate response? (true/false)
2. **severity**: Rate 1-10 how severe this emergency is. 10 = imminent threat to life.
3. **intent**: Primary intent of the caller (one of: medical, fire, assault, kidnap, panic, accident, natural_disaster, general)
4. **services_needed**: List ALL emergency services that should respond. Choose from: ["hospital", "police", "fire"]. Multiple services can be needed (e.g. a fire with injuries needs both "fire" and "hospital"). Always include relevant services.
5. **summary**: A clear, professional 2-3 sentence summary written for emergency dispatchers. Include: what happened, who needs help, what's the immediate danger, any location/context clues from the transcript.
6. **recommended_action**: What should responders do? (one of: EMERGENCY_DISPATCH, ESCALATE, MONITOR, NOTIFY)
7. **victim_count**: Estimated number of people affected (0 if unknown)
8. **situation_details**: Brief description of the specific danger type (e.g. "structure fire in residential building", "knife assault in progress", "cardiac arrest symptoms")

SEVERITY SCALE:
- 9-10: CRITICAL — Active threat to life, ongoing violence, building collapse, cardiac arrest
- 7-8: HIGH — Serious injury, fire spreading, armed suspect nearby
- 5-6: MEDIUM — Non-life-threatening injury, contained fire, suspect fled
- 3-4: LOW — Minor incident, anxiety/panic without physical danger
- 1-2: MINIMAL — False alarm, accidental trigger, no danger detected

SERVICE ROUTING RULES:
- Injuries/medical symptoms → include "hospital"
- Crime/violence/weapons/theft → include "police"  
- Fire/smoke/gas leak/explosion → include "fire"
- Trapped/collapsed building → include "fire" AND "hospital"
- Active shooter/violence with injuries → include ALL THREE
- Accident with injuries → include "hospital" AND "police"
- Kidnapping → include "police"
- Unknown emergency with distress → include ALL THREE

Always return your response in valid JSON format ONLY:
{
   "is_emergency": true,
   "severity": 8,
   "intent": "fire",
   "services_needed": ["fire", "hospital"],
   "summary": "Caller reports their house is on fire. They are trapped inside and requesting immediate firefighter assistance. Smoke inhalation risk is present.",
   "recommended_action": "EMERGENCY_DISPATCH",
   "victim_count": 1,
   "situation_details": "Residential structure fire with person trapped inside"
}"""
        
        try:
            logger.info(f"Sending text to Groq ({self.model}) for deep analysis...")
            completion = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"Emergency transcription to analyze:\n\"{transcribed_text}\""}
                ],
                response_format={"type": "json_object"},
                temperature=0.1  # Low temperature for consistent, accurate analysis
            )
            
            raw_response = completion.choices[0].message.content
            parsed = json.loads(raw_response)
            
            # Validate and normalize the response
            parsed.setdefault("is_emergency", False)
            parsed.setdefault("severity", 5)
            parsed.setdefault("intent", "general")
            parsed.setdefault("services_needed", [])
            parsed.setdefault("summary", transcribed_text[:150])
            parsed.setdefault("recommended_action", "MONITOR")
            parsed.setdefault("victim_count", 0)
            parsed.setdefault("situation_details", "")
            
            # Ensure severity is in range
            parsed["severity"] = max(1, min(10, int(parsed["severity"])))
            
            # Ensure services_needed is a list
            if isinstance(parsed["services_needed"], str):
                parsed["services_needed"] = [parsed["services_needed"]]
            
            logger.info(f"Groq Analysis: emergency={parsed['is_emergency']}, severity={parsed['severity']}/10, "
                        f"intent={parsed['intent']}, services={parsed['services_needed']}")
            logger.info(f"  Summary: {parsed['summary']}")
            return parsed
            
        except Exception as e:
            logger.error(f"Groq filtering failed: {e}")
            return self._fallback_summary(transcribed_text)

    def _fallback_summary(self, text: str) -> dict:
        """Generate a rule-based analysis when Groq is unavailable."""
        if not text or text == "[No speech detected]":
            return {
                "is_emergency": False,
                "severity": 1,
                "intent": "unknown",
                "services_needed": [],
                "summary": "No speech was detected in the recording.",
                "recommended_action": "MONITOR",
                "victim_count": 0,
                "situation_details": "No audio content"
            }
        
        text_lower = text.lower()
        services = set()
        severity = 3
        
        # Service detection
        if any(w in text_lower for w in ["fire", "burning", "smoke", "flame", "gas leak", "explosion"]):
            services.add("fire")
            severity = max(severity, 7)
        if any(w in text_lower for w in ["blood", "hurt", "pain", "ambulance", "medical", "dying", 
                                          "heart", "breath", "injured", "accident", "broken", "unconscious"]):
            services.add("hospital")
            severity = max(severity, 7)
        if any(w in text_lower for w in ["gun", "shoot", "knife", "stab", "attack", "rob", "robbery",
                                          "assault", "murder", "kill", "kidnap", "threat", "weapon",
                                          "steal", "thief", "fight", "stalking", "following"]):
            services.add("police")
            severity = max(severity, 8)
        
        # Emergency keywords boost
        emergency_words = ["help", "fire", "gun", "shoot", "kill", "blood", 
                           "ambulance", "dying", "attack", "kidnap", "emergency",
                           "trapped", "stuck", "please", "save"]
        is_emergency = any(word in text_lower for word in emergency_words)
        
        if is_emergency and not services:
            services = {"hospital", "police", "fire"}
            severity = max(severity, 6)
        
        # Intent detection
        intent = "general"
        if any(w in text_lower for w in ["fire", "burning", "smoke"]):
            intent = "fire"
        elif any(w in text_lower for w in ["blood", "hurt", "pain", "ambulance", "medical"]):
            intent = "medical"
        elif any(w in text_lower for w in ["gun", "shoot", "knife", "attack", "assault"]):
            intent = "assault"
        elif any(w in text_lower for w in ["kidnap", "taken", "hostage"]):
            intent = "kidnap"
        elif any(w in text_lower for w in ["accident", "crash", "collision"]):
            intent = "accident"
        elif any(w in text_lower for w in ["help", "scared", "danger"]):
            intent = "panic"
        
        summary = text[:200] + ("..." if len(text) > 200 else "")
        
        return {
            "is_emergency": is_emergency,
            "severity": severity,
            "intent": intent,
            "services_needed": list(services),
            "summary": summary,
            "recommended_action": "EMERGENCY_DISPATCH" if severity >= 7 else "ESCALATE" if severity >= 5 else "MONITOR",
            "victim_count": 0,
            "situation_details": f"Detected intent: {intent}"
        }
