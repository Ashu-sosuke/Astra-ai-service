from pydantic import BaseModel, HttpUrl, Field, validator
from typing import Optional, List, Dict, Any
from enum import Enum

class RecommendedAction(str, Enum):
    MONITOR = "MONITOR"
    NOTIFY = "NOTIFY"
    ESCALATE = "ESCALATE"
    EMERGENCY_DISPATCH = "EMERGENCY_DISPATCH"

class IncidentInput(BaseModel):
    incidentId: str = Field(..., description="Unique ID of the incident")
    audioUrl: str = Field(..., description="Signed URL to the audio file")
    latitude: Optional[float] = Field(None, ge=-90, le=90)
    longitude: Optional[float] = Field(None, ge=-180, le=180)
    timestamp: int = Field(..., description="Unix timestamp")
    
    @validator('audioUrl')
    def validate_url(cls, v):
        if not v.startswith(('http://', 'https://')):
            raise ValueError('audioUrl must be a valid HTTP/HTTPS URL')
        return v

class IncidentOutput(BaseModel):
    incident_id: str = Field(..., alias="incidentId")
    transcript: str
    stress_score: float = Field(..., alias="stressScore")
    threat_type: str = Field(..., alias="threatType")
    severity_score: float = Field(..., alias="severityScore")
    final_severity: str = Field(..., alias="finalSeverity")
    confidence: float
    recommended_action: RecommendedAction = Field(..., alias="recommendedAction")
    is_override_triggered: bool = False
    model_version: str = "v3.0.0"
    summary: Optional[str] = Field(None, description="AI generated summary")
    is_emergency: Optional[bool] = Field(None, description="AI emergency flag")
    intent: Optional[str] = Field(None, description="AI intent classification")
    services_needed: Optional[List[str]] = Field(None, description="Services that should respond")
    secondary_threats: Optional[List[str]] = Field(None, description="Secondary threat types")
    situation_details: Optional[str] = Field(None, description="Situation description")
    victim_count: Optional[int] = Field(None, description="Estimated victim count")
    details: Optional[Dict[str, Any]] = None
    latitude: Optional[float] = Field(None, description="Incident Latitude")
    longitude: Optional[float] = Field(None, description="Incident Longitude")
    timestamp: Optional[int] = Field(None, description="Incident Unix Timestamp")

    model_config = {
        "populate_by_name": True
    }
