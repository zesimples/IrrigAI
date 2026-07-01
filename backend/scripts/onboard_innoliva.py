"""Idempotent onboarding of the Innoliva client (6 polos, 77 olive sectors).

Reads docs/innoliva_device_mapping.csv and creates the entity tree, encrypted
per-farm credentials, and ProbeDepth rows (from each device's live sensor list).
Re-runnable: get-or-create by natural key. See
docs/superpowers/specs/2026-07-01-innoliva-onboarding-design.md.
"""
from __future__ import annotations

import re

# Polo → (MyIrrigation project_id, iMetos weather_device_id | None)
POLO_META: dict[str, tuple[str, str | None]] = {
    "Conceição": ("170", None),   # no iMetos → forecast-only
    "Covadonga": ("167", "574"),
    "Fátima": ("168", "590"),
    "Guadalupe": ("171", "571"),
    "Rocio": ("554", "573"),
    "Carmo": ("169", "572"),
}

_VARIETIES = ("Arbequina", "Cobrançosa", "Picoal")


def parse_variety(sector_name: str) -> str | None:
    """Return the olive variety named in the sector, else None."""
    for v in _VARIETIES:
        if v.lower() in sector_name.lower():
            return v
    return None


def extract_soil_moisture_depths(raw: dict) -> list[int]:
    """Sorted unique depths (cm) of exact 'Soil Moisture' sensors (not 'Summed')."""
    data = raw.get("data", raw) if isinstance(raw, dict) else {}
    sensors = data.get("sensors", []) if isinstance(data, dict) else []
    depths: set[int] = set()
    for s in sensors:
        if str(s.get("sensor_type", "")).strip().lower() != "soil moisture":
            continue
        m = re.search(r"(\d+)\s*cm", str(s.get("name", "")), re.IGNORECASE)
        if m:
            depths.add(int(m.group(1)))
    return sorted(depths)
