"""Auto-calibration service.

Validates configured soil type against observed probe data patterns.
Compares observed FC/refill against the existing soil preset list — NEVER
creates custom soil values.
"""

import logging
import statistics
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Thresholds for soil match decisions (in vol%)
VALIDATED_THRESHOLD_PCT = 2.0           # current preset within 2 vol% → validated
BETTER_MATCH_THRESHOLD_PCT = 3.0        # other preset >3 vol% closer → suggest switch
NO_MATCH_THRESHOLD_PCT = 5.0            # no preset within 5 vol% → flag mismatch

# Cycle detection parameters
SPIKE_THRESHOLD_M3M3 = 0.03             # 3 vol% increase in < 4h
PEAK_WINDOW_H = (6, 24)                 # look for peak 6–24h after irrigation
SHALLOW_MAX_DEPTH_CM = 30               # prefer depths ≤30cm; fall back to ≤60cm

# --- Probe-calibrated field-capacity (m³/m³) ---
CALIB_WINDOW_DAYS = 30
# A saved calibration is not trusted forever: once computed_at is older than this,
# soil-bound resolution ignores it and falls back to the next source. Manual re-run
# (or the next scheduled run) refreshes it.
CALIB_MAX_AGE_DAYS = 90
CALIB_MIN_READINGS = 48
CALIB_MIN_CYCLES = 3
CALIB_FC_MIN_M3M3 = 0.10
CALIB_FC_MAX_M3M3 = 0.60
CALIB_MIN_SPREAD_M3M3 = 0.03
ENVELOPE_FC_PCTL = 95.0
ENVELOPE_REFILL_PCTL = 10.0


@dataclass
class IrrigationCycle:
    irrigation_date: datetime
    peak_vwc_pct: float
    peak_depth_cm: int
    trough_vwc_pct: float
    trough_date: datetime
    cycle_duration_days: float


@dataclass
class ObservedSoilPoints:
    observed_fc_pct: float
    observed_refill_pct: float
    num_cycles: int
    consistency: float                  # 0-1, higher = more consistent
    analysis_depths_cm: list[int]


@dataclass
class ProbeCalibrationResult:
    observed_fc: float          # m³/m³ — drained upper limit
    observed_refill: float      # m³/m³ — refill / lower bound
    method: str                 # "cycles" | "envelope"
    num_cycles: int
    consistency: float          # 0–1
    window_days: int


@dataclass
class SoilPresetMatch:
    preset_id: str
    preset_name_pt: str
    preset_name_en: str
    preset_fc_pct: float
    preset_wp_pct: float
    distance: float


@dataclass
class SoilMatchResult:
    current_preset: SoilPresetMatch | None
    best_match: SoilPresetMatch
    all_matches: list[SoilPresetMatch]
    status: str                         # "validated" | "better_match_found" | "no_good_match"


@dataclass
class AutoCalibrationResult:
    sector_id: str
    sector_name: str
    observed: ObservedSoilPoints
    match: SoilMatchResult
    suggestion_pt: str
    suggestion_en: str
    generated_at: datetime


class AutoCalibrationService:

    async def analyze_sector(
        self, sector_id: str, db: AsyncSession
    ) -> AutoCalibrationResult | None:
        from app.models import IrrigationEvent, Plot, Probe, ProbeDepth, ProbeReading, Sector, SectorCropProfile

        sector = await db.get(Sector, sector_id)
        if sector is None:
            return None

        since = datetime.now(UTC) - timedelta(days=CALIB_WINDOW_DAYS)

        # --- Load probe depths at shallow levels ---
        probes_result = await db.execute(select(Probe).where(Probe.sector_id == sector_id))
        probes = probes_result.scalars().all()
        if not probes:
            return None

        depth_ids_by_depth: dict[int, str] = {}  # depth_cm → depth_id
        for probe in probes:
            depths_result = await db.execute(
                select(ProbeDepth).where(
                    ProbeDepth.probe_id == probe.id,
                    # Real VWC depths are "soil_moisture"; "moisture" is a legacy
                    # synonym still present in old/mock data.
                    ProbeDepth.sensor_type.in_(("soil_moisture", "moisture")),
                )
            )
            depths = depths_result.scalars().all()
            for d in depths:
                if d.depth_cm not in depth_ids_by_depth:
                    depth_ids_by_depth[d.depth_cm] = d.id

        # Prefer shallow depths
        shallow_ids = {dc: did for dc, did in depth_ids_by_depth.items() if dc <= SHALLOW_MAX_DEPTH_CM}
        if not shallow_ids:
            shallow_ids = {dc: did for dc, did in depth_ids_by_depth.items() if dc <= 60}
        if not shallow_ids:
            return None

        # --- Load probe readings for shallow depths ---
        readings_result = await db.execute(
            select(ProbeReading)
            .where(
                ProbeReading.probe_depth_id.in_(list(shallow_ids.values())),
                ProbeReading.timestamp >= since,
                ProbeReading.unit == "vwc_m3m3",
                ProbeReading.quality_flag == "ok",
            )
            .order_by(ProbeReading.timestamp)
        )
        readings = readings_result.scalars().all()
        if len(readings) < 48:
            return None

        # Map reading → depth_cm
        id_to_depth: dict[str, int] = {did: dc for dc, did in shallow_ids.items()}

        # --- Load irrigation events ---
        events_result = await db.execute(
            select(IrrigationEvent)
            .where(
                IrrigationEvent.sector_id == sector_id,
                IrrigationEvent.start_time >= since,
            )
            .order_by(IrrigationEvent.start_time)
        )
        events = events_result.scalars().all()

        # Also detect irrigation events from probe spikes (fallback)
        detected_events = self._detect_irrigation_events_from_probes(readings, id_to_depth)

        # Merge recorded + detected events, sorted by time
        all_event_times: list[datetime] = sorted(
            set(
                [e.start_time for e in events]
                + detected_events
            )
        )

        if len(all_event_times) < 3:
            return None

        # --- Build irrigation cycles ---
        cycles = self._build_cycles(readings, id_to_depth, all_event_times)
        if len(cycles) < 3:
            return None

        observed = self.compute_observed_reference_points(cycles)

        # --- Current soil preset ---
        scp_result = await db.execute(
            select(SectorCropProfile).where(SectorCropProfile.sector_id == sector_id)
        )
        scp = scp_result.scalar_one_or_none()
        current_preset_id = scp.soil_preset_id if scp else None

        # --- Match against all soil presets ---
        plot = await db.get(Plot, sector.plot_id)
        if current_preset_id is None and plot:
            current_preset_id = plot.soil_preset_id

        match = await self.match_against_soil_presets(observed, current_preset_id, db)

        suggestion_pt, suggestion_en = _build_calibration_suggestion(
            match, observed, sector.name
        )

        return AutoCalibrationResult(
            sector_id=sector_id,
            sector_name=sector.name,
            observed=observed,
            match=match,
            suggestion_pt=suggestion_pt,
            suggestion_en=suggestion_en,
            generated_at=datetime.now(UTC),
        )

    def _detect_irrigation_events_from_probes(
        self, readings: list, id_to_depth: dict[str, int]
    ) -> list[datetime]:
        """Detect irrigation events as VWC spikes > 3 vol% within 4h at shallow depths."""
        detected: list[datetime] = []
        by_depth: dict[int, list] = {}
        for r in readings:
            dc = id_to_depth.get(r.probe_depth_id)
            if dc is not None:
                by_depth.setdefault(dc, []).append(r)

        for dc, depth_readings in by_depth.items():
            for i in range(1, len(depth_readings)):
                prev = depth_readings[i - 1]
                curr = depth_readings[i]
                dt_h = (curr.timestamp - prev.timestamp).total_seconds() / 3600
                if dt_h <= 0 or dt_h > 4:
                    continue
                prev_val = prev.calibrated_value or prev.raw_value
                curr_val = curr.calibrated_value or curr.raw_value
                if curr_val - prev_val >= SPIKE_THRESHOLD_M3M3:
                    detected.append(prev.timestamp)
        return detected

    def _build_cycles(
        self,
        readings: list,
        id_to_depth: dict[str, int],
        event_times: list[datetime],
    ) -> list[IrrigationCycle]:
        cycles: list[IrrigationCycle] = []

        for i, event_time in enumerate(event_times):
            peak_start = event_time + timedelta(hours=PEAK_WINDOW_H[0])
            peak_end = event_time + timedelta(hours=PEAK_WINDOW_H[1])
            next_event = event_times[i + 1] if i + 1 < len(event_times) else datetime.now(UTC)

            peak_readings = [
                r for r in readings
                if peak_start <= r.timestamp <= peak_end
            ]
            if not peak_readings:
                continue

            trough_start = peak_end
            trough_readings = [
                r for r in readings
                if trough_start <= r.timestamp <= next_event - timedelta(hours=4)
            ]
            if not trough_readings:
                continue

            def _val(r):
                v = r.calibrated_value if r.calibrated_value is not None else r.raw_value
                return v if v is not None else 0.0

            peak_vwc = max(_val(r) for r in peak_readings)
            trough_vwc = min(_val(r) for r in trough_readings)

            # Get depth of peak reading
            peak_r = max(peak_readings, key=_val)
            peak_depth = id_to_depth.get(peak_r.probe_depth_id, 0)
            trough_r = min(trough_readings, key=_val)
            trough_time = trough_r.timestamp

            cycles.append(IrrigationCycle(
                irrigation_date=event_time,
                peak_vwc_pct=round(peak_vwc * 100, 2),
                peak_depth_cm=peak_depth,
                trough_vwc_pct=round(trough_vwc * 100, 2),
                trough_date=trough_time,
                cycle_duration_days=round((next_event - event_time).total_seconds() / 86400, 1),
            ))

        return cycles

    def compute_observed_reference_points(
        self, cycles: list[IrrigationCycle]
    ) -> ObservedSoilPoints:
        peaks = [c.peak_vwc_pct for c in cycles]
        troughs = [c.trough_vwc_pct for c in cycles]
        depths = list({c.peak_depth_cm for c in cycles})

        observed_fc = statistics.median(peaks)
        observed_refill = statistics.median(troughs)

        if len(peaks) >= 2:
            consistency = max(0.0, 1.0 - statistics.stdev(peaks) / (observed_fc + 0.001))
        else:
            consistency = 0.5

        return ObservedSoilPoints(
            observed_fc_pct=round(observed_fc, 1),
            observed_refill_pct=round(observed_refill, 1),
            num_cycles=len(cycles),
            consistency=round(consistency, 2),
            analysis_depths_cm=sorted(depths),
        )

    async def match_against_soil_presets(
        self,
        observed: ObservedSoilPoints,
        current_preset_id: str | None,
        db: AsyncSession,
    ) -> SoilMatchResult:
        from app.models import SoilPreset

        presets_result = await db.execute(select(SoilPreset))
        presets = presets_result.scalars().all()

        matches: list[SoilPresetMatch] = []
        for preset in presets:
            preset_fc_pct = preset.field_capacity * 100
            preset_wp_pct = preset.wilting_point * 100
            distance = (
                abs(observed.observed_fc_pct - preset_fc_pct)
                + abs(observed.observed_refill_pct - preset_wp_pct)
            )
            matches.append(SoilPresetMatch(
                preset_id=preset.id,
                preset_name_pt=preset.name_pt,
                preset_name_en=preset.name_en,
                preset_fc_pct=round(preset_fc_pct, 1),
                preset_wp_pct=round(preset_wp_pct, 1),
                distance=round(distance, 2),
            ))

        matches.sort(key=lambda m: m.distance)
        best_match = matches[0]

        current_preset: SoilPresetMatch | None = None
        if current_preset_id:
            current_preset = next((m for m in matches if m.preset_id == current_preset_id), None)

        # Determine status
        if best_match.distance > NO_MATCH_THRESHOLD_PCT * 2:
            status = "no_good_match"
        elif current_preset is None:
            status = "better_match_found"
        elif current_preset.preset_id == best_match.preset_id:
            status = "validated"
        elif (current_preset.distance - best_match.distance) > BETTER_MATCH_THRESHOLD_PCT:
            status = "better_match_found"
        elif current_preset.distance <= VALIDATED_THRESHOLD_PCT:
            status = "validated"
        else:
            status = "validated"

        return SoilMatchResult(
            current_preset=current_preset,
            best_match=best_match,
            all_matches=matches,
            status=status,
        )

    async def compute_sector_calibration(
        self, sector_id: str, db: AsyncSession
    ) -> ProbeCalibrationResult | None:
        """Calibrate FC / refill bounds to a sector's own VWC envelope.

        Prefers cycle-based reference points (≥ CALIB_MIN_CYCLES clean cycles);
        otherwise falls back to a percentile envelope proxy. Returns None when
        there is too little data or the result fails plausibility guards (the
        caller then keeps the preset FC).
        """
        from app.models import IrrigationEvent, Probe, ProbeDepth, ProbeReading, Sector

        sector = await db.get(Sector, sector_id)
        if sector is None:
            return None

        since = datetime.now(UTC) - timedelta(days=CALIB_WINDOW_DAYS)

        probes = (await db.execute(
            select(Probe).where(Probe.sector_id == sector_id)
        )).scalars().all()
        if not probes:
            return None

        depth_ids_by_depth: dict[int, str] = {}
        for probe in probes:
            depths = (await db.execute(
                select(ProbeDepth).where(
                    ProbeDepth.probe_id == probe.id,
                    # Real data uses "soil_moisture"; older/mock data uses "moisture".
                    # Tension depths are excluded here and again by the vwc_m3m3 unit
                    # filter on the readings query below.
                    ProbeDepth.sensor_type.in_(("soil_moisture", "moisture")),
                )
            )).scalars().all()
            for d in depths:
                depth_ids_by_depth.setdefault(d.depth_cm, d.id)

        shallow_ids = {dc: did for dc, did in depth_ids_by_depth.items() if dc <= SHALLOW_MAX_DEPTH_CM}
        if not shallow_ids:
            shallow_ids = {dc: did for dc, did in depth_ids_by_depth.items() if dc <= 60}
        if not shallow_ids:
            return None

        readings = (await db.execute(
            select(ProbeReading)
            .where(
                ProbeReading.probe_depth_id.in_(list(shallow_ids.values())),
                ProbeReading.timestamp >= since,
                ProbeReading.unit == "vwc_m3m3",
                ProbeReading.quality_flag == "ok",
            )
            .order_by(ProbeReading.timestamp)
        )).scalars().all()
        if len(readings) < CALIB_MIN_READINGS:
            return None

        id_to_depth = {did: dc for dc, did in shallow_ids.items()}

        def _val(r):
            v = r.calibrated_value if r.calibrated_value is not None else r.raw_value
            return v

        result: ProbeCalibrationResult | None = None

        # --- Try cycle-based calibration first ---
        events = (await db.execute(
            select(IrrigationEvent).where(
                IrrigationEvent.sector_id == sector_id,
                IrrigationEvent.start_time >= since,
            ).order_by(IrrigationEvent.start_time)
        )).scalars().all()
        detected = self._detect_irrigation_events_from_probes(readings, id_to_depth)
        event_times = sorted(set([e.start_time for e in events] + detected))

        if len(event_times) >= CALIB_MIN_CYCLES:
            cycles = self._build_cycles(readings, id_to_depth, event_times)
            if len(cycles) >= CALIB_MIN_CYCLES:
                obs = self.compute_observed_reference_points(cycles)
                result = ProbeCalibrationResult(
                    observed_fc=round(obs.observed_fc_pct / 100, 4),
                    observed_refill=round(obs.observed_refill_pct / 100, 4),
                    method="cycles",
                    num_cycles=obs.num_cycles,
                    consistency=obs.consistency,
                    window_days=CALIB_WINDOW_DAYS,
                )

        # --- Envelope fallback ---
        if result is None:
            vwc_values = [_val(r) for r in readings if _val(r) is not None]
            if len(vwc_values) < CALIB_MIN_READINGS:
                return None
            fc, refill = compute_envelope_points(vwc_values)
            result = ProbeCalibrationResult(
                observed_fc=fc,
                observed_refill=refill,
                method="envelope",
                num_cycles=0,
                consistency=0.5,
                window_days=CALIB_WINDOW_DAYS,
            )

        if not is_plausible_calibration(result.observed_fc, result.observed_refill):
            return None
        return result

    async def diagnose_unavailable(self, sector_id: str, db: AsyncSession) -> str:
        """Human-readable (pt) reason why compute_sector_calibration returned None.

        Mirrors the gates in compute_sector_calibration so the manual /run endpoint
        can tell the user the *actual* blocker (tension-only probe, too few VWC
        readings, implausible envelope) instead of a generic "insufficient data".
        """
        from app.models import Probe, ProbeDepth, ProbeReading

        since = datetime.now(UTC) - timedelta(days=CALIB_WINDOW_DAYS)
        probes = (await db.execute(
            select(Probe).where(Probe.sector_id == sector_id)
        )).scalars().all()
        if not probes:
            return (
                "Este sector não tem sonda associada, por isso não é possível "
                "calibrar a partir de dados de sonda."
            )

        moisture_depths: dict[int, str] = {}
        has_tension = False
        for probe in probes:
            depths = (await db.execute(
                select(ProbeDepth).where(ProbeDepth.probe_id == probe.id)
            )).scalars().all()
            for d in depths:
                if d.sensor_type in ("soil_moisture", "moisture"):
                    moisture_depths.setdefault(d.depth_cm, d.id)
                elif d.sensor_type and "tension" in d.sensor_type:
                    has_tension = True

        shallow = {dc: did for dc, did in moisture_depths.items() if dc <= SHALLOW_MAX_DEPTH_CM} or {
            dc: did for dc, did in moisture_depths.items() if dc <= 60
        }
        if not shallow:
            if has_tension:
                return (
                    "Este sector usa sensores de tensão (tipo Watermark). A calibração "
                    "precisa de sensores de humidade volumétrica (VWC) e não está "
                    "disponível para sensores de tensão."
                )
            return (
                "Este sector não tem sensores de humidade volumétrica (VWC) até 60 cm "
                "de profundidade para calibrar."
            )

        n = (await db.execute(
            select(func.count(ProbeReading.id)).where(
                ProbeReading.probe_depth_id.in_(list(shallow.values())),
                ProbeReading.timestamp >= since,
                ProbeReading.unit == "vwc_m3m3",
                ProbeReading.quality_flag == "ok",
            )
        )).scalar() or 0
        if n < CALIB_MIN_READINGS:
            return (
                f"Ainda não há leituras VWC suficientes para calibrar: {n} de "
                f"{CALIB_MIN_READINGS} necessárias nos últimos {CALIB_WINDOW_DAYS} dias."
            )

        return (
            "As leituras VWC disponíveis são demasiado planas ou fora do intervalo "
            "plausível para uma calibração fiável."
        )


def _build_calibration_suggestion(
    match: SoilMatchResult,
    observed: ObservedSoilPoints,
    sector_name: str,
) -> tuple[str, str]:
    obs_fc = observed.observed_fc_pct
    n = observed.num_cycles

    if match.status == "validated":
        cp = match.current_preset or match.best_match
        pt = (
            f"Validado: o tipo de solo '{cp.preset_name_pt}' corresponde aos dados da sonda "
            f"(CC observada: {obs_fc:.0f} vol%, preset: {cp.preset_fc_pct:.0f} vol%). "
            f"Com base em {n} ciclos de rega."
        )
        en = (
            f"Validated: soil type '{cp.preset_name_en}' matches probe data "
            f"(observed FC: {obs_fc:.0f} vol%, preset: {cp.preset_fc_pct:.0f} vol%). "
            f"Based on {n} irrigation cycles."
        )
    elif match.status == "better_match_found":
        bm = match.best_match
        cp = match.current_preset
        current_info = f" do que '{cp.preset_name_pt}' (CC: {cp.preset_fc_pct:.0f} vol%)" if cp else ""
        pt = (
            f"Os dados da sonda sugerem que o solo é mais próximo de '{bm.preset_name_pt}' "
            f"(CC: {bm.preset_fc_pct:.0f} vol%, PMP: {bm.preset_wp_pct:.0f} vol%){current_info}. "
            f"CC observada: {obs_fc:.0f} vol%. Com base em {n} ciclos de rega."
        )
        current_info_en = f" than '{cp.preset_name_en}' (FC: {cp.preset_fc_pct:.0f} vol%)" if cp else ""
        en = (
            f"Probe data suggests soil is closer to '{bm.preset_name_en}' "
            f"(FC: {bm.preset_fc_pct:.0f} vol%, WP: {bm.preset_wp_pct:.0f} vol%){current_info_en}. "
            f"Observed FC: {obs_fc:.0f} vol%. Based on {n} irrigation cycles."
        )
    else:  # no_good_match
        bm = match.best_match
        pt = (
            f"Os valores observados (CC: {obs_fc:.0f} vol%) não correspondem bem a nenhum tipo de solo "
            f"na lista (mais próximo: '{bm.preset_name_pt}' com distância {bm.distance:.1f} vol%). "
            f"Considere rever os tipos de solo disponíveis."
        )
        en = (
            f"Observed values (FC: {obs_fc:.0f} vol%) do not match any soil type in the list well "
            f"(closest: '{bm.preset_name_en}' at {bm.distance:.1f} vol% distance). "
            f"Consider reviewing available soil types."
        )

    return pt, en


def percentile(values: list[float], pct: float) -> float:
    """Linear-interpolation percentile (pct in 0–100). `values` need not be sorted."""
    if not values:
        raise ValueError("percentile of empty sequence")
    s = sorted(values)
    if len(s) == 1:
        return s[0]
    rank = (pct / 100.0) * (len(s) - 1)
    lo = int(rank)
    hi = min(lo + 1, len(s) - 1)
    frac = rank - lo
    return s[lo] + (s[hi] - s[lo]) * frac


def compute_depth_envelope(vwc_values: list[float]) -> tuple[float, float] | None:
    """Display-only observed envelope (CC_i, refill_i) for ONE depth.

    Same percentile envelope + plausibility guards as the sector calibration,
    applied to a single depth's history. Returns None when the depth has too
    little data or an implausible band (caller leaves the depth's bounds null).
    Used by the probe readings endpoint so the Soma chart can sum real
    per-layer bounds; never feeds the engine's TAW.
    """
    if len(vwc_values) < CALIB_MIN_READINGS:
        return None
    fc, refill = compute_envelope_points(vwc_values)
    if not is_plausible_calibration(fc, refill):
        return None
    return fc, refill


def compute_envelope_points(vwc_values: list[float]) -> tuple[float, float]:
    """Envelope-proxy calibration → (observed_fc, observed_refill) in m³/m³.

    FC ≈ high percentile of the trailing VWC envelope (drained upper limit);
    refill ≈ low percentile (operating lower bound). Used when there are fewer
    than CALIB_MIN_CYCLES clean irrigation cycles for cycle-based calibration.
    """
    fc = percentile(vwc_values, ENVELOPE_FC_PCTL)
    refill = percentile(vwc_values, ENVELOPE_REFILL_PCTL)
    return round(fc, 4), round(refill, 4)


def is_calibration_stale(
    computed_at: datetime | None,
    now: datetime | None = None,
    max_age_days: int = CALIB_MAX_AGE_DAYS,
) -> bool:
    """A saved calibration is stale once it is older than `max_age_days`.

    Stale calibrations are ignored by soil-bound resolution (the caller falls back
    to the next source). A missing `computed_at` is treated as stale. Naive
    datetimes are assumed UTC so old rows never crash the comparison.
    """
    if computed_at is None:
        return True
    if computed_at.tzinfo is None:
        computed_at = computed_at.replace(tzinfo=UTC)
    now = now or datetime.now(UTC)
    return (now - computed_at) > timedelta(days=max_age_days)


def is_plausible_calibration(observed_fc: float, observed_refill: float) -> bool:
    """Reject implausible calibrations so the caller falls back to the preset FC."""
    if not (CALIB_FC_MIN_M3M3 <= observed_fc <= CALIB_FC_MAX_M3M3):
        return False
    return (observed_fc - observed_refill) >= CALIB_MIN_SPREAD_M3M3
