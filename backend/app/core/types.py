"""Domain type aliases for readability and future flexibility."""

from typing import Annotated

from pydantic import Field

# Physical units
Millimeters = float          # mm — water depth
CubicMetersPerCubicMeter = float  # m³/m³ — volumetric water content
Meters = float               # m — root depth, spacing
Hectares = float             # ha — area
LitersPerHour = float        # L/h — emitter flow
MillimetersPerHour = float   # mm/h — application rate
DegreeCelsius = float        # °C
MegajoulesPerSquareMeter = float  # MJ/m² — solar radiation
MetersPerSecond = float      # m/s — wind speed
Percent = float              # 0–100

# Domain identifiers
FarmId = int
PlotId = int
SectorId = int
ProbeId = int
UserId = int

# Confidence score: 0.0–1.0
ConfidenceScore = Annotated[float, Field(ge=0.0, le=1.0)]
