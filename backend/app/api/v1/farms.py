from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models import Farm, FarmCredentials, Plot, Sector
from app.models.user import User
from app.schemas.common import PaginatedResponse
from app.schemas.farm import (
    FarmCreate,
    FarmCredentialsStatus,
    FarmCredentialsUpsert,
    FarmDetail,
    FarmOut,
    FarmUpdate,
    ProviderDiscovery,
    ProviderResource,
)
from app.services.audit_service import audit

router = APIRouter(prefix="/farms", tags=["farms"])

CurrentUser = Annotated[User, Depends(get_current_user)]


async def _owned_farm(farm_id: str, current_user: User, db: AsyncSession) -> Farm:
    farm = await db.get(Farm, farm_id)
    if not farm or (farm.owner_id != current_user.id and current_user.role != "admin"):
        raise HTTPException(404, detail="Farm not found")
    return farm


def _credential_status(credentials: FarmCredentials | None) -> FarmCredentialsStatus:
    return FarmCredentialsStatus(
        configured=bool(
            credentials
            and credentials.username
            and credentials.password
            and credentials.client_id
            and credentials.client_secret
        ),
        has_username=bool(credentials and credentials.username),
        has_password=bool(credentials and credentials.password),
        has_client_id=bool(credentials and credentials.client_id),
        has_client_secret=bool(credentials and credentials.client_secret),
        project_id=credentials.project_id if credentials else None,
        weather_device_id=credentials.weather_device_id if credentials else None,
    )


def _provider_resource(raw: dict, fallback_kind: str) -> ProviderResource | None:
    resource_id = raw.get("id") or raw.get("device_id") or raw.get("project_id")
    if resource_id is None:
        return None
    return ProviderResource(
        id=str(resource_id),
        name=str(raw.get("name") or raw.get("device_name") or raw.get("title") or resource_id),
        kind=(
            str(raw.get("type") or raw.get("device_type") or raw.get("sensor_type") or fallback_kind)
        ),
        project_id=(str(raw.get("project_id")) if raw.get("project_id") is not None else None),
        serial_number=(
            str(raw.get("serial_number") or raw.get("serial"))
            if raw.get("serial_number") or raw.get("serial")
            else None
        ),
    )


@router.get("", response_model=PaginatedResponse[FarmOut])
async def list_farms(
    current_user: CurrentUser,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    offset = (page - 1) * page_size
    base = select(Farm).where(Farm.is_archived == False)  # noqa: E712
    if current_user.role != "admin":
        base = base.where(Farm.owner_id == current_user.id)
    total = (await db.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
    farms = (
        await db.execute(
            base.order_by(Farm.created_at.desc()).offset(offset).limit(page_size)
        )
    ).scalars().all()
    return PaginatedResponse(
        items=[FarmOut.model_validate(f) for f in farms],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{farm_id}", response_model=FarmDetail)
async def get_farm(farm_id: str, current_user: CurrentUser, db: AsyncSession = Depends(get_db)):
    farm = await db.get(Farm, farm_id)
    if not farm or (farm.owner_id != current_user.id and current_user.role != "admin"):
        raise HTTPException(404, detail="Farm not found")

    plots = (await db.execute(select(Plot).where(Plot.farm_id == farm_id))).scalars().all()
    plot_ids = [p.id for p in plots]

    sector_count = 0
    if plot_ids:
        sector_count = (
            await db.execute(
                select(func.count()).select_from(Sector).where(Sector.plot_id.in_(plot_ids))
            )
        ).scalar_one()

    return FarmDetail(
        **FarmOut.model_validate(farm).model_dump(),
        plot_count=len(plots),
        sector_count=sector_count,
    )


@router.post("", response_model=FarmOut, status_code=201)
async def create_farm(body: FarmCreate, current_user: CurrentUser, db: AsyncSession = Depends(get_db)):
    data = body.model_dump()
    data["owner_id"] = current_user.id
    farm = Farm(**data)
    db.add(farm)
    await db.commit()
    await db.refresh(farm)
    return FarmOut.model_validate(farm)


@router.put("/{farm_id}", response_model=FarmOut)
async def update_farm(farm_id: str, body: FarmUpdate, current_user: CurrentUser, db: AsyncSession = Depends(get_db)):
    farm = await db.get(Farm, farm_id)
    if not farm or (farm.owner_id != current_user.id and current_user.role != "admin"):
        raise HTTPException(404, detail="Farm not found")
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(farm, k, v)
    await db.commit()
    await db.refresh(farm)
    return FarmOut.model_validate(farm)


@router.get("/{farm_id}/credentials", response_model=FarmCredentialsStatus)
async def get_farm_credentials_status(
    farm_id: str,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    await _owned_farm(farm_id, current_user, db)
    credentials = (
        await db.execute(
            select(FarmCredentials).where(FarmCredentials.farm_id == farm_id)
        )
    ).scalar_one_or_none()
    return _credential_status(credentials)


@router.put("/{farm_id}/credentials", response_model=FarmCredentialsStatus)
async def upsert_farm_credentials(
    farm_id: str,
    body: FarmCredentialsUpsert,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    await _owned_farm(farm_id, current_user, db)
    credentials = (
        await db.execute(
            select(FarmCredentials).where(FarmCredentials.farm_id == farm_id)
        )
    ).scalar_one_or_none()
    created = credentials is None
    if credentials is None:
        credentials = FarmCredentials(farm_id=farm_id)
        db.add(credentials)
    for key, value in body.model_dump().items():
        setattr(credentials, key, value)
    await db.flush()
    await audit.log(
        "farm_credentials_created" if created else "farm_credentials_updated",
        "farm_credentials",
        str(credentials.id),
        db,
        user_id=str(current_user.id),
        after_data={
            "configured": True,
            "project_id": credentials.project_id,
            "weather_device_id": credentials.weather_device_id,
        },
    )
    await db.commit()
    return _credential_status(credentials)


@router.get("/{farm_id}/provider-resources", response_model=ProviderDiscovery)
async def discover_provider_resources(
    farm_id: str,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """Validate saved MyIrrigation credentials and return sanitized resources."""
    await _owned_farm(farm_id, current_user, db)
    credentials = (
        await db.execute(
            select(FarmCredentials).where(FarmCredentials.farm_id == farm_id)
        )
    ).scalar_one_or_none()
    if not _credential_status(credentials).configured:
        raise HTTPException(409, detail="Farm provider credentials are not configured")

    from app.adapters.myirrigation import MyIrrigationAdapter
    from app.config import get_settings

    settings = get_settings()
    adapter = MyIrrigationAdapter(
        base_url=settings.MYIRRIGATION_BASE_URL,
        username=credentials.username,
        password=credentials.password,
        client_id=credentials.client_id,
        client_secret=credentials.client_secret,
        project_id=credentials.project_id or "",
        weather_device_id=credentials.weather_device_id or "",
    )
    try:
        projects_raw = await adapter.get_projects()
        devices_raw = await adapter.get_devices()
    except Exception as exc:
        raise HTTPException(502, detail="Provider authentication or discovery failed") from exc

    projects = [r for raw in projects_raw if (r := _provider_resource(raw, "project"))]
    devices = [r for raw in devices_raw if (r := _provider_resource(raw, "device"))]
    return ProviderDiscovery(projects=projects, devices=devices)


@router.post("/{farm_id}/archive", response_model=FarmOut)
async def archive_farm(farm_id: str, current_user: CurrentUser, db: AsyncSession = Depends(get_db)):
    farm = await db.get(Farm, farm_id)
    if not farm or (farm.owner_id != current_user.id and current_user.role != "admin"):
        raise HTTPException(404, detail="Farm not found")
    farm.is_archived = True
    farm.archived_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(farm)
    return FarmOut.model_validate(farm)


@router.post("/{farm_id}/unarchive", response_model=FarmOut)
async def unarchive_farm(farm_id: str, current_user: CurrentUser, db: AsyncSession = Depends(get_db)):
    farm = await db.get(Farm, farm_id)
    if not farm or (farm.owner_id != current_user.id and current_user.role != "admin"):
        raise HTTPException(404, detail="Farm not found")
    farm.is_archived = False
    farm.archived_at = None
    await db.commit()
    await db.refresh(farm)
    return FarmOut.model_validate(farm)
