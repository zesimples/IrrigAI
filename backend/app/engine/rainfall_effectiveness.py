"""Dynamic rainfall effectiveness calculation.

Effective rainfall depends on both the rainfall amount (intensity proxy) and
soil texture (infiltration rate). Heavy rain on clay runs off; light rain on
any soil is fully absorbed.

The sector-level `rainfall_effectiveness` factor is applied ON TOP as a user
correction for local conditions (slope, surface cover, micro-climate).
"""

# Effectiveness factor by (intensity_bucket, soil_texture)
# intensity buckets: "light" < 5mm, "moderate" 5–15mm, "heavy" 15–30mm, "very_heavy" > 30mm

_TABLE: dict[str, dict[str, float]] = {
    "light": {
        "clay":       1.00,
        "clay_loam":  1.00,
        "loam":       1.00,
        "sandy_loam": 1.00,
        "sand":       1.00,
        "custom":     1.00,
    },
    "moderate": {
        "clay":       0.65,
        "clay_loam":  0.75,
        "loam":       0.85,
        "sandy_loam": 0.92,
        "sand":       0.95,
        "custom":     0.80,
    },
    "heavy": {
        "clay":       0.50,
        "clay_loam":  0.60,
        "loam":       0.75,
        "sandy_loam": 0.85,
        "sand":       0.90,
        "custom":     0.70,
    },
    "very_heavy": {
        "clay":       0.35,
        "clay_loam":  0.45,
        "loam":       0.60,
        "sandy_loam": 0.75,
        "sand":       0.80,
        "custom":     0.55,
    },
}

_DEFAULT_TEXTURE = "loam"  # used when soil texture is unknown


def _intensity_bucket(rainfall_mm: float) -> str:
    if rainfall_mm < 5.0:
        return "light"
    elif rainfall_mm < 15.0:
        return "moderate"
    elif rainfall_mm < 30.0:
        return "heavy"
    else:
        return "very_heavy"


def dynamic_effectiveness(rainfall_mm: float, soil_texture: str | None) -> float:
    """Return the fraction of rainfall_mm that is effective for irrigation scheduling.

    Args:
        rainfall_mm: Daily rainfall total (mm).
        soil_texture: Soil texture class (clay, clay_loam, loam, sandy_loam, sand, custom).

    Returns:
        Effectiveness factor in [0.35, 1.0].
    """
    if rainfall_mm <= 0.0:
        return 1.0  # no rain, factor irrelevant

    bucket = _intensity_bucket(rainfall_mm)
    texture = soil_texture if soil_texture in _TABLE["light"] else _DEFAULT_TEXTURE
    return _TABLE[bucket][texture]


def compute_effective_rainfall(
    rainfall_mm: float,
    soil_texture: str | None,
    user_correction: float = 1.0,
) -> tuple[float, str]:
    """Compute effective rainfall and return a log note.

    Args:
        rainfall_mm: Daily rainfall (mm).
        soil_texture: Soil texture class.
        user_correction: Sector-level user multiplier (slope, cover, etc.). Default 1.0.

    Returns:
        (effective_mm, log_note)
    """
    if rainfall_mm <= 0.0:
        return 0.0, "No rainfall"

    factor = dynamic_effectiveness(rainfall_mm, soil_texture)
    effective = rainfall_mm * factor * user_correction
    texture_label = soil_texture or "unknown (assumed loam)"
    note = (
        f"Rainfall {rainfall_mm:.1f}mm × effectiveness {factor:.0%} "
        f"(texture={texture_label}, intensity={_intensity_bucket(rainfall_mm)})"
    )
    if user_correction != 1.0:
        note += f" × user correction {user_correction:.2f}"
    note += f" = {effective:.1f}mm effective"

    return round(effective, 2), note
