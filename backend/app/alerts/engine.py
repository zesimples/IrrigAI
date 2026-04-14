"""Alert Engine — generates and reconciles operational alerts for a farm.

Sources:
  1. Anomaly detector  → probe/sensor anomalies
  2. Water balance     → water stress, over-irrigation
  3. Weather forecast  → rain skip opportunity
  4. Data freshness    → stale probes, stale weather
  5. Configuration     → missing critical setup

Alert reconciliation prevents flooding and auto-resolves fixed issues.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import AlertSeverity, AlertType
from app.engine.pipeline import build_sector_context, build_weather_context
from app.engine.probe_interpreter import interpret_probes
from app.engine.water_balance import build_water_balance
from app.models import Alert, Farm, Plot, Probe, Sector, WeatherObservation
from app.models.recommendation import Recommendation

logger = logging.getLogger(__name__)

# Thresholds
_STALE_PROBE_HOURS = 6.0
_STALE_WEATHER_HOURS = 24.0
_WATER_STRESS_FRACTION = 0.80    # depletion / TAW
_WATER_STRESS_CRITICAL = 0.90
_LOW_CONFIDENCE_THRESHOLD = 0.50


# ---------------------------------------------------------------------------
# Alert factory helpers
# ---------------------------------------------------------------------------

def _make_alert(
    alert_type: AlertType,
    severity: AlertSeverity,
    title_pt: str,
    title_en: str,
    description_pt: str,
    description_en: str,
    farm_id: str,
    sector_id: str | None = None,
    data: dict | None = None,
) -> Alert:
    return Alert(
        alert_type=alert_type,
        severity=severity,
        title_pt=title_pt,
        title_en=title_en,
        description_pt=description_pt,
        description_en=description_en,
        farm_id=farm_id,
        sector_id=sector_id,
        is_active=True,
        data=data or {},
    )


def _water_stress_alert(sector_name: str, depletion_pct: float, farm_id: str, sector_id: str) -> Alert:
    severity = AlertSeverity.CRITICAL if depletion_pct > 90 else AlertSeverity.WARNING
    return _make_alert(
        alert_type=AlertType.WATER_STRESS,
        severity=severity,
        title_pt=f"Stress hídrico: {sector_name}",
        title_en=f"Water stress: {sector_name}",
        description_pt=f"A depleção do solo atingiu {depletion_pct:.0f}% da água disponível. Rega recomendada.",
        description_en=f"Soil depletion reached {depletion_pct:.0f}% of available water. Irrigation recommended.",
        farm_id=farm_id,
        sector_id=sector_id,
        data={"depletion_pct": depletion_pct},
    )


def _over_irrigation_alert(sector_name: str, farm_id: str, sector_id: str) -> Alert:
    return _make_alert(
        alert_type=AlertType.OVER_IRRIGATION,
        severity=AlertSeverity.WARNING,
        title_pt=f"Excesso de rega: {sector_name}",
        title_en=f"Over-irrigation: {sector_name}",
        description_pt="O solo está acima da capacidade de campo. Risco de drenagem profunda e lavagem de nutrientes.",
        description_en="Soil is above field capacity. Risk of deep drainage and nutrient leaching.",
        farm_id=farm_id,
        sector_id=sector_id,
    )


def _rain_skip_alert(sector_name: str, rain_mm: float, farm_id: str, sector_id: str) -> Alert:
    return _make_alert(
        alert_type=AlertType.RAIN_SKIP,
        severity=AlertSeverity.INFO,
        title_pt=f"Oportunidade de redução de rega: {sector_name}",
        title_en=f"Rain skip opportunity: {sector_name}",
        description_pt=f"Prevista chuva de {rain_mm:.0f}mm nas próximas 48h. Considere adiar a rega.",
        description_en=f"Forecast {rain_mm:.0f}mm rain in the next 48h. Consider skipping irrigation.",
        farm_id=farm_id,
        sector_id=sector_id,
        data={"forecast_rain_mm": rain_mm},
    )


def _stale_probe_alert(sector_name: str, hours: float, farm_id: str, sector_id: str) -> Alert:
    return _make_alert(
        alert_type=AlertType.STALE_PROBE,
        severity=AlertSeverity.WARNING,
        title_pt=f"Dados de sonda desactualizados: {sector_name}",
        title_en=f"Stale probe data: {sector_name}",
        description_pt=f"Os dados da sonda têm {hours:.1f}h. Verifique a conectividade da sonda.",
        description_en=f"Probe data is {hours:.1f}h old. Check probe connectivity.",
        farm_id=farm_id,
        sector_id=sector_id,
        data={"hours_since_reading": hours},
    )


def _stale_weather_alert(hours: float, farm_id: str) -> Alert:
    return _make_alert(
        alert_type=AlertType.STALE_WEATHER,
        severity=AlertSeverity.INFO,
        title_pt="Dados meteorológicos desactualizados",
        title_en="Stale weather data",
        description_pt=f"Os dados meteorológicos têm {hours:.1f}h. As recomendações podem ser menos precisas.",
        description_en=f"Weather data is {hours:.1f}h old. Recommendations may be less accurate.",
        farm_id=farm_id,
        data={"hours_since_obs": hours},
    )


def _missing_config_alert(sector_name: str, missing: list[str], farm_id: str, sector_id: str) -> Alert:
    missing_str = "; ".join(missing)
    return _make_alert(
        alert_type=AlertType.MISSING_DATA,
        severity=AlertSeverity.INFO,
        title_pt=f"Configuração em falta: {sector_name}",
        title_en=f"Missing configuration: {sector_name}",
        description_pt=f"Configuração por completar: {missing_str}. As recomendações usam valores por defeito.",
        description_en=f"Incomplete configuration: {missing_str}. Recommendations use default values.",
        farm_id=farm_id,
        sector_id=sector_id,
        data={"missing": missing},
    )


def _low_confidence_alert(sector_name: str, score: float, farm_id: str, sector_id: str) -> Alert:
    return _make_alert(
        alert_type=AlertType.LOW_CONFIDENCE,
        severity=AlertSeverity.WARNING,
        title_pt=f"Baixa confiança na recomendação: {sector_name}",
        title_en=f"Low recommendation confidence: {sector_name}",
        description_pt=f"A confiança da última recomendação é de {score:.0%}. Configure mais parâmetros para melhorar.",
        description_en=f"Last recommendation confidence is {score:.0%}. Configure more parameters to improve.",
        farm_id=farm_id,
        sector_id=sector_id,
        data={"confidence_score": score},
    )


# ---------------------------------------------------------------------------
# Alert Engine
# ---------------------------------------------------------------------------

class AlertEngine:
    """Generates and reconciles operational alerts for a farm."""

    async def run_farm_alerts(self, farm_id: str, db: AsyncSession) -> list[Alert]:
        """Generate all alerts for a farm, reconcile with existing active alerts."""
        farm = await db.get(Farm, farm_id)
        if farm is None:
            return []

        new_alerts: list[Alert] = []

        # Collect all sectors
        plots_result = await db.execute(select(Plot).where(Plot.farm_id == farm_id))
        plots = plots_result.scalars().all()

        # Farm-level weather freshness
        weather_alert = await self._check_weather_freshness(farm_id, db)
        if weather_alert:
            new_alerts.append(weather_alert)

        for plot in plots:
            sectors_result = await db.execute(
                select(Sector).where(Sector.plot_id == plot.id)
            )
            for sector in sectors_result.scalars().all():
                try:
                    sector_alerts = await self._run_sector_alerts(sector, farm_id, db)
                    new_alerts.extend(sector_alerts)
                except Exception:
                    logger.exception("Alert check failed for sector %s", sector.id)

        await self.reconcile_alerts(farm_id, new_alerts, db)
        return new_alerts

    async def _run_sector_alerts(
        self, sector: Sector, farm_id: str, db: AsyncSession
    ) -> list[Alert]:
        alerts: list[Alert] = []

        # Load engine context for water balance
        try:
            ctx = await build_sector_context(sector.id, db)
        except Exception:
            logger.exception("Could not build sector context for %s", sector.id)
            return alerts

        # Missing config check
        if ctx.missing_config:
            alerts.append(_missing_config_alert(sector.name, ctx.missing_config, farm_id, sector.id))

        # Water balance
        try:
            probes_snap = await interpret_probes(ctx, db)
            wb = build_water_balance(ctx, probes_snap.rootzone.swc_current)

            depletion_fraction = wb.depletion_mm / wb.taw_mm if wb.taw_mm > 0 else 0.0

            if depletion_fraction >= _WATER_STRESS_FRACTION:
                depletion_pct = depletion_fraction * 100
                alerts.append(_water_stress_alert(sector.name, depletion_pct, farm_id, sector.id))

            # Over-irrigation: current SWC at or above FC
            if wb.swc_current >= wb.fc * 0.98:
                alerts.append(_over_irrigation_alert(sector.name, farm_id, sector.id))

        except Exception:
            logger.exception("Water balance check failed for sector %s", sector.id)

        # Probe data freshness
        freshness_alerts = await self._check_probe_freshness(sector, farm_id, db)
        alerts.extend(freshness_alerts)

        # Rain skip opportunity (needs weather)
        rain_alert = await self._check_rain_skip(sector, farm_id, db)
        if rain_alert:
            alerts.append(rain_alert)

        # Low confidence from latest recommendation
        conf_alert = await self._check_low_confidence(sector, farm_id, db)
        if conf_alert:
            alerts.append(conf_alert)

        return alerts

    async def _check_probe_freshness(
        self, sector: Sector, farm_id: str, db: AsyncSession
    ) -> list[Alert]:
        now = datetime.now(UTC)
        probes_result = await db.execute(
            select(Probe).where(Probe.sector_id == sector.id)
        )
        probes = probes_result.scalars().all()

        alerts: list[Alert] = []
        for probe in probes:
            if probe.last_reading_at is None:
                alerts.append(_stale_probe_alert(sector.name, 9999.0, farm_id, sector.id))
            else:
                ts = probe.last_reading_at
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=UTC)
                hours_old = (now - ts).total_seconds() / 3600
                if hours_old > _STALE_PROBE_HOURS:
                    alerts.append(_stale_probe_alert(sector.name, hours_old, farm_id, sector.id))
        return alerts

    async def _check_weather_freshness(self, farm_id: str, db: AsyncSession) -> Alert | None:
        now = datetime.now(UTC)
        obs_result = await db.execute(
            select(WeatherObservation)
            .where(WeatherObservation.farm_id == farm_id)
            .order_by(WeatherObservation.timestamp.desc())
            .limit(1)
        )
        obs = obs_result.scalar_one_or_none()
        if obs is None:
            return _stale_weather_alert(9999.0, farm_id)
        ts = obs.timestamp
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        hours_old = (now - ts).total_seconds() / 3600
        if hours_old > _STALE_WEATHER_HOURS:
            return _stale_weather_alert(hours_old, farm_id)
        return None

    async def _check_rain_skip(
        self, sector: Sector, farm_id: str, db: AsyncSession
    ) -> Alert | None:
        try:
            weather = await build_weather_context(farm_id, db)
            rain_48h = sum((f.rainfall_mm or 0.0) for f in weather.forecast[:2])
            if rain_48h >= 10.0:
                return _rain_skip_alert(sector.name, rain_48h, farm_id, sector.id)
        except Exception:
            pass
        return None

    async def _check_low_confidence(
        self, sector: Sector, farm_id: str, db: AsyncSession
    ) -> Alert | None:
        rec_result = await db.execute(
            select(Recommendation)
            .where(Recommendation.sector_id == sector.id)
            .order_by(Recommendation.generated_at.desc())
            .limit(1)
        )
        rec = rec_result.scalar_one_or_none()
        if rec and rec.confidence_score < _LOW_CONFIDENCE_THRESHOLD:
            return _low_confidence_alert(sector.name, rec.confidence_score, farm_id, sector.id)
        return None

    async def reconcile_alerts(
        self,
        farm_id: str,
        new_alerts: list[Alert],
        db: AsyncSession,
    ) -> None:
        """Reconcile new alert candidates with existing active alerts.

        - Match on (alert_type, sector_id)
        - If match: update timestamp, keep existing (no duplicate)
        - If no match for existing active alert: auto-resolve it
        - If no match for new alert: create it
        """
        existing_result = await db.execute(
            select(Alert).where(Alert.farm_id == farm_id, Alert.is_active.is_(True))
        )
        existing: list[Alert] = list(existing_result.scalars().all())

        def _key(a: Alert) -> tuple:
            return (a.alert_type, a.sector_id)

        existing_map = {_key(a): a for a in existing}
        new_keys = {_key(a) for a in new_alerts}

        # Auto-resolve existing alerts that are no longer triggered
        for key, existing_alert in existing_map.items():
            if key not in new_keys:
                existing_alert.is_active = False
                logger.debug("Auto-resolved alert %s (%s)", existing_alert.id, existing_alert.alert_type)

        # Create new alerts that don't already exist
        for alert in new_alerts:
            key = _key(alert)
            if key in existing_map:
                # Update the existing alert's data but don't create a duplicate
                existing_alert = existing_map[key]
                existing_alert.data = alert.data
                existing_alert.severity = alert.severity
                existing_alert.description_pt = alert.description_pt
                existing_alert.description_en = alert.description_en
            else:
                db.add(alert)
                logger.debug("Created alert %s for sector %s", alert.alert_type, alert.sector_id)

        await db.commit()
