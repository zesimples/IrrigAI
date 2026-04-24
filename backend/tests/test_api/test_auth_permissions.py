"""API auth and permission tests.

Exit criteria:
- Unauthenticated requests to protected endpoints → 401
- Invalid / expired tokens → 401
- User A cannot read, write, or list resources owned by user B → 404 / empty list
- A failing permission check breaks CI (these tests are in the full test run)
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from jose import jwt
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import create_access_token, hash_password
from app.config import get_settings
from app.models.base import new_uuid
from app.models.farm import Farm
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


# ── 401 — unauthenticated ─────────────────────────────────────────────────────

async def test_list_farms_requires_auth(client: AsyncClient):
    resp = await client.get("/api/v1/farms")
    assert resp.status_code == 401


async def test_get_farm_requires_auth(client: AsyncClient, db: AsyncSession):
    owner = await _make_user(db, "owner")
    farm = await _make_farm(db, owner)
    resp = await client.get(f"/api/v1/farms/{farm.id}")
    assert resp.status_code == 401


async def test_create_farm_requires_auth(client: AsyncClient):
    resp = await client.post("/api/v1/farms", json={"name": "Hacked"})
    assert resp.status_code == 401


async def test_update_farm_requires_auth(client: AsyncClient, db: AsyncSession):
    owner = await _make_user(db, "owner")
    farm = await _make_farm(db, owner)
    resp = await client.put(f"/api/v1/farms/{farm.id}", json={"name": "Hacked"})
    assert resp.status_code == 401


# ── 401 — malformed / expired tokens ─────────────────────────────────────────

async def test_garbage_token_rejected(client: AsyncClient):
    resp = await client.get("/api/v1/farms", headers=_bearer("not.a.jwt"))
    assert resp.status_code == 401


async def test_expired_token_rejected(client: AsyncClient, db: AsyncSession):
    user = await _make_user(db, "expired")
    payload = {
        "sub": user.id,
        "iat": datetime.now(UTC) - timedelta(hours=48),
        "exp": datetime.now(UTC) - timedelta(hours=24),
    }
    token = jwt.encode(payload, get_settings().SECRET_KEY, algorithm="HS256")
    resp = await client.get("/api/v1/farms", headers=_bearer(token))
    assert resp.status_code == 401


async def test_token_signed_with_wrong_key_rejected(client: AsyncClient, db: AsyncSession):
    user = await _make_user(db, "wrongkey")
    token = jwt.encode({"sub": user.id}, "wrong-secret", algorithm="HS256")
    resp = await client.get("/api/v1/farms", headers=_bearer(token))
    assert resp.status_code == 401


# ── ownership isolation ───────────────────────────────────────────────────────

async def test_user_cannot_see_other_users_farm(client: AsyncClient, db: AsyncSession):
    alice = await _make_user(db, "alice")
    bob = await _make_user(db, "bob")
    bobs_farm = await _make_farm(db, bob)

    resp = await client.get(f"/api/v1/farms/{bobs_farm.id}", headers=_bearer(create_access_token(alice.id)))
    assert resp.status_code == 404


async def test_list_farms_only_returns_own_farms(client: AsyncClient, db: AsyncSession):
    alice = await _make_user(db, "alice-list")
    bob = await _make_user(db, "bob-list")
    alices_farm = await _make_farm(db, alice)
    bobs_farm = await _make_farm(db, bob)

    resp = await client.get("/api/v1/farms", headers=_bearer(create_access_token(alice.id)))
    assert resp.status_code == 200
    ids = [f["id"] for f in resp.json()["items"]]
    assert alices_farm.id in ids
    assert bobs_farm.id not in ids


async def test_user_cannot_update_other_users_farm(client: AsyncClient, db: AsyncSession):
    alice = await _make_user(db, "alice-upd")
    bob = await _make_user(db, "bob-upd")
    bobs_farm = await _make_farm(db, bob)

    resp = await client.put(
        f"/api/v1/farms/{bobs_farm.id}",
        json={"name": "Stolen"},
        headers=_bearer(create_access_token(alice.id)),
    )
    assert resp.status_code == 404


# ── login endpoint ─────────────────────────────────────────────────────────────

async def test_login_returns_token(client: AsyncClient, db: AsyncSession):
    user = await _make_user(db, "login-ok")
    raw_password = "hunter2-" + user.id
    resp = await client.post(
        "/api/v1/auth/token",
        data={"username": user.email, "password": raw_password},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "access_token" in body
    assert body["token_type"] == "bearer"


async def test_login_wrong_password_returns_401(client: AsyncClient, db: AsyncSession):
    user = await _make_user(db, "login-bad")
    resp = await client.post(
        "/api/v1/auth/token",
        data={"username": user.email, "password": "wrong"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert resp.status_code == 401


async def test_login_unknown_email_returns_401(client: AsyncClient):
    resp = await client.post(
        "/api/v1/auth/token",
        data={"username": "nobody@irrigai.test", "password": "anything"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert resp.status_code == 401


# ── register endpoint ─────────────────────────────────────────────────────────

async def test_register_creates_user_and_returns_token(client: AsyncClient):
    uid = uuid.uuid4()
    resp = await client.post("/api/v1/auth/register", json={
        "email": f"new-{uid}@irrigai.test",
        "name": "New User",
        "password": "Passw0rd!",
    })
    assert resp.status_code == 201
    assert "access_token" in resp.json()


async def test_duplicate_register_returns_409(client: AsyncClient, db: AsyncSession):
    user = await _make_user(db, "dup-reg")
    resp = await client.post("/api/v1/auth/register", json={
        "email": user.email,
        "name": "Dupe",
        "password": "Passw0rd!",
    })
    assert resp.status_code == 409


async def test_authenticated_request_succeeds(client: AsyncClient, db: AsyncSession):
    user = await _make_user(db, "authed")
    farm = await _make_farm(db, user)
    resp = await client.get(f"/api/v1/farms/{farm.id}", headers=_bearer(create_access_token(user.id)))
    assert resp.status_code == 200
    assert resp.json()["id"] == farm.id
