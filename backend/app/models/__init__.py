# Import all models so Alembic can detect them for autogenerate migrations.
# Order matters for FK resolution — import FK targets before dependent models.

from app.models.crop_profile_template import CropProfileTemplate
from app.models.soil_preset import SoilPreset
from app.models.user import User
from app.models.farm import Farm
from app.models.farm_credentials import FarmCredentials
from app.models.plot import Plot
from app.models.sector import Sector
from app.models.sector_crop_profile import SectorCropProfile
from app.models.irrigation_system import IrrigationSystem
from app.models.probe import Probe
from app.models.probe_depth import ProbeDepth
from app.models.probe_reading import ProbeReading
from app.models.weather_observation import WeatherObservation
from app.models.weather_forecast import WeatherForecast
from app.models.recommendation import Recommendation
from app.models.recommendation_reason import RecommendationReason
from app.models.irrigation_event import IrrigationEvent
from app.models.alert import Alert
from app.models.audit_log import AuditLog
from app.models.sector_override import SectorOverride

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
]
