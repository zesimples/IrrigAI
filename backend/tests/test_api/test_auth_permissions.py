"""API auth and permission tests.

Exit criteria:
- Unauthenticated requests to protected endpoints → 401
- Invalid / expired tokens → 401
- User A cannot read, write, or list resources owned by user B → 404 / empty list
- A failing permission check breaks CI (these tests are in the full test run)
"""

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from httpx import AsyncClient
from jose import jwt
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import create_access_token, hash_password
from app.config import get_settings
from app.models.alert import Alert
from app.models.base import new_uuid
from app.models.farm import Farm
from app.models.irrigation_event import IrrigationEvent
from app.models.plot import Plot
from app.models.probe import Probe
from app.models.recommendation import Recommendation
from app.models.sector import Sector
from app.models.user import User

# ── helpers ───────────────────────────────────────────────────────────────────

def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _make_user(db: AsyncSession, suffix: str = "") -> User:
    uid = str(uuid.uuid4())
    user = User(
        id=uid,
        email=f"test-{uid}{suffix}@irrigai.test",
        name=f"Test {suffix}",
        hashed_password=hash_password("hunter2-" + uid),
    )
    db.add(user)
    await db.commit()
    return user


async def _make_farm(db: AsyncSession, owner: User) -> Farm:
    farm = Farm(id=new_uuid(), name=f"Farm-{uuid.uuid4()}", owner_id=owner.id)
    db.add(farm)
    await db.commit()
    return farm


async def _make_sector_tree(db: AsyncSession, owner: User) -> tuple[Farm, Plot, Sector]:
    farm = await _make_farm(db, owner)
    plot = Plot(id=new_uuid(), farm_id=farm.id, name=f"Plot-{uuid.uuid4()}", area_ha=1.0)
    sector = Sector(
        id=new_uuid(),
        plot_id=plot.id,
        name=f"Sector-{uuid.uuid4()}",
        crop_type="olive",
    )
    db.add_all([plot, sector])
    await db.commit()
    return farm, plot, sector


# ── 401 — unauthenticated ─────────────────────────────────────────────────────

async def test_list_farms_requires_auth(noauth_client: AsyncClient):
    resp = await noauth_client.get("/api/v1/farms")
    assert resp.status_code == 401


async def test_get_farm_requires_auth(noauth_client: AsyncClient, db: AsyncSession):
    owner = await _make_user(db, "owner")
    farm = await _make_farm(db, owner)
    resp = await noauth_client.get(f"/api/v1/farms/{farm.id}")
    assert resp.status_code == 401


async def test_create_farm_requires_auth(noauth_client: AsyncClient):
    resp = await noauth_client.post("/api/v1/farms", json={"name": "Hacked"})
    assert resp.status_code == 401


async def test_update_farm_requires_auth(noauth_client: AsyncClient, db: AsyncSession):
    owner = await _make_user(db, "owner")
    farm = await _make_farm(db, owner)
    resp = await noauth_client.put(f"/api/v1/farms/{farm.id}", json={"name": "Hacked"})
    assert resp.status_code == 401


# ── 401 — malformed / expired tokens ─────────────────────────────────────────

async def test_garbage_token_rejected(noauth_client: AsyncClient):
    resp = await noauth_client.get("/api/v1/farms", headers=_bearer("not.a.jwt"))
    assert resp.status_code == 401


async def test_expired_token_rejected(noauth_client: AsyncClient, db: AsyncSession):
    user = await _make_user(db, "expired")
    payload = {
        "sub": user.id,
        "iat": datetime.now(UTC) - timedelta(hours=48),
        "exp": datetime.now(UTC) - timedelta(hours=24),
    }
    token = jwt.encode(payload, get_settings().SECRET_KEY, algorithm="HS256")
    resp = await noauth_client.get("/api/v1/farms", headers=_bearer(token))
    assert resp.status_code == 401


async def test_token_signed_with_wrong_key_rejected(noauth_client: AsyncClient, db: AsyncSession):
    user = await _make_user(db, "wrongkey")
    token = jwt.encode({"sub": user.id}, "wrong-secret", algorithm="HS256")
    resp = await noauth_client.get("/api/v1/farms", headers=_bearer(token))
    assert resp.status_code == 401


# ── ownership isolation ───────────────────────────────────────────────────────

async def test_user_cannot_see_other_users_farm(noauth_client: AsyncClient, db: AsyncSession):
    alice = await _make_user(db, "alice")
    bob = await _make_user(db, "bob")
    bobs_farm = await _make_farm(db, bob)

    resp = await noauth_client.get(f"/api/v1/farms/{bobs_farm.id}", headers=_bearer(create_access_token(alice.id)))
    assert resp.status_code == 404


async def test_list_farms_only_returns_own_farms(noauth_client: AsyncClient, db: AsyncSession):
    alice = await _make_user(db, "alice-list")
    bob = await _make_user(db, "bob-list")
    alices_farm = await _make_farm(db, alice)
    bobs_farm = await _make_farm(db, bob)

    resp = await noauth_client.get("/api/v1/farms", headers=_bearer(create_access_token(alice.id)))
    assert resp.status_code == 200
    ids = [f["id"] for f in resp.json()["items"]]
    assert alices_farm.id in ids
    assert bobs_farm.id not in ids


async def test_user_cannot_update_other_users_farm(noauth_client: AsyncClient, db: AsyncSession):
    alice = await _make_user(db, "alice-upd")
    bob = await _make_user(db, "bob-upd")
    bobs_farm = await _make_farm(db, bob)

    resp = await noauth_client.put(
        f"/api/v1/farms/{bobs_farm.id}",
        json={"name": "Stolen"},
        headers=_bearer(create_access_token(alice.id)),
    )
    assert resp.status_code == 404


async def test_user_cannot_read_other_users_dashboard(
    noauth_client: AsyncClient,
    db: AsyncSession,
):
    alice = await _make_user(db, "alice-dashboard")
    bob = await _make_user(db, "bob-dashboard")
    bobs_farm = await _make_farm(db, bob)

    resp = await noauth_client.get(
        f"/api/v1/farms/{bobs_farm.id}/dashboard",
        headers=_bearer(create_access_token(alice.id)),
    )
    assert resp.status_code == 404


async def test_user_cannot_traverse_other_users_nested_resources(
    noauth_client: AsyncClient,
    db: AsyncSession,
):
    alice = await _make_user(db, "alice-nested")
    bob = await _make_user(db, "bob-nested")
    bobs_farm, bobs_plot, bobs_sector = await _make_sector_tree(db, bob)
    probe = Probe(id=new_uuid(), sector_id=bobs_sector.id, external_id=f"probe-{uuid.uuid4()}")
    db.add(probe)
    await db.commit()

    token = _bearer(create_access_token(alice.id))
    checks = [
        f"/api/v1/farms/{bobs_farm.id}/plots",
        f"/api/v1/plots/{bobs_plot.id}",
        f"/api/v1/plots/{bobs_plot.id}/sectors",
        f"/api/v1/sectors/{bobs_sector.id}",
        f"/api/v1/sectors/{bobs_sector.id}/probes",
        f"/api/v1/probes/{probe.id}",
    ]
    for path in checks:
        resp = await noauth_client.get(path, headers=token)
        assert resp.status_code == 404, path


async def test_user_cannot_mutate_other_users_recommendation(
    noauth_client: AsyncClient,
    db: AsyncSession,
):
    alice = await _make_user(db, "alice-rec")
    bob = await _make_user(db, "bob-rec")
    _, _, bobs_sector = await _make_sector_tree(db, bob)
    rec = Recommendation(
        id=new_uuid(),
        sector_id=bobs_sector.id,
        generated_at=datetime.now(UTC),
        target_date=date.today(),
        action="skip",
        confidence_score=0.8,
        confidence_level="medium",
        inputs_snapshot={},
        computation_log={},
    )
    db.add(rec)
    await db.commit()

    resp = await noauth_client.post(
        f"/api/v1/recommendations/{rec.id}/accept",
        json={"notes": "should not work"},
        headers=_bearer(create_access_token(alice.id)),
    )
    assert resp.status_code == 404


async def test_user_cannot_mutate_other_users_alert_or_irrigation_event(
    noauth_client: AsyncClient,
    db: AsyncSession,
):
    alice = await _make_user(db, "alice-mutate")
    bob = await _make_user(db, "bob-mutate")
    bobs_farm, _, bobs_sector = await _make_sector_tree(db, bob)
    alert = Alert(
        id=new_uuid(),
        farm_id=bobs_farm.id,
        sector_id=bobs_sector.id,
        alert_type="missing_data",
        severity="warning",
        title_pt="Aviso",
        title_en="Warning",
        description_pt="Descricao",
        description_en="Description",
    )
    event = IrrigationEvent(
        id=new_uuid(),
        sector_id=bobs_sector.id,
        start_time=datetime.now(UTC),
        source="manual",
    )
    db.add_all([alert, event])
    await db.commit()

    token = _bearer(create_access_token(alice.id))
    alert_resp = await noauth_client.post(f"/api/v1/alerts/{alert.id}/resolve", headers=token)
    event_resp = await noauth_client.put(
        f"/api/v1/irrigation-events/{event.id}",
        json={"notes": "should not work"},
        headers=token,
    )
    assert alert_resp.status_code == 404
    assert event_resp.status_code == 404


async def test_audit_log_requires_admin(noauth_client: AsyncClient, db: AsyncSession):
    user = await _make_user(db, "audit-nonadmin")
    resp = await noauth_client.get(
        "/api/v1/audit-log",
        headers=_bearer(create_access_token(user.id)),
    )
    assert resp.status_code == 404


# ── login endpoint ─────────────────────────────────────────────────────────────

async def test_login_returns_token(noauth_client: AsyncClient, db: AsyncSession):
    user = await _make_user(db, "login-ok")
    raw_password = "hunter2-" + user.id
    resp = await noauth_client.post(
        "/api/v1/auth/token",
        data={"username": user.email, "password": raw_password},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "access_token" in body
    assert body["token_type"] == "bearer"


async def test_login_wrong_password_returns_401(noauth_client: AsyncClient, db: AsyncSession):
    user = await _make_user(db, "login-bad")
    resp = await noauth_client.post(
        "/api/v1/auth/token",
        data={"username": user.email, "password": "wrong"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert resp.status_code == 401


async def test_login_unknown_email_returns_401(noauth_client: AsyncClient):
    resp = await noauth_client.post(
        "/api/v1/auth/token",
        data={"username": "nobody@irrigai.test", "password": "anything"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert resp.status_code == 401


# ── register endpoint ─────────────────────────────────────────────────────────

async def test_register_creates_user_and_returns_token(noauth_client: AsyncClient):
    uid = uuid.uuid4()
    resp = await noauth_client.post("/api/v1/auth/register", json={
        "email": f"new-{uid}@irrigai.test",
        "name": "New User",
        "password": "Passw0rd!",
    })
    assert resp.status_code == 201
    assert "access_token" in resp.json()


async def test_duplicate_register_returns_409(noauth_client: AsyncClient, db: AsyncSession):
    user = await _make_user(db, "dup-reg")
    resp = await noauth_client.post("/api/v1/auth/register", json={
        "email": user.email,
        "name": "Dupe",
        "password": "Passw0rd!",
    })
    assert resp.status_code == 409


async def test_authenticated_request_succeeds(noauth_client: AsyncClient, db: AsyncSession):
    user = await _make_user(db, "authed")
    farm = await _make_farm(db, user)
    resp = await noauth_client.get(f"/api/v1/farms/{farm.id}", headers=_bearer(create_access_token(user.id)))
    assert resp.status_code == 200
    assert resp.json()["id"] == farm.id


# ── global auth: previously-unprotected data endpoints now require auth ─────────

@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/sectors/00000000-0000-0000-0000-000000000000",
        "/api/v1/probes/00000000-0000-0000-0000-000000000000",
        "/api/v1/recommendations/00000000-0000-0000-0000-000000000000",
        "/api/v1/farms/00000000-0000-0000-0000-000000000000/dashboard",
    ],
)
async def test_data_endpoints_require_auth(noauth_client: AsyncClient, path: str):
    """Every v1 resource endpoint (not just /farms) must reject anonymous access.

    Auth runs as a router-level dependency before the handler, so even a
    non-existent resource id returns 401 (not 404) when unauthenticated."""
    resp = await noauth_client.get(path)
    assert resp.status_code == 401, f"{path} returned {resp.status_code}, expected 401"
