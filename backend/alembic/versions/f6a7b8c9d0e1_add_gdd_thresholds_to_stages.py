"""add GDD thresholds to crop profile template and sector crop profile stages

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-04-20

Adds gdd_min, gdd_max, tbase_c to each stage dict inside the JSONB stages
column of crop_profile_template (and non-customised sector_crop_profile copies).
This is a pure data migration — no schema change.
"""
import json
from alembic import op
from sqlalchemy import text

revision = 'f6a7b8c9d0e1'
down_revision = 'e5f6a7b8c9d0'
branch_labels = None
depends_on = None

# GDD thresholds per stage key
_GDD = {
    # Olive (Tbase 10°C, reference Feb 1)
    "olive_dormancy":        {"gdd_min": 0,    "gdd_max": 150,  "tbase_c": 10},
    "olive_bud_break":       {"gdd_min": 150,  "gdd_max": 400,  "tbase_c": 10},
    "olive_flowering":       {"gdd_min": 400,  "gdd_max": 600,  "tbase_c": 10},
    "olive_fruit_set":       {"gdd_min": 600,  "gdd_max": 900,  "tbase_c": 10},
    "olive_pit_hardening":   {"gdd_min": 900,  "gdd_max": 1400, "tbase_c": 10},
    "olive_oil_accumulation":{"gdd_min": 1400, "gdd_max": 2200, "tbase_c": 10},
    "olive_veraison":        {"gdd_min": 2200, "gdd_max": 2600, "tbase_c": 10},
    "olive_harvest":         {"gdd_min": 2600, "gdd_max": 3000, "tbase_c": 10},
    # Almond (Tbase 7°C, reference Feb 1)
    "almond_dormancy":       {"gdd_min": 0,    "gdd_max": 100,  "tbase_c": 7},
    "almond_bloom":          {"gdd_min": 100,  "gdd_max": 300,  "tbase_c": 7},
    "almond_fruit_set":      {"gdd_min": 300,  "gdd_max": 600,  "tbase_c": 7},
    "almond_shell_expansion":{"gdd_min": 600,  "gdd_max": 1100, "tbase_c": 7},
    "almond_kernel_fill":    {"gdd_min": 1100, "gdd_max": 1800, "tbase_c": 7},
    "almond_hull_split":     {"gdd_min": 1800, "gdd_max": 2200, "tbase_c": 7},
    "almond_post_harvest":   {"gdd_min": 2200, "gdd_max": 2600, "tbase_c": 7},
    # Maize (Tbase 10°C, reference sowing_date)
    "maize_emergence":       {"gdd_min": 0,    "gdd_max": 200,  "tbase_c": 10},
    "maize_vegetative":      {"gdd_min": 200,  "gdd_max": 700,  "tbase_c": 10},
    "maize_tasseling":       {"gdd_min": 700,  "gdd_max": 1000, "tbase_c": 10},
    "maize_grain_fill":      {"gdd_min": 1000, "gdd_max": 1500, "tbase_c": 10},
    "maize_maturation":      {"gdd_min": 1500, "gdd_max": 2000, "tbase_c": 10},
}


def _add_gdd_to_stages(stages: list) -> list:
    updated = []
    for stage in stages:
        key = stage.get("key", "")
        new_stage = dict(stage)
        gdd = _GDD.get(key)
        if gdd:
            new_stage.update(gdd)
        else:
            # Vineyard stages and unknown keys — add null GDD fields
            new_stage.setdefault("gdd_min", None)
            new_stage.setdefault("gdd_max", None)
            new_stage.setdefault("tbase_c", None)
        updated.append(new_stage)
    return updated


def upgrade() -> None:
    conn = op.get_bind()

    # --- Update crop_profile_template ---
    templates = conn.execute(
        text("SELECT id, stages FROM crop_profile_template WHERE is_system_default = true")
    ).fetchall()

    for row in templates:
        template_id, stages = row
        if isinstance(stages, str):
            stages = json.loads(stages)
        updated = _add_gdd_to_stages(stages)
        conn.execute(
            text("UPDATE crop_profile_template SET stages = :stages WHERE id = :id"),
            {"stages": json.dumps(updated), "id": template_id},
        )

    # --- Update sector_crop_profile (non-customized copies only) ---
    profiles = conn.execute(
        text("SELECT id, stages FROM sector_crop_profile WHERE is_customized = false")
    ).fetchall()

    for row in profiles:
        profile_id, stages = row
        if isinstance(stages, str):
            stages = json.loads(stages)
        updated = _add_gdd_to_stages(stages)
        conn.execute(
            text("UPDATE sector_crop_profile SET stages = :stages WHERE id = :id"),
            {"stages": json.dumps(updated), "id": profile_id},
        )


def downgrade() -> None:
    conn = op.get_bind()

    def _remove_gdd(stages: list) -> list:
        return [
            {k: v for k, v in s.items() if k not in ("gdd_min", "gdd_max", "tbase_c")}
            for s in stages
        ]

    for table in ("crop_profile_template", "sector_crop_profile"):
        rows = conn.execute(text(f"SELECT id, stages FROM {table}")).fetchall()
        for row in rows:
            rid, stages = row
            if isinstance(stages, str):
                stages = json.loads(stages)
            cleaned = _remove_gdd(stages)
            conn.execute(
                text(f"UPDATE {table} SET stages = :stages WHERE id = :id"),
                {"stages": json.dumps(cleaned), "id": rid},
            )
