"""MyIrrigation discovery tool.

Run after filling MYIRRIGATION_* credentials in .env to verify connectivity
and list available projects and devices.

Usage (inside the container):
    docker compose exec backend python -m app.tools.myirrigation_discover

Or locally (with a venv and deps installed):
    python -m app.tools.myirrigation_discover
"""

import asyncio
import json


async def main() -> None:
    from app.config import get_settings
    cfg = get_settings()

    if not cfg.MYIRRIGATION_USERNAME or not cfg.MYIRRIGATION_PASSWORD:
        print("ERROR: Set MYIRRIGATION_USERNAME and MYIRRIGATION_PASSWORD in .env first.")
        return

    from app.adapters.myirrigation import MyIrrigationAdapter
    adapter = MyIrrigationAdapter(
        base_url=cfg.MYIRRIGATION_BASE_URL,
        username=cfg.MYIRRIGATION_USERNAME,
        password=cfg.MYIRRIGATION_PASSWORD,
        client_id=cfg.MYIRRIGATION_CLIENT_ID,
        client_secret=cfg.MYIRRIGATION_CLIENT_SECRET,
    )

    # ── Step 1: Authenticate ───────────────────────────────────────────────────
    print(f"\n[1] Authenticating at {cfg.MYIRRIGATION_BASE_URL} ...")
    try:
        await adapter.authenticate()
        print("    OK — token obtained")
    except Exception as exc:
        print(f"    ERROR: {exc}")
        return

    # ── Step 2: List projects ──────────────────────────────────────────────────
    print("\n[2] Listing projects ...")
    try:
        projects = await adapter.get_projects()
    except Exception as exc:
        print(f"    ERROR: {exc}")
        return

    if not projects:
        print("    No projects found.")
    else:
        for p in projects:
            print(f"    • id={p.get('id')}  name={p.get('name')!r}")

    # ── Step 3: List devices ───────────────────────────────────────────────────
    print("\n[3] Listing devices ...")
    try:
        devices = await adapter.get_devices()
    except Exception as exc:
        print(f"    ERROR: {exc}")
        return

    if not devices:
        print("    No devices found.")
    else:
        print(f"\n    Found {len(devices)} device(s):\n")
        for dev in devices:
            device_id = dev.get("id", "?")
            project_id = dev.get("project_id", "?")
            name = dev.get("name", "unnamed")
            external_id = f"{project_id}/{device_id}"
            print(f"    • {name}  (id={device_id}, project={project_id})")
            print(f"        probe external_id → \"{external_id}\"")
        print()

    # ── Summary ────────────────────────────────────────────────────────────────
    print("─" * 60)
    print("NEXT STEPS:")
    print("  1. Confirm PROBE_PROVIDER=myirrigation in .env")
    print("  2. For each device you want to track, create a Probe")
    print("     in IrrigAI with external_id = \"{project_id}/{device_id}\"")
    print("     (use the external_id values printed above)")
    print("  3. Set:  PROBE_PROVIDER=myirrigation  WEATHER_PROVIDER=myirrigation")
    print("  4. Restart the backend container.")
    print("─" * 60)


if __name__ == "__main__":
    asyncio.run(main())
