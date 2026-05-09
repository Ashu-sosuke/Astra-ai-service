import math
from config import config

class FusionEngine:
    @staticmethod
    def compute_severity(stress_score: float, threat_data: dict, keyword_score: float = 0.0, 
                         location_risk: float = 0.0, groq_severity: int = None) -> dict:
        """
        Computes the final severity score using Fusion Engine v3.0.
        
        Features:
        - Exponential Stress Scaling: Low stress dampened, high stress amplified
        - Confidence-Weighted Threat Score with secondary threat boost
        - Groq AI Severity Integration: Uses the LLM's 1-10 severity rating
        - Emergency Overrides: Immediate CRITICAL for high-confidence severe threats
        - Multi-service routing awareness
        """
        
        # 1. Exponential Stress Scaling
        scaled_stress = math.pow(stress_score, 2)
        
        # 2. Threat Severity Mapping
        THREAT_SEVERITY_MAP = {
            "ASSAULT": 1.0,
            "KIDNAP": 1.0,
            "FIRE": 0.9,
            "ACCIDENT": 0.85,
            "PANIC": 0.8,
            "MEDICAL": 0.85,
            "FALSE_ALARM": 0.0,
            "UNKNOWN": 0.3
        }
        
        threat_type = threat_data.get("threat_type", "UNKNOWN")
        threat_confidence = threat_data.get("confidence", 0.0)
        secondary_threats = threat_data.get("secondary_threats", [])
        base_threat_score = THREAT_SEVERITY_MAP.get(threat_type, 0.3)
        
        # 3. Confidence-Weighted Threat Score
        weighted_threat_score = (base_threat_score * threat_confidence) + (0.3 * (1 - threat_confidence))
        
        # Boost for secondary threats (multi-service emergencies are more severe)
        if secondary_threats:
            secondary_boost = min(0.15, len(secondary_threats) * 0.08)
            weighted_threat_score = min(1.0, weighted_threat_score + secondary_boost)
        
        # 4. Groq AI Severity Integration (normalized to 0-1)
        groq_score = 0.0
        if groq_severity is not None:
            groq_score = max(0.0, min(1.0, groq_severity / 10.0))
        
        # 5. Weighted Fusion Calculation
        # v3.0: Increased threat weight, added groq_score, reduced stress dependency
        if groq_severity is not None:
            # When we have Groq analysis, use it heavily (it's the smartest signal)
            final_score = (
                (0.15 * scaled_stress) +         # Audio stress (15%)
                (0.25 * weighted_threat_score) +  # Threat classification (25%)
                (0.35 * groq_score) +             # Groq AI severity (35%) — highest weight
                (0.15 * keyword_score) +          # Keyword matching (15%)
                (0.10 * location_risk)            # Historical crime data (10%)
            )
        else:
            # Fallback weights without Groq
            final_score = (
                (config.WEIGHT_STRESS * scaled_stress) +
                (config.WEIGHT_THREAT * weighted_threat_score) +
                (config.WEIGHT_KEYWORD * keyword_score) + 
                (config.WEIGHT_LOCATION * location_risk)
            )
        
        # 6. Critical Overrides
        is_override = False
        
        # High-confidence ASSAULT/KIDNAP → force CRITICAL
        if threat_type in ["ASSAULT", "KIDNAP"] and threat_confidence >= 0.8:
            final_score = max(final_score, 0.95)
            is_override = True
        
        # Groq says severity >= 9 with high confidence → force CRITICAL
        if groq_severity is not None and groq_severity >= 9 and threat_confidence >= 0.7:
            final_score = max(final_score, 0.90)
            is_override = True
        
        # Multi-service + high groq severity → boost
        if len(secondary_threats) >= 1 and groq_severity is not None and groq_severity >= 7:
            final_score = max(final_score, 0.70)
        
        # Clamp result
        final_score = min(max(final_score, 0.0), 1.0)
        
        # 7. Determine Severity Level & Action
        if final_score >= 0.85:
            severity = "CRITICAL"
            action = "EMERGENCY_DISPATCH"
        elif final_score >= 0.65:
            severity = "HIGH"
            action = "EMERGENCY_DISPATCH"
        elif final_score >= 0.45:
            severity = "MEDIUM"
            action = "ESCALATE"
        elif final_score >= 0.25:
            severity = "LOW"
            action = "NOTIFY"
        else:
            severity = "MINIMAL"
            action = "MONITOR"
            
        return {
            "final_score": round(final_score, 2),
            "severity_level": severity,
            "recommended_action": action,
            "is_override_triggered": is_override,
            "breakdown": {
                "raw_stress": stress_score,
                "scaled_stress_contribution": round(0.15 * scaled_stress if groq_severity else config.WEIGHT_STRESS * scaled_stress, 3),
                "threat_contribution": round(0.25 * weighted_threat_score if groq_severity else config.WEIGHT_THREAT * weighted_threat_score, 3),
                "groq_severity_contribution": round(0.35 * groq_score, 3) if groq_severity else 0,
                "keyword_contribution": round(0.15 * keyword_score if groq_severity else config.WEIGHT_KEYWORD * keyword_score, 3),
                "location_contribution": round(0.10 * location_risk if groq_severity else config.WEIGHT_LOCATION * location_risk, 3),
                "secondary_threats": secondary_threats,
                "groq_severity_raw": groq_severity
            }
        }
