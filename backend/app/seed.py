"""Seed script for IrrigAI.

Usage: python -m app.seed

Populates:
  A) System templates (crop profiles, soil presets) — always, idempotent
  B) Farm "Herdade do Esporão" — 7 olive sectors + vineyard sectors

Safe to re-run: clears existing farm data first, never touches system
templates that already exist.

PROBE MAPPING — ESPORÃO OLIVAL (project 1044)
---------------------------------------------
All confirmed via MyIrrigation API (/data/devices) + serial number verification.
Watermark WM200SS sensors, measuring soil suction (cBar) at 40cm and 60cm.
Weather station: iMetos Esporão (device 1583).

  Talhão | Variety     | WM   | Device ID | Serial
  -------|-------------|------|-----------|----------
  T01    | Cobrançosa  | WM01 | 4663      | 0390C362
  T04    | Cobrançosa  | WM06 | 4664      | 0390CE99
  T05    | Cobrançosa  | WM02 | 4662      | 0390C35B
  T07    | Cobrançosa  | WM03 | 4661      | 0390C35A
  T10    | Cobrançosa  | WM04 | 4666      | 0390CE9D
  T17    | Arbequina   | WM07 | 4665      | 0390CE9A
  T18    | Arbequina   | WM05 | 4667      | 0390CEA3

PROBE MAPPING — ESPORÃO VINHA (project 604)
-------------------------------------------
Device IDs to be confirmed. Update the PROBE_VINHA_* constants below.
"""

# ---------------------------------------------------------------------------
# MyIrrigation probe external_id values: "{project_id}/{device_id}"
# ---------------------------------------------------------------------------
# Olival — Cobrançosa sectors (all confirmed)
PROBE_T01_COBR = "1044/4663"   # WM01 serial 0390C362
PROBE_T04_COBR = "1044/4664"   # WM06 serial 0390CE99
PROBE_T05_COBR = "1044/4662"   # WM02 serial 0390C35B
PROBE_T07_COBR = "1044/4661"   # WM03 serial 0390C35A
PROBE_T10_COBR = "1044/4666"   # WM04 serial 0390CE9D
# Olival — Arbequina sectors (all confirmed)
PROBE_T17_ARB  = "1044/4665"   # WM07 serial 0390CE9A
PROBE_T18_ARB  = "1044/4667"   # WM05 serial 0390CEA3

# Vinha — Esporão Vinha (project 604) — confirmed 2026-04-14
# TDT/capacitance probes reporting VWC (vol%) at multiple depths
PROBE_T15B_MISTURA   = "604/1865"  # T15B Mistura Tinta TA 80   — depths 20/40/60/80/100cm
PROBE_T18_ARAGONEZ   = "604/1875"  # T18 Aragonez TC 02          — depths 20/40/60/80/100cm
PROBE_T23B_TFRANCA   = "604/1867"  # T23B Touriga Franca TA 05   — depths 20/40/60/80cm
PROBE_T25_TRINCA     = "604/1869"  # T25 Trincadeira TA 74       — depths 20/40/60/80/100cm
PROBE_T27A_SYRAH     = "604/1874"  # T27A Syrah TA 98            — depths 20/40/60/80/100cm
PROBE_T37_PMAUSENG   = "604/5634"  # T37 Petit Manseng BB 07     — model device, no VWC sensors
PROBE_T58_VIOGNIER   = "604/1866"  # T58 Viognier BB 08          — depths 20/40/60/80/100cm
PROBE_T63_CAMPO      = "604/1881"  # T63 Campo Ampelográfico TA 10 — depths 20/40/60/80/100cm
PROBE_T76_TFRANCA    = "604/1880"  # T76 Touriga Franca TA 15    — depths 20/40/60/80/100cm
PROBE_T84_ALFROCH    = "604/5809"  # T84 Alfrocheiro             — depths 20/40/60/80cm

# ---------------------------------------------------------------------------
# Conqueiros — Amendoal (project 959) — Watermark WM200SS, cBar
# ---------------------------------------------------------------------------
PROBE_CONQ_S02  = "959/4914"   # Turno 1 (S02) — almond
PROBE_CONQ_S03  = "959/4915"   # Turno 1 (S03) — almond
PROBE_CONQ_S10  = "959/4913"   # Turno 2 (S10) — almond
PROBE_CONQ_S12  = "959/4912"   # Turno 2 (S12) — almond
PROBE_CONQ_S19  = "959/8404"   # Turno 3 (S19) Amendoal Novo — almond
PROBE_CONQ_S25  = "959/7044"   # Turno 4 (S25) Amendoal Novo — almond

# ---------------------------------------------------------------------------
# Conqueiros — Olival (project 1597) — Watermark WM200SS, cBar
# ---------------------------------------------------------------------------
PROBE_CONQ_O01A = "1597/3634"  # Turno 1 (S01) — olive
PROBE_CONQ_O01B = "1597/7674"  # Turno 1 (S02) — olive
PROBE_CONQ_O01C = "1597/7673"  # Turno 1 (S03) — olive
PROBE_CONQ_O02  = "1597/3891"  # Turno 2 (S08) — olive
PROBE_CONQ_O03  = "1597/3633"  # Turno 3 (S12) — olive
PROBE_CONQ_O04  = "1597/3629"  # Turno 4 (S15) — olive
PROBE_CONQ_O05  = "1597/3832"  # Turno 5 (S20) — olive

import copy
import math
import random
import uuid
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import create_engine, delete, select, text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import (
    CropProfileTemplate,
    Farm,
    IrrigationEvent,
    IrrigationSystem,
    Plot,
    Probe,
    ProbeDepth,
    ProbeReading,
    Recommendation,
    RecommendationReason,
    Sector,
    SectorCropProfile,
    SoilPreset,
    User,
)

settings = get_settings()

# ---------------------------------------------------------------------------
# Crop profile template data (from project brief)
# ---------------------------------------------------------------------------

OLIVE_STAGES = [
    {"key": "olive_dormancy", "name_pt": "Dormência", "name_en": "Dormancy",
     "typical_months": [12, 1, 2], "kc": 0.40, "water_sensitivity": "low",
     "root_depth_m": 0.70, "rdi_eligible": False, "rdi_factor": None},
    {"key": "olive_bud_break", "name_pt": "Abrolhamento", "name_en": "Bud break",
     "typical_months": [3, 4], "kc": 0.45, "water_sensitivity": "medium",
     "root_depth_m": 0.75, "rdi_eligible": False, "rdi_factor": None},
    {"key": "olive_flowering", "name_pt": "Floração", "name_en": "Flowering",
     "typical_months": [5], "kc": 0.50, "water_sensitivity": "high",
     "root_depth_m": 0.80, "rdi_eligible": False, "rdi_factor": None},
    {"key": "olive_fruit_set", "name_pt": "Vingamento", "name_en": "Fruit set",
     "typical_months": [6], "kc": 0.55, "water_sensitivity": "high",
     "root_depth_m": 0.85, "rdi_eligible": False, "rdi_factor": None},
    {"key": "olive_pit_hardening", "name_pt": "Endurecimento do caroço", "name_en": "Pit hardening",
     "typical_months": [7], "kc": 0.50, "water_sensitivity": "low",
     "root_depth_m": 0.90, "rdi_eligible": True, "rdi_factor": 0.40},
    {"key": "olive_oil_accumulation", "name_pt": "Acumulação de azeite", "name_en": "Oil accumulation",
     "typical_months": [8, 9], "kc": 0.60, "water_sensitivity": "medium_high",
     "root_depth_m": 1.00, "rdi_eligible": False, "rdi_factor": None},
    {"key": "olive_veraison", "name_pt": "Pintor", "name_en": "Veraison",
     "typical_months": [10], "kc": 0.55, "water_sensitivity": "medium",
     "root_depth_m": 0.95, "rdi_eligible": False, "rdi_factor": None},
    {"key": "olive_harvest", "name_pt": "Colheita", "name_en": "Harvest",
     "typical_months": [10, 11], "kc": 0.50, "water_sensitivity": "low",
     "root_depth_m": 0.90, "rdi_eligible": False, "rdi_factor": None},
]

ALMOND_STAGES = [
    {"key": "almond_dormancy", "name_pt": "Dormência", "name_en": "Dormancy",
     "typical_months": [12, 1], "kc": 0.30, "water_sensitivity": "none",
     "root_depth_m": 0.60, "rdi_eligible": False, "rdi_factor": None},
    {"key": "almond_bloom", "name_pt": "Floração", "name_en": "Bloom",
     "typical_months": [2, 3], "kc": 0.40, "water_sensitivity": "high",
     "root_depth_m": 0.65, "rdi_eligible": False, "rdi_factor": None},
    {"key": "almond_fruit_set", "name_pt": "Vingamento", "name_en": "Fruit set",
     "typical_months": [3, 4], "kc": 0.55, "water_sensitivity": "high",
     "root_depth_m": 0.75, "rdi_eligible": False, "rdi_factor": None},
    {"key": "almond_shell_expansion", "name_pt": "Expansão da casca", "name_en": "Shell expansion",
     "typical_months": [5, 6], "kc": 0.80, "water_sensitivity": "high",
     "root_depth_m": 0.90, "rdi_eligible": False, "rdi_factor": None},
    {"key": "almond_kernel_fill", "name_pt": "Enchimento do miolo", "name_en": "Kernel fill",
     "typical_months": [7, 8], "kc": 0.90, "water_sensitivity": "critical",
     "root_depth_m": 1.00, "rdi_eligible": False, "rdi_factor": None},
    {"key": "almond_hull_split", "name_pt": "Abertura do pericarpo", "name_en": "Hull split",
     "typical_months": [8, 9], "kc": 0.65, "water_sensitivity": "medium",
     "root_depth_m": 1.00, "rdi_eligible": False, "rdi_factor": None},
    {"key": "almond_post_harvest", "name_pt": "Pós-colheita", "name_en": "Post-harvest",
     "typical_months": [10, 11], "kc": 0.50, "water_sensitivity": "low",
     "root_depth_m": 0.90, "rdi_eligible": True, "rdi_factor": 0.50},
]

MAIZE_STAGES = [
    {"key": "maize_emergence", "name_pt": "Emergência–V6", "name_en": "Emergence–V6",
     "typical_months": [], "dap_start": 0, "dap_end": 30,
     "kc": 0.40, "water_sensitivity": "low_medium",
     "root_depth_m": 0.20, "rdi_eligible": False, "rdi_factor": None},
    {"key": "maize_vegetative", "name_pt": "V6–VT (crescimento)", "name_en": "V6–VT (growth)",
     "typical_months": [], "dap_start": 30, "dap_end": 60,
     "kc": 0.80, "water_sensitivity": "medium",
     "root_depth_m": 0.50, "rdi_eligible": False, "rdi_factor": None},
    {"key": "maize_tasseling", "name_pt": "VT–R1 (pendoamento)", "name_en": "VT–R1 (tasseling)",
     "typical_months": [], "dap_start": 60, "dap_end": 75,
     "kc": 1.20, "water_sensitivity": "critical",
     "root_depth_m": 0.80, "rdi_eligible": False, "rdi_factor": None},
    {"key": "maize_grain_fill", "name_pt": "R1–R3 (enchimento)", "name_en": "R1–R3 (grain fill)",
     "typical_months": [], "dap_start": 75, "dap_end": 100,
     "kc": 1.15, "water_sensitivity": "critical",
     "root_depth_m": 1.00, "rdi_eligible": False, "rdi_factor": None},
    {"key": "maize_maturation", "name_pt": "R4–R6 (maturação)", "name_en": "R4–R6 (maturation)",
     "typical_months": [], "dap_start": 100, "dap_end": 140,
     "kc": 0.60, "water_sensitivity": "low",
     "root_depth_m": 1.00, "rdi_eligible": False, "rdi_factor": None},
]

VINEYARD_STAGES = [
    {"key": "vine_dormancy", "name_pt": "Dormência", "name_en": "Dormancy",
     "typical_months": [12, 1, 2], "kc": 0.30, "water_sensitivity": "none",
     "root_depth_m": 0.50, "rdi_eligible": False, "rdi_factor": None},
    {"key": "vine_bleeding", "name_pt": "Choro", "name_en": "Bleeding",
     "typical_months": [2, 3], "kc": 0.30, "water_sensitivity": "low",
     "root_depth_m": 0.50, "rdi_eligible": False, "rdi_factor": None},
    {"key": "vine_budbreak", "name_pt": "Abrolhamento", "name_en": "Bud break",
     "typical_months": [3, 4], "kc": 0.35, "water_sensitivity": "low",
     "root_depth_m": 0.55, "rdi_eligible": False, "rdi_factor": None},
    {"key": "vine_shoot_growth", "name_pt": "Crescimento do lançamento", "name_en": "Shoot growth",
     "typical_months": [4, 5], "kc": 0.50, "water_sensitivity": "medium",
     "root_depth_m": 0.60, "rdi_eligible": False, "rdi_factor": None},
    {"key": "vine_flowering", "name_pt": "Floração", "name_en": "Flowering",
     "typical_months": [5, 6], "kc": 0.55, "water_sensitivity": "high",
     "root_depth_m": 0.65, "rdi_eligible": False, "rdi_factor": None},
    {"key": "vine_fruit_set", "name_pt": "Vingamento", "name_en": "Fruit set",
     "typical_months": [6], "kc": 0.65, "water_sensitivity": "critical",
     "root_depth_m": 0.70, "rdi_eligible": False, "rdi_factor": None},
    {"key": "vine_berry_growth", "name_pt": "Crescimento da baga", "name_en": "Berry growth",
     "typical_months": [7], "kc": 0.70, "water_sensitivity": "high",
     "root_depth_m": 0.80, "rdi_eligible": False, "rdi_factor": None},
    {"key": "vine_veraison", "name_pt": "Pintor (Maturação)", "name_en": "Veraison",
     "typical_months": [8], "kc": 0.65, "water_sensitivity": "medium",
     "root_depth_m": 0.85, "rdi_eligible": True, "rdi_factor": 0.50},
    {"key": "vine_ripening", "name_pt": "Maturação", "name_en": "Ripening",
     "typical_months": [8, 9], "kc": 0.55, "water_sensitivity": "medium",
     "root_depth_m": 0.90, "rdi_eligible": True, "rdi_factor": 0.60},
    {"key": "vine_harvest", "name_pt": "Colheita", "name_en": "Harvest",
     "typical_months": [9, 10], "kc": 0.45, "water_sensitivity": "low",
     "root_depth_m": 0.85, "rdi_eligible": False, "rdi_factor": None},
    {"key": "vine_post_harvest", "name_pt": "Pós-colheita", "name_en": "Post-harvest",
     "typical_months": [10, 11], "kc": 0.30, "water_sensitivity": "none",
     "root_depth_m": 0.70, "rdi_eligible": False, "rdi_factor": None},
]

CROP_TEMPLATES = [
    {
        "crop_type": "olive",
        "name_pt": "Olival",
        "name_en": "Olive",
        "mad": 0.65,
        "root_depth_mature_m": 1.0,
        "root_depth_young_m": 0.4,
        "maturity_age_years": 6,
        "stages": OLIVE_STAGES,
    },
    {
        "crop_type": "almond",
        "name_pt": "Amendoal",
        "name_en": "Almond",
        "mad": 0.55,
        "root_depth_mature_m": 1.2,
        "root_depth_young_m": 0.5,
        "maturity_age_years": 5,
        "stages": ALMOND_STAGES,
    },
    {
        "crop_type": "maize",
        "name_pt": "Milho",
        "name_en": "Maize",
        "mad": 0.50,
        "root_depth_mature_m": 1.0,
        "root_depth_young_m": 1.0,
        "maturity_age_years": None,
        "stages": MAIZE_STAGES,
    },
    {
        "crop_type": "vineyard",
        "name_pt": "Vinha",
        "name_en": "Vineyard",
        "mad": 0.50,
        "root_depth_mature_m": 0.90,
        "root_depth_young_m": 0.40,
        "maturity_age_years": 4,
        "stages": VINEYARD_STAGES,
    },
]

SOIL_PRESETS = [
    {"name_pt": "Argila", "name_en": "Clay",
     "texture": "clay", "field_capacity": 0.36, "wilting_point": 0.20, "taw_mm_per_m": 160.0},
    {"name_pt": "Franco-argiloso", "name_en": "Clay-loam",
     "texture": "clay_loam", "field_capacity": 0.28, "wilting_point": 0.14, "taw_mm_per_m": 140.0},
    {"name_pt": "Franco", "name_en": "Loam",
     "texture": "loam", "field_capacity": 0.24, "wilting_point": 0.10, "taw_mm_per_m": 140.0},
    {"name_pt": "Franco-arenoso", "name_en": "Sandy-loam",
     "texture": "sandy_loam", "field_capacity": 0.18, "wilting_point": 0.08, "taw_mm_per_m": 100.0},
    {"name_pt": "Arenoso", "name_en": "Sand",
     "texture": "sand", "field_capacity": 0.12, "wilting_point": 0.05, "taw_mm_per_m": 70.0},
]


# ---------------------------------------------------------------------------
# Probe reading generator
# ---------------------------------------------------------------------------

def _generate_readings(
    probe_depth_id: str,
    depth_cm: int,
    fc: float,
    pwp: float,
    days: int = 7,
    end_time: datetime | None = None,
) -> list[dict]:
    """Generate realistic hourly soil moisture readings for a probe depth.

    Pattern: FC after irrigation event, slowly depleting due to ETc and drainage.
    Deeper depths respond more slowly and stay wetter.
    """
    if end_time is None:
        end_time = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)

    depth_factor = 1.0 - (depth_cm / 200.0)  # shallower = drier faster
    start_swc = pwp + (fc - pwp) * (0.65 + depth_factor * 0.20)  # start ~65-85% of TAW
    swc = start_swc

    readings = []
    for h in range(days * 24, 0, -1):
        ts = end_time - timedelta(hours=h)

        # Diurnal ETc signal (peaks mid-day)
        hour_of_day = ts.hour
        diurnal = 0.4 + 0.6 * math.sin(math.pi * hour_of_day / 24)
        hourly_etc_m3m3 = (0.006 / 24) * diurnal * depth_factor  # ~6mm/day mid-canopy

        # Occasional irrigation boost (every ~3 days, at 06:00)
        if h % 72 == 6:
            swc = min(fc, swc + (fc - pwp) * 0.60)

        swc = max(pwp + 0.01, swc - hourly_etc_m3m3)
        # Add small noise
        noise = random.gauss(0, 0.002)
        raw = round(max(pwp, min(fc, swc + noise)), 4)
        calibrated = round(raw * 1.0, 4)  # calibration_factor=1.0, offset=0.0

        readings.append({
            "id": str(uuid.uuid4()),
            "probe_depth_id": probe_depth_id,
            "timestamp": ts,
            "raw_value": raw,
            "calibrated_value": calibrated,
            "unit": "vwc_m3m3",
            "quality_flag": "ok",
        })

    return readings


# ---------------------------------------------------------------------------
# Main seed function
# ---------------------------------------------------------------------------

def seed(engine) -> None:
    print("=== IrrigAI Seed Script ===")

    with Session(engine) as session:
        # ----------------------------------------------------------------
        # A) System templates
        # ----------------------------------------------------------------
        print("\n[1/2] Seeding system templates...")

        # Crop profile templates — upsert by crop_type (system defaults only)
        for tmpl in CROP_TEMPLATES:
            existing = session.execute(
                select(CropProfileTemplate).where(
                    CropProfileTemplate.crop_type == tmpl["crop_type"],
                    CropProfileTemplate.is_system_default.is_(True),
                )
            ).scalar_one_or_none()

            if existing:
                print(f"  [skip] CropProfileTemplate '{tmpl['crop_type']}' already exists")
            else:
                obj = CropProfileTemplate(
                    id=str(uuid.uuid4()),
                    is_system_default=True,
                    **tmpl,
                )
                session.add(obj)
                print(f"  [+] CropProfileTemplate '{tmpl['crop_type']}'")

        # Soil presets — upsert by texture
        for preset in SOIL_PRESETS:
            existing = session.execute(
                select(SoilPreset).where(
                    SoilPreset.texture == preset["texture"],
                    SoilPreset.is_system_default.is_(True),
                )
            ).scalar_one_or_none()

            if existing:
                print(f"  [skip] SoilPreset '{preset['texture']}' already exists")
            else:
                obj = SoilPreset(
                    id=str(uuid.uuid4()),
                    is_system_default=True,
                    **preset,
                )
                session.add(obj)
                print(f"  [+] SoilPreset '{preset['texture']}'")

        session.flush()

        # ----------------------------------------------------------------
        # B) Sample farm — clear existing data first
        # ----------------------------------------------------------------
        print("\n[2/2] Seeding sample farm 'Herdade do Esporão'...")

        # Clear existing farm data (identified by farm name)
        existing_farm = session.execute(
            select(Farm).where(Farm.name == "Herdade do Esporão")
        ).scalar_one_or_none()

        if existing_farm:
            print("  Clearing existing demo data...")
            # Cascade deletes handle most, but probe_reading needs explicit clearing
            # because it has no cascade path from Farm
            sector_ids = [
                row[0] for row in session.execute(
                    text("""
                        SELECT s.id FROM sector s
                        JOIN plot p ON s.plot_id = p.id
                        WHERE p.farm_id = :farm_id
                    """),
                    {"farm_id": existing_farm.id},
                ).fetchall()
            ]
            if sector_ids:
                probe_ids = [
                    row[0] for row in session.execute(
                        text("SELECT id FROM probe WHERE sector_id = ANY(:ids)"),
                        {"ids": sector_ids},
                    ).fetchall()
                ]
                if probe_ids:
                    depth_ids = [
                        row[0] for row in session.execute(
                            text("SELECT id FROM probe_depth WHERE probe_id = ANY(:ids)"),
                            {"ids": probe_ids},
                        ).fetchall()
                    ]
                    if depth_ids:
                        session.execute(
                            text("DELETE FROM probe_reading WHERE probe_depth_id = ANY(:ids)"),
                            {"ids": depth_ids},
                        )

            session.delete(existing_farm)
            session.flush()
            print("  Existing demo data cleared.")

        # Users
        grower = session.execute(
            select(User).where(User.email == "joao.silva@demo.irrigai.pt")
        ).scalar_one_or_none()
        if not grower:
            grower = User(
                id=str(uuid.uuid4()),
                email="joao.silva@demo.irrigai.pt",
                name="João Silva",
                role="grower",
                language="pt",
                hashed_password="$2b$12$demo_hash_grower",  # not real — demo only
            )
            session.add(grower)

        agronomist = session.execute(
            select(User).where(User.email == "ana.ferreira@demo.irrigai.pt")
        ).scalar_one_or_none()
        if not agronomist:
            agronomist = User(
                id=str(uuid.uuid4()),
                email="ana.ferreira@demo.irrigai.pt",
                name="Dr. Ana Ferreira",
                role="agronomist",
                language="pt",
                hashed_password="$2b$12$demo_hash_agro",
            )
            session.add(agronomist)

        session.flush()

        # Farm
        farm = Farm(
            id=str(uuid.uuid4()),
            name="Herdade do Esporão",
            location_lat=38.42,
            location_lon=-7.54,
            region="Alentejo",
            timezone="Europe/Lisbon",
            owner_id=grower.id,
            myirrigation_username="esporao_api",
            myirrigation_password="esporao_api",
            myirrigation_client_id="7JTTP4XGVZ9S1M7PEABD",
            myirrigation_client_secret="PKVSK5BPNNYE4JE2KOQ2",
            myirrigation_weather_device_id="1583",
        )
        session.add(farm)
        session.flush()

        # Soil preset — clay loam for Alentejo olive groves
        clay_loam = session.execute(
            select(SoilPreset).where(SoilPreset.texture == "clay_loam")
        ).scalar_one()

        # Olive crop template
        olive_tmpl = session.execute(
            select(CropProfileTemplate).where(
                CropProfileTemplate.crop_type == "olive",
                CropProfileTemplate.is_system_default.is_(True),
            )
        ).scalar_one()

        # Vineyard crop template
        vineyard_tmpl = session.execute(
            select(CropProfileTemplate).where(
                CropProfileTemplate.crop_type == "vineyard",
                CropProfileTemplate.is_system_default.is_(True),
            )
        ).scalar_one()

        # Sandy-loam soil preset for vineyard (typical Alentejo vinha soils)
        sandy_loam = session.execute(
            select(SoilPreset).where(SoilPreset.texture == "sandy_loam")
        ).scalar_one()

        # Three plots: Cobrançosa block + Arbequina block + Vinha block
        plot_cobr = Plot(
            id=str(uuid.uuid4()),
            farm_id=farm.id,
            name="Olival Cobrançosa",
            area_ha=65.0,   # T01+T04+T05+T07+T10 combined
            soil_texture=clay_loam.texture,
            field_capacity=clay_loam.field_capacity,
            wilting_point=clay_loam.wilting_point,
            stone_content_pct=5.0,
            soil_preset_id=clay_loam.id,
        )
        plot_arb = Plot(
            id=str(uuid.uuid4()),
            farm_id=farm.id,
            name="Olival Arbequina",
            area_ha=30.0,   # T17+T18 combined
            soil_texture=clay_loam.texture,
            field_capacity=clay_loam.field_capacity,
            wilting_point=clay_loam.wilting_point,
            stone_content_pct=5.0,
            soil_preset_id=clay_loam.id,
        )
        plot_vinha = Plot(
            id=str(uuid.uuid4()),
            farm_id=farm.id,
            name="Vinha",
            area_ha=40.0,
            soil_texture=sandy_loam.texture,
            field_capacity=sandy_loam.field_capacity,
            wilting_point=sandy_loam.wilting_point,
            stone_content_pct=10.0,
            soil_preset_id=sandy_loam.id,
        )
        session.add_all([plot_cobr, plot_arb, plot_vinha])
        session.flush()

        # Drip system spec — shared across all sectors (adjust per-sector if needed)
        _DRIP_COBR  = {"system_type": "drip", "emitter_flow_lph": 4.0,
                       "emitter_spacing_m": 0.5, "lines_per_row": 1,
                       "efficiency": 0.90, "max_runtime_hours": 8.0}
        _DRIP_ARB   = {"system_type": "drip", "emitter_flow_lph": 1.6,
                       "emitter_spacing_m": 0.75, "lines_per_row": 1,
                       "efficiency": 0.90, "max_runtime_hours": 6.0}
        _DRIP_VINHA = {"system_type": "drip", "emitter_flow_lph": 2.3,
                       "emitter_spacing_m": 0.5, "lines_per_row": 1,
                       "efficiency": 0.92, "max_runtime_hours": 6.0}

        # Olive sectors — confirmed mapping from MyIrrigation API + Esporão agronomist
        # Vineyard sectors — project 604 (ESPORÃO VINHA); device IDs to be filled in
        sectors_data = [
            # ── Cobrançosa (traditional spacing, planted ~2008) ───────────────
            {
                "plot_id": plot_cobr.id,
                "name": "T01 - Cobrançosa",
                "area_ha": 13.0,
                "crop_type": "olive",
                "variety": "Cobrançosa",
                "planting_year": 2008,
                "tree_spacing_m": 7.0,
                "row_spacing_m": 7.0,
                "trees_per_ha": 204,
                "current_phenological_stage": "olive_oil_accumulation",
                "irrigation_strategy": "full_etc",
                "template": olive_tmpl,
                "irrig_system": _DRIP_COBR,
                "probe_external_id": PROBE_T01_COBR,
            },
            {
                "plot_id": plot_cobr.id,
                "name": "T04 - Cobrançosa",
                "area_ha": 13.0,
                "crop_type": "olive",
                "variety": "Cobrançosa",
                "planting_year": 2008,
                "tree_spacing_m": 7.0,
                "row_spacing_m": 7.0,
                "trees_per_ha": 204,
                "current_phenological_stage": "olive_oil_accumulation",
                "irrigation_strategy": "full_etc",
                "template": olive_tmpl,
                "irrig_system": _DRIP_COBR,
                "probe_external_id": PROBE_T04_COBR,
            },
            {
                "plot_id": plot_cobr.id,
                "name": "T05 - Cobrançosa",
                "area_ha": 13.0,
                "crop_type": "olive",
                "variety": "Cobrançosa",
                "planting_year": 2008,
                "tree_spacing_m": 7.0,
                "row_spacing_m": 7.0,
                "trees_per_ha": 204,
                "current_phenological_stage": "olive_oil_accumulation",
                "irrigation_strategy": "full_etc",
                "template": olive_tmpl,
                "irrig_system": _DRIP_COBR,
                "probe_external_id": PROBE_T05_COBR,
            },
            {
                "plot_id": plot_cobr.id,
                "name": "T07 - Cobrançosa",
                "area_ha": 13.0,
                "crop_type": "olive",
                "variety": "Cobrançosa",
                "planting_year": 2008,
                "tree_spacing_m": 7.0,
                "row_spacing_m": 7.0,
                "trees_per_ha": 204,
                "current_phenological_stage": "olive_oil_accumulation",
                "irrigation_strategy": "full_etc",
                "template": olive_tmpl,
                "irrig_system": _DRIP_COBR,
                "probe_external_id": PROBE_T07_COBR,
            },
            {
                "plot_id": plot_cobr.id,
                "name": "T10 - Cobrançosa",
                "area_ha": 13.0,
                "crop_type": "olive",
                "variety": "Cobrançosa",
                "planting_year": 2008,
                "tree_spacing_m": 7.0,
                "row_spacing_m": 7.0,
                "trees_per_ha": 204,
                "current_phenological_stage": "olive_oil_accumulation",
                "irrigation_strategy": "full_etc",
                "template": olive_tmpl,
                "irrig_system": _DRIP_COBR,
                "probe_external_id": PROBE_T10_COBR,
            },
            # ── Arbequina (super-high-density, planted ~2010) ─────────────────
            {
                "plot_id": plot_arb.id,
                "name": "T17 - Arbequina",
                "area_ha": 15.0,
                "crop_type": "olive",
                "variety": "Arbequina",
                "planting_year": 2010,
                "tree_spacing_m": 1.5,
                "row_spacing_m": 3.75,
                "trees_per_ha": 1778,
                "current_phenological_stage": "olive_oil_accumulation",
                "irrigation_strategy": "full_etc",
                "template": olive_tmpl,
                "irrig_system": _DRIP_ARB,
                "probe_external_id": PROBE_T17_ARB,
            },
            {
                "plot_id": plot_arb.id,
                "name": "T18 - Arbequina",
                "area_ha": 15.0,
                "crop_type": "olive",
                "variety": "Arbequina",
                "planting_year": 2010,
                "tree_spacing_m": 1.5,
                "row_spacing_m": 3.75,
                "trees_per_ha": 1778,
                "current_phenological_stage": "olive_oil_accumulation",
                "irrigation_strategy": "full_etc",
                "template": olive_tmpl,
                "irrig_system": _DRIP_ARB,
                "probe_external_id": PROBE_T18_ARB,
            },
            # ── Vinha (project 604 — ESPORÃO VINHA) ──────────────────────────
            # TDT/capacitance probes, VWC at multiple depths (20–100 cm)
            {
                "plot_id": plot_vinha.id,
                "name": "T15B - Mistura Tinta",
                "area_ha": 5.0,
                "crop_type": "vineyard",
                "variety": "Mistura Tinta",
                "planting_year": 2003,
                "tree_spacing_m": 1.0,
                "row_spacing_m": 2.5,
                "trees_per_ha": 4000,
                "current_phenological_stage": "vine_shoot_growth",
                "irrigation_strategy": "rdi",
                "template": vineyard_tmpl,
                "irrig_system": _DRIP_VINHA,
                "probe_external_id": PROBE_T15B_MISTURA,
                "probe_depths": [20, 40, 60, 80, 100],
            },
            {
                "plot_id": plot_vinha.id,
                "name": "T18 - Aragonez",
                "area_ha": 5.0,
                "crop_type": "vineyard",
                "variety": "Aragonez",
                "planting_year": 2003,
                "tree_spacing_m": 1.0,
                "row_spacing_m": 2.5,
                "trees_per_ha": 4000,
                "current_phenological_stage": "vine_shoot_growth",
                "irrigation_strategy": "rdi",
                "template": vineyard_tmpl,
                "irrig_system": _DRIP_VINHA,
                "probe_external_id": PROBE_T18_ARAGONEZ,
                "probe_depths": [20, 40, 60, 80, 100],
            },
            {
                "plot_id": plot_vinha.id,
                "name": "T23B - Touriga Franca",
                "area_ha": 4.0,
                "crop_type": "vineyard",
                "variety": "Touriga Franca",
                "planting_year": 2003,
                "tree_spacing_m": 1.0,
                "row_spacing_m": 2.5,
                "trees_per_ha": 4000,
                "current_phenological_stage": "vine_shoot_growth",
                "irrigation_strategy": "rdi",
                "template": vineyard_tmpl,
                "irrig_system": _DRIP_VINHA,
                "probe_external_id": PROBE_T23B_TFRANCA,
                "probe_depths": [20, 40, 60, 80],
            },
            {
                "plot_id": plot_vinha.id,
                "name": "T25 - Trincadeira",
                "area_ha": 5.0,
                "crop_type": "vineyard",
                "variety": "Trincadeira",
                "planting_year": 2003,
                "tree_spacing_m": 1.0,
                "row_spacing_m": 2.5,
                "trees_per_ha": 4000,
                "current_phenological_stage": "vine_shoot_growth",
                "irrigation_strategy": "rdi",
                "template": vineyard_tmpl,
                "irrig_system": _DRIP_VINHA,
                "probe_external_id": PROBE_T25_TRINCA,
                "probe_depths": [20, 40, 60, 80, 100],
            },
            {
                "plot_id": plot_vinha.id,
                "name": "T27A - Syrah",
                "area_ha": 4.0,
                "crop_type": "vineyard",
                "variety": "Syrah",
                "planting_year": 2003,
                "tree_spacing_m": 1.0,
                "row_spacing_m": 2.5,
                "trees_per_ha": 4000,
                "current_phenological_stage": "vine_shoot_growth",
                "irrigation_strategy": "rdi",
                "template": vineyard_tmpl,
                "irrig_system": _DRIP_VINHA,
                "probe_external_id": PROBE_T27A_SYRAH,
                "probe_depths": [20, 40, 60, 80, 100],
            },
            {
                "plot_id": plot_vinha.id,
                "name": "T37 - Petit Manseng",
                "area_ha": 3.0,
                "crop_type": "vineyard",
                "variety": "Petit Manseng",
                "planting_year": 2005,
                "tree_spacing_m": 1.0,
                "row_spacing_m": 2.5,
                "trees_per_ha": 4000,
                "current_phenological_stage": "vine_shoot_growth",
                "irrigation_strategy": "rdi",
                "template": vineyard_tmpl,
                "irrig_system": _DRIP_VINHA,
                "probe_external_id": PROBE_T37_PMAUSENG,
                "probe_depths": [],  # model device — no physical VWC sensors
            },
            {
                "plot_id": plot_vinha.id,
                "name": "T58 - Viognier",
                "area_ha": 3.0,
                "crop_type": "vineyard",
                "variety": "Viognier",
                "planting_year": 2005,
                "tree_spacing_m": 1.0,
                "row_spacing_m": 2.5,
                "trees_per_ha": 4000,
                "current_phenological_stage": "vine_shoot_growth",
                "irrigation_strategy": "rdi",
                "template": vineyard_tmpl,
                "irrig_system": _DRIP_VINHA,
                "probe_external_id": PROBE_T58_VIOGNIER,
                "probe_depths": [20, 40, 60, 80, 100],
            },
            {
                "plot_id": plot_vinha.id,
                "name": "T63 - Campo Ampelográfico",
                "area_ha": 3.0,
                "crop_type": "vineyard",
                "variety": "Campo Ampelográfico",
                "planting_year": 2005,
                "tree_spacing_m": 1.0,
                "row_spacing_m": 2.5,
                "trees_per_ha": 4000,
                "current_phenological_stage": "vine_shoot_growth",
                "irrigation_strategy": "rdi",
                "template": vineyard_tmpl,
                "irrig_system": _DRIP_VINHA,
                "probe_external_id": PROBE_T63_CAMPO,
                "probe_depths": [20, 40, 60, 80, 100],
            },
            {
                "plot_id": plot_vinha.id,
                "name": "T76 - Touriga Franca",
                "area_ha": 4.0,
                "crop_type": "vineyard",
                "variety": "Touriga Franca",
                "planting_year": 2003,
                "tree_spacing_m": 1.0,
                "row_spacing_m": 2.5,
                "trees_per_ha": 4000,
                "current_phenological_stage": "vine_shoot_growth",
                "irrigation_strategy": "rdi",
                "template": vineyard_tmpl,
                "irrig_system": _DRIP_VINHA,
                "probe_external_id": PROBE_T76_TFRANCA,
                "probe_depths": [20, 40, 60, 80, 100],
            },
            {
                "plot_id": plot_vinha.id,
                "name": "T84 - Alfrocheiro",
                "area_ha": 4.0,
                "crop_type": "vineyard",
                "variety": "Alfrocheiro",
                "planting_year": 2003,
                "tree_spacing_m": 1.0,
                "row_spacing_m": 2.5,
                "trees_per_ha": 4000,
                "current_phenological_stage": "vine_shoot_growth",
                "irrigation_strategy": "rdi",
                "template": vineyard_tmpl,
                "irrig_system": _DRIP_VINHA,
                "probe_external_id": PROBE_T84_ALFROCH,
                "probe_depths": [20, 40, 60, 80],
            },
        ]

        now = datetime.now(UTC)

        for sd in sectors_data:
            tmpl = sd.pop("template")
            irrig_data = sd.pop("irrig_system")
            probe_ext_id = sd.pop("probe_external_id")
            depth_levels = sd.pop("probe_depths", [40, 60])

            sector = Sector(id=str(uuid.uuid4()), **sd)
            session.add(sector)
            session.flush()

            # SectorCropProfile — copy from template
            scp = SectorCropProfile(
                id=str(uuid.uuid4()),
                sector_id=sector.id,
                source_template_id=tmpl.id,
                crop_type=tmpl.crop_type,
                mad=tmpl.mad,
                root_depth_mature_m=tmpl.root_depth_mature_m,
                root_depth_young_m=tmpl.root_depth_young_m,
                maturity_age_years=tmpl.maturity_age_years,
                stages=copy.deepcopy(tmpl.stages),
                is_customized=False,
            )
            session.add(scp)

            # IrrigationSystem
            irrig_sys = IrrigationSystem(
                id=str(uuid.uuid4()),
                sector_id=sector.id,
                **irrig_data,
            )
            session.add(irrig_sys)

            # Probe — real data fetched from MyIrrigation ingestion
            is_vineyard = sd.get("crop_type") == "vineyard"
            probe = Probe(
                id=str(uuid.uuid4()),
                sector_id=sector.id,
                external_id=probe_ext_id,
                manufacturer="Pessl Instruments",
                model="TDT Soil Moisture" if is_vineyard else "Watermark WM200SS",
                install_date=date(2023, 3, 15),
                health_status="ok",
                last_reading_at=None,
                is_reference=True,
            )
            session.add(probe)
            session.flush()

            # ProbeDepth records — depths and sensor type differ by probe model.
            # Vineyard TDT probes report vol% (0–100); calibration_factor=0.01
            # converts to m³/m³ (0–1) expected by the quality checker and engine.
            sensor_type = "soil_moisture" if is_vineyard else "soil_tension"
            cal_factor  = 0.01 if is_vineyard else 1.0
            for depth_cm in depth_levels:
                pd = ProbeDepth(
                    id=str(uuid.uuid4()),
                    probe_id=probe.id,
                    depth_cm=depth_cm,
                    sensor_type=sensor_type,
                    calibration_offset=0.0,
                    calibration_factor=cal_factor,
                )
                session.add(pd)

            print(f"  [+] Sector '{sector.name}' | probe={probe_ext_id} | stage={sector.current_phenological_stage}")

        session.flush()
        print("  [+] Probe structure created — real readings will be fetched from MyIrrigation on first ingestion")

        print("  [~] Weather data: skipped — real data will be fetched from MyIrrigation on first ingestion")

        # Irrigation events — 3 historical events across sectors
        print("  [+] Inserting 3 irrigation events...")
        all_sectors = session.execute(
            select(Sector).where(Sector.plot_id.in_([plot_cobr.id, plot_arb.id, plot_vinha.id]))
        ).scalars().all()
        sector_by_name = {s.name: s for s in all_sectors}

        for sector_name, days_ago, duration_min, applied_mm in [
            ("T01 - Cobrançosa", 6, 180, 18.0),
            ("T01 - Cobrançosa", 3, 180, 18.0),
            ("T17 - Arbequina", 4, 240, 22.0),
        ]:
            s = sector_by_name[sector_name]
            start = now - timedelta(days=days_ago, hours=2)
            end = start + timedelta(minutes=duration_min)
            evt = IrrigationEvent(
                id=str(uuid.uuid4()),
                sector_id=s.id,
                start_time=start,
                end_time=end,
                duration_minutes=float(duration_min),
                applied_mm=applied_mm,
                source="manual_log",
            )
            session.add(evt)

        session.commit()

    # ----------------------------------------------------------------
    # C) Sample farm — Herdade dos Conqueiros
    # ----------------------------------------------------------------
    print("\n[3/3] Seeding sample farm 'Herdade dos Conqueiros'...")
    with Session(engine) as session:
        existing_conq = session.execute(
            select(Farm).where(Farm.name == "Herdade dos Conqueiros")
        ).scalar_one_or_none()

        if existing_conq:
            print("  Clearing existing Conqueiros data...")
            sector_ids = [
                row[0] for row in session.execute(
                    text("""
                        SELECT s.id FROM sector s
                        JOIN plot p ON s.plot_id = p.id
                        WHERE p.farm_id = :farm_id
                    """),
                    {"farm_id": existing_conq.id},
                ).fetchall()
            ]
            if sector_ids:
                probe_ids = [
                    row[0] for row in session.execute(
                        text("SELECT id FROM probe WHERE sector_id = ANY(:ids)"),
                        {"ids": sector_ids},
                    ).fetchall()
                ]
                if probe_ids:
                    depth_ids = [
                        row[0] for row in session.execute(
                            text("SELECT id FROM probe_depth WHERE probe_id = ANY(:ids)"),
                            {"ids": probe_ids},
                        ).fetchall()
                    ]
                    if depth_ids:
                        session.execute(
                            text("DELETE FROM probe_reading WHERE probe_depth_id = ANY(:ids)"),
                            {"ids": depth_ids},
                        )
            session.delete(existing_conq)
            session.flush()
            print("  Existing Conqueiros data cleared.")

        # Reuse same owner/agronomist as Esporão
        grower = session.execute(
            select(User).where(User.email == "joao.silva@demo.irrigai.pt")
        ).scalar_one()

        # Almond and olive templates
        almond_tmpl = session.execute(
            select(CropProfileTemplate).where(
                CropProfileTemplate.crop_type == "almond",
                CropProfileTemplate.is_system_default.is_(True),
            )
        ).scalar_one()
        olive_tmpl = session.execute(
            select(CropProfileTemplate).where(
                CropProfileTemplate.crop_type == "olive",
                CropProfileTemplate.is_system_default.is_(True),
            )
        ).scalar_one()

        # Sandy-clay-loam soil for Conqueiros
        sandy_clay_loam = session.execute(
            select(SoilPreset).where(SoilPreset.texture == "sandy_clay_loam")
        ).scalar_one_or_none()
        clay_loam = session.execute(
            select(SoilPreset).where(SoilPreset.texture == "clay_loam")
        ).scalar_one()
        soil = sandy_clay_loam or clay_loam

        farm_conq = Farm(
            id=str(uuid.uuid4()),
            name="Herdade dos Conqueiros",
            location_lat=37.95,
            location_lon=-7.45,
            region="Alentejo",
            timezone="Europe/Lisbon",
            owner_id=grower.id,
            myirrigation_username="conqueiros_api",
            myirrigation_password="conqueiros_api",
            myirrigation_client_id="YYRIcSNREmmcFwNbt1i02w",
            myirrigation_client_secret="BTF77w9Yf6gUjabINuiFRA",
            myirrigation_weather_device_id="824",
        )
        session.add(farm_conq)
        session.flush()

        _DRIP_CONQ_ALMOND = {
            "system_type": "drip",
            "emitter_flow_lph": 2.3,
            "emitter_spacing_m": 0.5,
            "lines_per_row": 1,
            "efficiency": 0.90,
            "distribution_uniformity": 0.88,
            "max_runtime_hours": 8.0,
        }
        _DRIP_CONQ_OLIVE = {
            "system_type": "drip",
            "emitter_flow_lph": 2.3,
            "emitter_spacing_m": 0.5,
            "lines_per_row": 1,
            "efficiency": 0.90,
            "distribution_uniformity": 0.88,
            "max_runtime_hours": 8.0,
        }

        plot_amendoal = Plot(
            id=str(uuid.uuid4()),
            farm_id=farm_conq.id,
            name="Amendoal Conqueiros",
            area_ha=None,
            soil_texture=soil.texture,
            field_capacity=soil.field_capacity,
            wilting_point=soil.wilting_point,
            stone_content_pct=5.0,
            soil_preset_id=soil.id,
        )
        plot_olival = Plot(
            id=str(uuid.uuid4()),
            farm_id=farm_conq.id,
            name="Olival",
            area_ha=None,
            soil_texture=clay_loam.texture,
            field_capacity=clay_loam.field_capacity,
            wilting_point=clay_loam.wilting_point,
            stone_content_pct=5.0,
            soil_preset_id=clay_loam.id,
        )
        session.add_all([plot_amendoal, plot_olival])
        session.flush()

        conq_sectors = [
            # ── Amendoal (project 959) ────────────────────────────────────
            {
                "plot_id": plot_amendoal.id,
                "name": "Turno 1 (S02)",
                "crop_type": "almond",
                "variety": "Amendoeira",
                "current_phenological_stage": "almond_flowering",
                "irrigation_strategy": "full_etc",
                "template": almond_tmpl,
                "irrig_system": _DRIP_CONQ_ALMOND,
                "probe_external_id": PROBE_CONQ_S02,
            },
            {
                "plot_id": plot_amendoal.id,
                "name": "Turno 1 (S03)",
                "crop_type": "almond",
                "variety": "Amendoeira",
                "current_phenological_stage": "almond_flowering",
                "irrigation_strategy": "full_etc",
                "template": almond_tmpl,
                "irrig_system": _DRIP_CONQ_ALMOND,
                "probe_external_id": PROBE_CONQ_S03,
            },
            {
                "plot_id": plot_amendoal.id,
                "name": "Turno 2 (S10)",
                "crop_type": "almond",
                "variety": "Amendoeira",
                "current_phenological_stage": "almond_flowering",
                "irrigation_strategy": "full_etc",
                "template": almond_tmpl,
                "irrig_system": _DRIP_CONQ_ALMOND,
                "probe_external_id": PROBE_CONQ_S10,
            },
            {
                "plot_id": plot_amendoal.id,
                "name": "Turno 2 (S12)",
                "crop_type": "almond",
                "variety": "Amendoeira",
                "current_phenological_stage": "almond_flowering",
                "irrigation_strategy": "full_etc",
                "template": almond_tmpl,
                "irrig_system": _DRIP_CONQ_ALMOND,
                "probe_external_id": PROBE_CONQ_S12,
            },
            {
                "plot_id": plot_amendoal.id,
                "name": "Turno 3 (S19) Amendoal Novo",
                "crop_type": "almond",
                "variety": "Amendoeira",
                "current_phenological_stage": "almond_flowering",
                "irrigation_strategy": "full_etc",
                "template": almond_tmpl,
                "irrig_system": _DRIP_CONQ_ALMOND,
                "probe_external_id": PROBE_CONQ_S19,
            },
            {
                "plot_id": plot_amendoal.id,
                "name": "Turno 4 (S25) Amendoal Novo",
                "crop_type": "almond",
                "variety": "Amendoeira",
                "current_phenological_stage": "almond_flowering",
                "irrigation_strategy": "full_etc",
                "template": almond_tmpl,
                "irrig_system": _DRIP_CONQ_ALMOND,
                "probe_external_id": PROBE_CONQ_S25,
            },
            # ── Olival (project 1597) ─────────────────────────────────────
            {
                "plot_id": plot_olival.id,
                "name": "Turno 1 (S01)",
                "crop_type": "olive",
                "variety": "Oliveira",
                "current_phenological_stage": "olive_bud_break",
                "irrigation_strategy": "full_etc",
                "template": olive_tmpl,
                "irrig_system": _DRIP_CONQ_OLIVE,
                "probe_external_id": PROBE_CONQ_O01A,
            },
            {
                "plot_id": plot_olival.id,
                "name": "Turno 1 (S02)",
                "crop_type": "olive",
                "variety": "Oliveira",
                "current_phenological_stage": "olive_bud_break",
                "irrigation_strategy": "full_etc",
                "template": olive_tmpl,
                "irrig_system": _DRIP_CONQ_OLIVE,
                "probe_external_id": PROBE_CONQ_O01B,
            },
            {
                "plot_id": plot_olival.id,
                "name": "Turno 1 (S03)",
                "crop_type": "olive",
                "variety": "Oliveira",
                "current_phenological_stage": "olive_bud_break",
                "irrigation_strategy": "full_etc",
                "template": olive_tmpl,
                "irrig_system": _DRIP_CONQ_OLIVE,
                "probe_external_id": PROBE_CONQ_O01C,
            },
            {
                "plot_id": plot_olival.id,
                "name": "Turno 2 (S08)",
                "crop_type": "olive",
                "variety": "Oliveira",
                "current_phenological_stage": "olive_bud_break",
                "irrigation_strategy": "full_etc",
                "template": olive_tmpl,
                "irrig_system": _DRIP_CONQ_OLIVE,
                "probe_external_id": PROBE_CONQ_O02,
            },
            {
                "plot_id": plot_olival.id,
                "name": "Turno 3 (S12)",
                "crop_type": "olive",
                "variety": "Oliveira",
                "current_phenological_stage": "olive_bud_break",
                "irrigation_strategy": "full_etc",
                "template": olive_tmpl,
                "irrig_system": _DRIP_CONQ_OLIVE,
                "probe_external_id": PROBE_CONQ_O03,
            },
            {
                "plot_id": plot_olival.id,
                "name": "Turno 4 (S15)",
                "crop_type": "olive",
                "variety": "Oliveira",
                "current_phenological_stage": "olive_bud_break",
                "irrigation_strategy": "full_etc",
                "template": olive_tmpl,
                "irrig_system": _DRIP_CONQ_OLIVE,
                "probe_external_id": PROBE_CONQ_O04,
            },
            {
                "plot_id": plot_olival.id,
                "name": "Turno 5 (S20)",
                "crop_type": "olive",
                "variety": "Oliveira",
                "current_phenological_stage": "olive_bud_break",
                "irrigation_strategy": "full_etc",
                "template": olive_tmpl,
                "irrig_system": _DRIP_CONQ_OLIVE,
                "probe_external_id": PROBE_CONQ_O05,
            },
        ]

        now = datetime.now(UTC)

        for sd in conq_sectors:
            tmpl = sd.pop("template")
            irrig_data = sd.pop("irrig_system")
            probe_ext_id = sd.pop("probe_external_id")

            sector = Sector(id=str(uuid.uuid4()), **sd)
            session.add(sector)
            session.flush()

            scp = SectorCropProfile(
                id=str(uuid.uuid4()),
                sector_id=sector.id,
                source_template_id=tmpl.id,
                crop_type=tmpl.crop_type,
                mad=tmpl.mad,
                root_depth_mature_m=tmpl.root_depth_mature_m,
                root_depth_young_m=tmpl.root_depth_young_m,
                maturity_age_years=tmpl.maturity_age_years,
                stages=copy.deepcopy(tmpl.stages),
                is_customized=False,
            )
            session.add(scp)

            irrig_sys = IrrigationSystem(
                id=str(uuid.uuid4()),
                sector_id=sector.id,
                **irrig_data,
            )
            session.add(irrig_sys)

            probe = Probe(
                id=str(uuid.uuid4()),
                sector_id=sector.id,
                external_id=probe_ext_id,
                manufacturer="Pessl Instruments",
                model="Watermark WM200SS",
                install_date=date(2023, 3, 15),
                health_status="ok",
                last_reading_at=None,
                is_reference=True,
            )
            session.add(probe)
            session.flush()

            for depth_cm in [40, 60]:
                pd = ProbeDepth(
                    id=str(uuid.uuid4()),
                    probe_id=probe.id,
                    depth_cm=depth_cm,
                    sensor_type="soil_tension",
                    calibration_offset=0.0,
                    calibration_factor=1.0,
                )
                session.add(pd)

            print(f"  [+] Sector '{sector.name}' | probe={probe_ext_id}")

        session.commit()
        print(f"  Conqueiros: 2 plots, {len(conq_sectors)} sectors seeded ✓")

    # Verify counts
    with Session(engine) as session:
        n_templates = session.execute(select(CropProfileTemplate)).all()
        n_presets = session.execute(select(SoilPreset)).all()
        n_readings = session.execute(text("SELECT COUNT(*) FROM probe_reading")).scalar()
        n_obs = session.execute(text("SELECT COUNT(*) FROM weather_observation")).scalar()

        # Verify T01 crop profile has olive stages
        sector_t01 = session.execute(
            select(Sector).where(Sector.name == "T01 - Cobrançosa")
        ).scalar_one()
        scp = session.execute(
            select(SectorCropProfile).where(SectorCropProfile.sector_id == sector_t01.id)
        ).scalar_one()
        stage_keys = [s["key"] for s in scp.stages]
        assert "olive_oil_accumulation" in stage_keys, "olive_oil_accumulation stage missing!"
        first_stage_kc = scp.stages[0]["kc"]
        assert first_stage_kc == 0.40, f"Expected Kc=0.40 for dormancy, got {first_stage_kc}"

        # Verify T17 is Arbequina variety
        sector_t17 = session.execute(
            select(Sector).where(Sector.name == "T17 - Arbequina")
        ).scalar_one()
        assert sector_t17.variety == "Arbequina", "T17 should be Arbequina variety"
        assert sector_t17.current_phenological_stage == "olive_oil_accumulation"

        print("\n=== Seed complete ===")
        print(f"  Farm:             Herdade do Esporão")
        print(f"  Crop templates:   {len(n_templates)}")
        print(f"  Soil presets:     {len(n_presets)}")
        print(f"  Probe readings:   {n_readings:,} (0 expected — real data from MyIrrigation ingestion)")
        print(f"  Weather obs:      {n_obs} (mock seed data; replaced by MyIrrigation on first ingestion)")
        print(f"  T01 SCP:          olive, {len(scp.stages)} stages, Kc0={first_stage_kc} ✓")
        print(f"  T17 variety:      Arbequina ✓")
        print()
        print("  Probe external_ids (MyIrrigation device IDs, project 1044):")
        print("    T01 Cobrançosa WM01 → 1044/4663")
        print("    T04 Cobrançosa WM06 → 1044/4664")
        print("    T05 Cobrançosa WM02 → 1044/4662")
        print("    T07 Cobrançosa WM03 → 1044/4661")
        print("    T10 Cobrançosa WM04 → 1044/4666")
        print("    T17 Arbequina  WM07 → 1044/4665")
        print("    T18 Arbequina  WM05 → 1044/4667")
        print()


if __name__ == "__main__":
    engine = create_engine(settings.DATABASE_URL_SYNC, echo=False)
    seed(engine)
