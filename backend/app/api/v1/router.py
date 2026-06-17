from fastapi import APIRouter, Depends

from app.api.v1 import (
    alerts,
    audit_log,
    auth,
    auto_calibration,
    chat,
    crop_profiles,
    dashboard,
    farms,
    flowmeter,
    flowmeter_reference,
    gdd,
    irrigation,
    overrides,
    plots,
    probes,
    recommendations,
    sectors,
    weather,
)
from app.auth import get_current_user

router = APIRouter()

# Authentication is enforced at the router level on every resource group except
# `auth` (which issues tokens and must stay anonymous). Endpoints that also take
# `current_user` as a parameter resolve the same dependency once (FastAPI caches
# it per request) and use it for ownership checks. New routers are protected by
# default — add them below and they inherit auth automatically.
_auth = [Depends(get_current_user)]

router.include_router(auth.router)
router.include_router(farms.router, dependencies=_auth)
router.include_router(plots.router, dependencies=_auth)
router.include_router(sectors.router, dependencies=_auth)
router.include_router(probes.router, dependencies=_auth)
router.include_router(weather.router, dependencies=_auth)
router.include_router(recommendations.router, dependencies=_auth)
router.include_router(alerts.router, dependencies=_auth)
router.include_router(irrigation.router, dependencies=_auth)
router.include_router(dashboard.router, dependencies=_auth)
router.include_router(crop_profiles.router, dependencies=_auth)
router.include_router(chat.router, dependencies=_auth)
router.include_router(overrides.router, dependencies=_auth)
router.include_router(audit_log.router, dependencies=_auth)
router.include_router(auto_calibration.router, dependencies=_auth)
router.include_router(gdd.router, dependencies=_auth)
router.include_router(flowmeter.router, dependencies=_auth)
router.include_router(flowmeter_reference.router, dependencies=_auth)
