from enum import Enum


class CropType(str, Enum):
    """Built-in crop types. Additional types can be added via CropProfileTemplate in DB."""

    OLIVE = "olive"
    ALMOND = "almond"
    MAIZE = "maize"
    VINEYARD = "vineyard"


class IrrigationSystemType(str, Enum):
    DRIP = "drip"
    CENTER_PIVOT = "center_pivot"
    SPRINKLER = "sprinkler"
    FLOOD = "flood"


class SoilTexture(str, Enum):
    CLAY = "clay"
    CLAY_LOAM = "clay_loam"
    LOAM = "loam"
    SANDY_LOAM = "sandy_loam"
    SAND = "sand"
    CUSTOM = "custom"  # User enters their own FC/PWP values


class RecommendationAction(str, Enum):
    IRRIGATE = "irrigate"
    SKIP = "skip"
    REDUCE = "reduce"
    INCREASE = "increase"
    DEFER = "defer"


class ConfidenceLevel(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class AlertSeverity(str, Enum):
    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"


class AlertType(str, Enum):
    WATER_STRESS = "water_stress"
    OVER_IRRIGATION = "over_irrigation"
    PROBE_ANOMALY = "probe_anomaly"
    DEEP_DRAINAGE = "deep_drainage"
    RAIN_SKIP = "rain_skip"
    UNDERPERFORMANCE = "underperformance"
    LOW_CONFIDENCE = "low_confidence"
    MISSING_DATA = "missing_data"
    STALE_PROBE = "stale_probe"
    STALE_WEATHER = "stale_weather"


class OverrideType(str, Enum):
    FIXED_DEPTH = "fixed_depth"
    FIXED_RUNTIME = "fixed_runtime"
    SKIP = "skip"
    FORCE_IRRIGATE = "force_irrigate"


class OverrideStrategy(str, Enum):
    ONE_TIME = "one_time"
    UNTIL_NEXT_STAGE = "until_next_stage"


class UserRole(str, Enum):
    GROWER = "grower"
    FARM_MANAGER = "farm_manager"
    AGRONOMIST = "agronomist"
    ADMIN = "admin"


class ProbeHealthStatus(str, Enum):
    OK = "ok"
    WARNING = "warning"
    ERROR = "error"
    OFFLINE = "offline"


class IrrigationStrategy(str, Enum):
    FULL_ETC = "full_etc"
    RDI = "rdi"
    DEFICIT = "deficit"
    CUSTOM = "custom"
