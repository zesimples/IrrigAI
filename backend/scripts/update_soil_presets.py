"""Update soil preset values to Alentejo-calibrated table.

Run inside the backend container:
    python scripts/update_soil_presets.py

Idempotent: UPDATEs existing presets and INSERTs missing ones.
Does NOT delete any preset to preserve existing crop-profile FK references.

New presets added:
    loamy_sand, silty_loam, silt, sandy_clay_loam,
    silty_clay_loam, silty_clay, sandy_clay

Updated presets (old → new values):
    sand          FC 0.12→0.07  WP 0.05→0.03  TAW  70→ 40
    sandy_loam    FC 0.18→0.16  WP 0.08→0.07  TAW 100→ 90
    loam          FC 0.24→0.25  WP 0.10→0.12  TAW 140→130
    clay          FC 0.36→0.42  WP 0.20→0.30  TAW 160→120
    clay_loam     FC 0.28→0.30  WP 0.14→0.15  TAW 140→150  (name unchanged)
"""
import asyncio
import uuid

from sqlalchemy import select
from app.database import AsyncSessionLocal
from app.models import SoilPreset

# Alentejo-calibrated values (% vol / 100 = m³/m³)
PRESETS = [
    {"name_pt": "Areia",                "name_en": "Sand",              "texture": "sand",              "field_capacity": 0.07, "wilting_point": 0.03, "taw_mm_per_m":  40.0},
    {"name_pt": "Areia-franca",         "name_en": "Loamy Sand",        "texture": "loamy_sand",        "field_capacity": 0.10, "wilting_point": 0.04, "taw_mm_per_m":  60.0},
    {"name_pt": "Franco-arenoso",       "name_en": "Sandy Loam",        "texture": "sandy_loam",        "field_capacity": 0.16, "wilting_point": 0.07, "taw_mm_per_m":  90.0},
    {"name_pt": "Franco",               "name_en": "Loam",              "texture": "loam",              "field_capacity": 0.25, "wilting_point": 0.12, "taw_mm_per_m": 130.0},
    {"name_pt": "Franco-limoso",        "name_en": "Silty Loam",        "texture": "silty_loam",        "field_capacity": 0.31, "wilting_point": 0.13, "taw_mm_per_m": 180.0},
    {"name_pt": "Limo",                 "name_en": "Silt",              "texture": "silt",              "field_capacity": 0.30, "wilting_point": 0.05, "taw_mm_per_m": 250.0},
    {"name_pt": "Franco-argilo-arenoso","name_en": "Sandy Clay Loam",   "texture": "sandy_clay_loam",   "field_capacity": 0.27, "wilting_point": 0.17, "taw_mm_per_m": 100.0},
    {"name_pt": "Franco-argiloso",      "name_en": "Clay Loam",         "texture": "clay_loam",         "field_capacity": 0.30, "wilting_point": 0.15, "taw_mm_per_m": 150.0},
    {"name_pt": "Franco-argilo-limoso", "name_en": "Silty Clay Loam",   "texture": "silty_clay_loam",   "field_capacity": 0.37, "wilting_point": 0.21, "taw_mm_per_m": 160.0},
    {"name_pt": "Argilo-limoso",        "name_en": "Silty Clay",        "texture": "silty_clay",        "field_capacity": 0.42, "wilting_point": 0.28, "taw_mm_per_m": 140.0},
    {"name_pt": "Argila",               "name_en": "Clay",              "texture": "clay",              "field_capacity": 0.42, "wilting_point": 0.30, "taw_mm_per_m": 120.0},
    {"name_pt": "Argilo-arenoso",       "name_en": "Sandy Clay",        "texture": "sandy_clay",        "field_capacity": 0.36, "wilting_point": 0.26, "taw_mm_per_m": 100.0},
]


async def main() -> None:
    async with AsyncSessionLocal() as db:
        updated = 0
        inserted = 0

        for p in PRESETS:
            result = await db.execute(
                select(SoilPreset).where(
                    SoilPreset.texture == p["texture"],
                    SoilPreset.is_system_default.is_(True),
                )
            )
            existing = result.scalar_one_or_none()

            if existing:
                existing.name_pt = p["name_pt"]
                existing.name_en = p["name_en"]
                existing.field_capacity = p["field_capacity"]
                existing.wilting_point = p["wilting_point"]
                existing.taw_mm_per_m = p["taw_mm_per_m"]
                updated += 1
                print(
                    f"  [update] {p['texture']:20s}  "
                    f"FC={p['field_capacity']:.2f}  WP={p['wilting_point']:.2f}  "
                    f"TAW={p['taw_mm_per_m']:.0f}"
                )
            else:
                obj = SoilPreset(
                    id=str(uuid.uuid4()),
                    is_system_default=True,
                    **p,
                )
                db.add(obj)
                inserted += 1
                print(
                    f"  [insert] {p['texture']:20s}  "
                    f"FC={p['field_capacity']:.2f}  WP={p['wilting_point']:.2f}  "
                    f"TAW={p['taw_mm_per_m']:.0f}"
                )

        await db.commit()
        print(f"\nDone. Updated={updated}  Inserted={inserted}")


asyncio.run(main())
