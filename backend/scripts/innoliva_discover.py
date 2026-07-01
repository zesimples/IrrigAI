"""Innoliva onboarding — MyIrrigation device discovery & serial matching.

READ-ONLY. Authenticates with Innoliva credentials, lists projects + devices,
and matches the 77 sector serials below to their {project_id}/{device_id}
external_id. Writes nothing to the DB and does not touch the running config.

Credentials come from env vars (so the live Esporão MYIRRIGATION_* stay intact):

    INNOLIVA_USERNAME       INNOLIVA_CLIENT_ID
    INNOLIVA_PASSWORD       INNOLIVA_CLIENT_SECRET
    INNOLIVA_BASE_URL       (optional, default https://api.myirrigation.eu/api/v1)

Run inside the backend container:

    docker compose exec \
      -e INNOLIVA_USERNAME=... -e INNOLIVA_PASSWORD=... \
      -e INNOLIVA_CLIENT_ID=... -e INNOLIVA_CLIENT_SECRET=... \
      backend python scripts/innoliva_discover.py
"""

from __future__ import annotations

import asyncio
import os
import re

# (polo, sector_name, serial) — verbatim from the onboarding list.
SECTORS: list[tuple[str, str, str]] = [
    # Polo de Conceição
    ("Conceição", "Bussalfão UPC1", "SM005119"),
    ("Conceição", "Bussalfão UPC3", "SM005072"),
    ("Conceição", "Bussalfão UPC5", "SM005064"),
    ("Conceição", "Herdade de Sousa UPC2 (Arbequina)", "SM005098"),
    ("Conceição", "Herdade de Sousa UPC3 (Arbequina)", "SM005101"),
    ("Conceição", "Herdade de Sousa UPC4 (Cobrançosa)", "SM005099"),
    ("Conceição", "Herdade de Sousa UPC5 (Picoal)", "SM005100"),
    ("Conceição", "Monte das Oliveiras", "0020347E"),
    ("Conceição", "Monte das Oliveiras 1", "SM005107"),
    ("Conceição", "Monte das Oliveiras 2", "SM005115"),
    ("Conceição", "Monte das Oliveiras 3", "SM005128"),
    ("Conceição", "Musgos", "03110794"),
    ("Conceição", "Musgos 2 UPC3", "SM005208"),
    # Polo de Covadonga
    ("Covadonga", "Carapetal C55 Sul", "00203D0E"),
    ("Covadonga", "Carapetal Este UPC6", "SM005067"),
    ("Covadonga", "Carapetal Este UPC7", "SM005116"),
    ("Covadonga", "Carapetal Lagar C04 Sul", "0020348A"),
    ("Covadonga", "Carapetal Oeste UPC4", "SM005207"),
    ("Covadonga", "Carapetal Oeste UPC5", "SM005201"),
    ("Covadonga", "Fontainhas F05 Norte", "0020348B"),
    ("Covadonga", "Fontainhas S03 Ensaio Aquagri", "0020359D"),
    ("Covadonga", "Fontainhas S03 Ensaio Innoliva", "00203595"),
    ("Covadonga", "Fontainhas S1", "SM005199"),
    ("Covadonga", "Fontainhas S2", "SM005196"),
    ("Covadonga", "Fontainhas UPC2", "SM005203"),
    ("Covadonga", "Pardieiro Novo", "031107C3"),
    ("Covadonga", "Pardieiro P29 Norte", "0020348D"),
    ("Covadonga", "Pardieiro UPC10", "SM005202"),
    ("Covadonga", "Sargaçal", "SM005069"),
    ("Covadonga", "Sargaçal 2", "03110792"),
    # Polo de Fátima
    ("Fátima", "Charnequinha", "031107AD"),
    ("Fátima", "Gasparões", "SM005080"),
    ("Fátima", "Lagoa", "03110793"),
    ("Fátima", "Lagoa T1", "SM005070"),
    ("Fátima", "Monte Espada UPC1", "SM005198"),
    ("Fátima", "Montespada ME20 Sul", "01204518"),
    ("Fátima", "Pedralva Nova", "031107B6"),
    ("Fátima", "Pedralva Nova T1", "SM005085"),
    ("Fátima", "Pedralva Nova T3", "SM005094"),
    ("Fátima", "Pedralva P10 Norte", "00203A34"),
    ("Fátima", "São João SJ39 Sul", "00203482"),
    ("Fátima", "São João T1", "SM005068"),
    ("Fátima", "São João T4", "SM005083"),
    ("Fátima", "Sesmarias 2", "SM005205"),
    ("Fátima", "Sesmarias SM03 Norte", "00203489"),
    # Polo de Guadalupe
    ("Guadalupe", "Guadalupe Norte", "00203485"),
    ("Guadalupe", "Guadalupe Sul", "0020347F"),
    # Polo de Rocio
    ("Rocio", "Chaminé", "0020348E"),
    ("Rocio", "Chaminé 2 UPC1", "SM005056"),
    ("Rocio", "Chaminé 3 UPC3", "SM005063"),
    ("Rocio", "Farrobo", "031107B4"),
    ("Rocio", "Farrobo 2 UPC2", "SM005118"),
    ("Rocio", "Farrobo 3 UPC4", "SM005093"),
    ("Rocio", "Gregas", "SM005143"),
    ("Rocio", "Matosa", "031107BE"),
    ("Rocio", "Matosa 3", "SM005077"),
    ("Rocio", "Matosa 4", "SM005120"),
    ("Rocio", "Misericordia", "00203486"),
    ("Rocio", "Misericórdia 2 UPC1", "SM005159"),
    ("Rocio", "Misericórdia 3 UPC3", "SM005075"),
    ("Rocio", "Monforte", "031107C2"),
    ("Rocio", "Monforte 2 UPC1", "SM005126"),
    ("Rocio", "Monforte 3 UPC4", "SM005104"),
    ("Rocio", "Prado", "002035A4"),
    # Polo do Carmo
    ("Carmo", "Broeira", "031107AE"),
    ("Carmo", "Broeira P10 T2", "SM005092"),
    ("Carmo", "Broeira P36 T3", "SM005087"),
    ("Carmo", "Cailogo CL10 Norte", "0020348F"),
    ("Carmo", "Cailogo P24 T3", "SM005095"),
    ("Carmo", "Cascalho CAS Norte", "00203484"),
    ("Carmo", "Cascalho P26 T2", "SM005090"),
    ("Carmo", "Cebolinho", "031107A4"),
    ("Carmo", "Courela P47 T4", "SM005108"),
    ("Carmo", "Malhada Velha", "031107BF"),
    ("Carmo", "Malhada Velha PN6 T1", "SM005078"),
    ("Carmo", "Mosaico M20 Sul", "0120AB02"),
    ("Carmo", "Mosaico P8 T2", "SM005125"),
]


# Polo → MyIrrigation project_id (confirmed via GET /data/projects). Device
# objects carry no project_id, so external_id uses the sector's polo project.
POLO_PROJECT: dict[str, str] = {
    "Conceição": "170",
    "Covadonga": "167",
    "Fátima": "168",
    "Guadalupe": "171",
    "Rocio": "554",
    "Carmo": "169",
}


def _norm(s: object) -> str:
    """Uppercase, strip non-alphanumerics — tolerant serial comparison."""
    return re.sub(r"[^A-Z0-9]", "", str(s or "").upper())


def _device_serial_candidates(dev: dict) -> set[str]:
    """All fields on a device that could carry the printed serial."""
    fields = ("serial", "serial_number", "serialNumber", "name", "imei",
              "device_serial", "code", "reference", "label")
    vals = {_norm(dev.get(f)) for f in fields if dev.get(f) not in (None, "")}
    # Also scan every top-level string value as a fallback.
    for v in dev.values():
        if isinstance(v, str):
            vals.add(_norm(v))
    vals.discard("")
    return vals


async def main() -> None:
    user = os.environ.get("INNOLIVA_USERNAME")
    pw = os.environ.get("INNOLIVA_PASSWORD")
    cid = os.environ.get("INNOLIVA_CLIENT_ID", "")
    csec = os.environ.get("INNOLIVA_CLIENT_SECRET", "")
    base = os.environ.get("INNOLIVA_BASE_URL", "https://api.myirrigation.eu/api/v1")

    if not user or not pw:
        print("ERROR: set INNOLIVA_USERNAME and INNOLIVA_PASSWORD (and client id/secret).")
        return

    from app.adapters.myirrigation import MyIrrigationAdapter

    adapter = MyIrrigationAdapter(
        base_url=base, username=user, password=pw,
        client_id=cid, client_secret=csec,
    )

    print(f"[1] Authenticating at {base} ...")
    await adapter.authenticate()
    print("    OK")

    print("[2] Listing projects ...")
    projects = await adapter.get_projects()
    proj_name = {str(p.get("id")): p.get("name") for p in projects}
    print(f"    {len(projects)} project(s):")
    for p in projects:
        print(f"      • id={p.get('id')}  name={p.get('name')!r}")

    print("[3] Listing devices ...")
    devices = await adapter.get_devices()
    print(f"    {len(devices)} device(s)")

    # Build serial -> device index (a serial may appear on multiple fields).
    index: dict[str, list[dict]] = {}
    for dev in devices:
        for cand in _device_serial_candidates(dev):
            index.setdefault(cand, []).append(dev)

    print("\n" + "=" * 100)
    print(f"{'POLO':<11}{'SECTOR':<38}{'SERIAL':<11}{'PROJECT':<9}{'DEVICE':<8}EXTERNAL_ID")
    print("-" * 100)

    matched, unmatched = 0, []
    used_device_ids: set[str] = set()
    csv_rows: list[str] = ["polo,project_id,sector_name,serial,device_id,device_name,external_id"]
    for polo, name, serial in SECTORS:
        hits = index.get(_norm(serial), [])
        if not hits:
            unmatched.append((polo, name, serial))
            print(f"{polo:<11}{name[:37]:<38}{serial:<11}{'—':<9}{'—':<8}NOT FOUND")
            continue
        dev = hits[0]
        did = str(dev.get("id"))
        pid = POLO_PROJECT.get(polo, str(dev.get("project_id")))
        used_device_ids.add(did)
        ext = f"{pid}/{did}"
        flag = "  ⚠ multiple" if len(hits) > 1 else ""
        print(f"{polo:<11}{name[:37]:<38}{serial:<11}{pid:<9}{did:<8}{ext}{flag}")
        dev_name = str(dev.get("name", "")).replace(",", " ")
        csv_rows.append(f"{polo},{pid},{name.replace(',', ' ')},{serial},{did},{dev_name},{ext}")
        matched += 1

    out_path = os.environ.get("INNOLIVA_CSV_OUT")
    if out_path:
        with open(out_path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(csv_rows) + "\n")
        print(f"\nWrote {matched}-row mapping CSV → {out_path}")

    print("=" * 100)
    print(f"\nMatched {matched}/{len(SECTORS)} sectors.")
    if unmatched:
        print(f"\n{len(unmatched)} UNMATCHED serial(s):")
        for polo, name, serial in unmatched:
            print(f"  • [{polo}] {name} :: {serial}")

    extra = [d for d in devices if str(d.get("id")) not in used_device_ids]
    if extra:
        print(f"\n{len(extra)} device(s) on the account NOT in the list:")
        for d in extra:
            pid = str(d.get("project_id"))
            print(f"  • id={d.get('id')} project={pid} ({proj_name.get(pid)}) "
                  f"name={d.get('name')!r} serial={d.get('serial') or d.get('serial_number')!r}")


if __name__ == "__main__":
    asyncio.run(main())
