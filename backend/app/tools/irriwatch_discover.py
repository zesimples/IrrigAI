"""IrriWatch discovery tool.

Run this after filling IRRIWATCH_CLIENT_ID and IRRIWATCH_CLIENT_SECRET in .env
to discover your company UUID and available order/field names.

Usage (inside the container):
    docker compose exec backend python -m app.tools.irriwatch_discover

Or locally (if you have a venv with deps installed):
    python -m app.tools.irriwatch_discover
"""

import asyncio
import json

import httpx


async def main() -> None:
    from app.config import get_settings
    cfg = get_settings()

    if not cfg.IRRIWATCH_CLIENT_ID or not cfg.IRRIWATCH_CLIENT_SECRET:
        print("ERROR: Set IRRIWATCH_CLIENT_ID and IRRIWATCH_CLIENT_SECRET in .env first.")
        return

    base_url = cfg.IRRIWATCH_BASE_URL.rstrip("/")

    # ── Step 1: Authenticate ───────────────────────────────────────────────────
    print(f"\n[1] Authenticating at {base_url} ...")
    token = None
    for path in ["/oauth/v2/token", "/oauth2/v2/token"]:
        url = base_url + path
        async with httpx.AsyncClient(timeout=15) as client:
            try:
                resp = await client.post(
                    url,
                    data={
                        "grant_type": "client_credentials",
                        "client_id": cfg.IRRIWATCH_CLIENT_ID,
                        "client_secret": cfg.IRRIWATCH_CLIENT_SECRET,
                    },
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
                if resp.status_code < 400:
                    token = resp.json()["access_token"]
                    print(f"    OK — token endpoint: {url}")
                    break
                else:
                    print(f"    {url} → HTTP {resp.status_code}")
            except Exception as e:
                print(f"    {url} → error: {e}")

    if not token:
        print("ERROR: Authentication failed. Check your credentials.")
        return

    headers = {"Authorization": f"Bearer {token}"}

    # ── Step 2: List companies ─────────────────────────────────────────────────
    print("\n[2] Listing companies ...")
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(f"{base_url}/api/v1/company", headers=headers)
        companies = resp.json()

    if not companies:
        print("    No companies found.")
        return

    for c in companies:
        print(f"    • {c.get('name')}  →  UUID: {c.get('uuid')}")

    # Use first company (or the one already configured)
    company_uuid = cfg.IRRIWATCH_COMPANY_UUID or companies[0]["uuid"]
    print(f"\n    Using company UUID: {company_uuid}")
    print(f"    → Set IRRIWATCH_COMPANY_UUID={company_uuid} in .env")

    # ── Step 3: List orders ────────────────────────────────────────────────────
    print(f"\n[3] Listing orders for company {company_uuid} ...")
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            f"{base_url}/api/v1/company/{company_uuid}/order", headers=headers
        )
        orders = resp.json()

    if not orders:
        print("    No orders found.")
        return

    print(f"\n    Found {len(orders)} order(s):\n")
    for order in orders:
        order_uuid = order.get("uuid", "")
        state = order.get("state", "unknown")
        subscription = order.get("subscription_type", "")
        geojson = order.get("fields", {})
        features = geojson.get("features", []) if isinstance(geojson, dict) else []
        field_names = [
            f.get("properties", {}).get("name") or f.get("properties", {}).get("id", "?")
            for f in features
        ]

        print(f"    Order: {order_uuid}  [{state}] [{subscription}]")
        if field_names:
            print(f"    Fields ({len(field_names)}):")
            for name in field_names:
                external_id = f"{order_uuid}/{name}"
                print(f"      • {name}")
                print(f"        probe external_id → \"{external_id}\"")
        print()

    # ── Summary ───────────────────────────────────────────────────────────────
    print("─" * 60)
    print("NEXT STEPS:")
    print(f"  1. Set in .env:  IRRIWATCH_COMPANY_UUID={company_uuid}")
    print("  2. For each IrriWatch field you want to track, create a Probe")
    print("     in IrrigAI with external_id = \"{order_uuid}/{field_name}\"")
    print("     (use the probe external_id values printed above)")
    print("  3. Set:  PROBE_PROVIDER=irriwatch  WEATHER_PROVIDER=irriwatch")
    print("  4. Restart the backend container.")
    print("─" * 60)


if __name__ == "__main__":
    asyncio.run(main())
