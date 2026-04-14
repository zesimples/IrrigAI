"""Unit conversion utilities."""


def mm_to_liters(mm: float, area_ha: float) -> float:
    """Convert mm of water over an area (ha) to total liters."""
    return mm * area_ha * 10_000 / 1_000  # 1mm over 1m² = 1L


def liters_to_mm(liters: float, area_ha: float) -> float:
    """Convert total liters over an area (ha) to mm."""
    return liters * 1_000 / (area_ha * 10_000)


def runtime_hours(irrigation_mm: float, application_rate_mm_h: float) -> float:
    """Compute irrigation runtime in hours given depth and application rate."""
    if application_rate_mm_h <= 0:
        raise ValueError("Application rate must be > 0")
    return irrigation_mm / application_rate_mm_h


def drip_application_rate(
    emitter_flow_l_h: float,
    emitter_spacing_m: float,
    row_spacing_m: float,
) -> float:
    """Compute drip application rate in mm/h.

    application_rate = (emitter_flow / emitter_spacing) / row_spacing
    """
    if emitter_spacing_m <= 0 or row_spacing_m <= 0:
        raise ValueError("Spacing values must be > 0")
    return (emitter_flow_l_h / emitter_spacing_m) / row_spacing_m
