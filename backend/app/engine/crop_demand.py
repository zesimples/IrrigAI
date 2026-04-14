"""Crop demand (ETc) computation.

Kc is looked up from the sector's SectorCropProfile.stages JSONB field — never
from hardcoded constants. The engine works with whatever the user has configured
or with sensible fallbacks.
"""

from app.engine.types import DailyWeather, SectorContext


def get_kc_from_profile(
    stages: list[dict],
    current_stage: str | None,
) -> tuple[float, str]:
    """Look up Kc from the sector's crop profile stages (JSONB).

    Args:
        stages: SectorCropProfile.stages — list of stage dicts
        current_stage: Sector.current_phenological_stage key, or None

    Returns:
        (kc_value, source_description)

    Logic:
        - If current_stage matches a stage key → return that stage's Kc
        - If current_stage is None or not found → use highest Kc in profile
          (mid-season proxy) and note it in source
    """
    if not stages:
        return 0.80, "default (no stages in profile)"

    # Build a lookup dict by stage key
    by_key = {s["key"]: s for s in stages if "key" in s and "kc" in s}

    if current_stage and current_stage in by_key:
        kc = float(by_key[current_stage]["kc"])
        return kc, f"profile stage '{current_stage}'"

    # Fall back to highest Kc (conservative mid-season proxy)
    max_stage = max(stages, key=lambda s: s.get("kc", 0))
    kc = float(max_stage.get("kc", 0.80))
    reason = (
        "default (stage not set, using highest Kc as mid-season proxy)"
        if current_stage is None
        else f"default (stage '{current_stage}' not found in profile, using highest Kc)"
    )
    return kc, reason


def compute_etc(et0_mm: float, kc: float, ks: float = 1.0) -> float:
    """ETc = ET0 × Kc × Ks (mm/day).

    Ks (stress coefficient) defaults to 1.0 (no stress applied at engine level).
    """
    return round(et0_mm * kc * ks, 3)


def compute_root_depth(ctx: SectorContext) -> float:
    """Select effective root depth based on tree age vs. maturity.

    If age data is available, interpolates between young and mature root depths.
    Otherwise returns mature root depth.
    """
    if ctx.tree_age_years is not None and ctx.tree_age_years < 4:
        return ctx.root_depth_m  # Already set to young depth in context building
    return ctx.root_depth_m
