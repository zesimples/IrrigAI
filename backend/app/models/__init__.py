# Import all models so Alembic can detect them for autogenerate migrations.
# Order matters for FK resolution — import FK targets before dependent models.

from app.models.ai_response_feedback import AIResponseFeedback
from app.models.alert import Alert
from app.models.audit_log import AuditLog
from app.models.chat_conversation import ChatConversation
from app.models.chat_message import ChatMessage
from app.models.crop_profile_template import CropProfileTemplate
from app.models.detected_water_event import DetectedWaterEvent
from app.models.farm import Farm
from app.models.farm_credentials import FarmCredentials
from app.models.field_observation import FieldObservation
from app.models.flowmeter import Flowmeter
from app.models.flowmeter_reading import FlowmeterReading
from app.models.flowmeter_reference import FlowmeterReference
from app.models.irrigation_event import IrrigationEvent
from app.models.irrigation_event_detected import IrrigationEventDetected
from app.models.irrigation_fingerprint import IrrigationFingerprint
from app.models.irrigation_system import IrrigationSystem
from app.models.plot import Plot
from app.models.probe import Probe
from app.models.probe_calibration import ProbeCalibration
from app.models.probe_calibration_run import ProbeCalibrationRun
from app.models.probe_depth import ProbeDepth
from app.models.probe_reading import ProbeReading
from app.models.provider_ingestion_run import ProviderIngestionRun
from app.models.provider_sync_log import ProviderSyncLog
from app.models.recommendation import Recommendation
from app.models.recommendation_outcome import RecommendationOutcome
from app.models.recommendation_reason import RecommendationReason
from app.models.sector import Sector
from app.models.sector_crop_profile import SectorCropProfile
from app.models.sector_override import SectorOverride
from app.models.soil_preset import SoilPreset
from app.models.user import User
from app.models.weather_forecast import WeatherForecast
from app.models.weather_observation import WeatherObservation

__all__ = [
    "CropProfileTemplate",
    "SoilPreset",
    "User",
    "Farm",
    "FarmCredentials",
    "Plot",
    "Sector",
    "SectorCropProfile",
    "IrrigationSystem",
    "Probe",
    "ProbeDepth",
    "ProbeReading",
    "WeatherObservation",
    "WeatherForecast",
    "Recommendation",
    "RecommendationReason",
    "IrrigationEvent",
    "Alert",
    "AuditLog",
    "SectorOverride",
    "ProviderSyncLog",
    "ProviderIngestionRun",
    "DetectedWaterEvent",
    "Flowmeter",
    "FlowmeterReading",
    "IrrigationEventDetected",
    "FlowmeterReference",
    "ProbeCalibration",
    "ProbeCalibrationRun",
    "IrrigationFingerprint",
    "RecommendationOutcome",
    "FieldObservation",
    "ChatConversation",
    "ChatMessage",
    "AIResponseFeedback",
]
