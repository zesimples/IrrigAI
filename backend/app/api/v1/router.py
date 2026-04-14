from fastapi import APIRouter

from app.api.v1 import (
    alerts,
    audit_log,
    chat,
    crop_profiles,
    dashboard,
    farms,
    irrigation,
    overrides,
    plots,
    probes,
    recommendations,
    sectors,
    weather,
)

router = APIRouter()

router.include_router(farms.router)
router.include_router(plots.router)
router.include_router(sectors.router)
router.include_router(probes.router)
router.include_router(weather.router)
router.include_router(recommendations.router)
router.include_router(alerts.router)
router.include_router(irrigation.router)
router.include_router(dashboard.router)
router.include_router(crop_profiles.router)
router.include_router(chat.router)
router.include_router(overrides.router)
router.include_router(audit_log.router)
