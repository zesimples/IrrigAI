# Task: Fix MyIrrigation weather project_id resolution (per-farm + auto-detect)

**Status:** Queued (not started)
**Filed:** 2026-06-17

## Context

Weather **forecast** comes from `GET /data/projects/{project_id}/weather_forecast/detailed`
(`adapters/myirrigation.py::fetch_forecast` → `_get_weather_project_id`). Two latent bugs
surfaced while debugging a (transient) forecast 404.

> Note: the 404 itself was transient — today's forecast model run hadn't published when
> ingestion ran (`modelrun_updatetime_utc 10:04`); project 1044 returns 200 once it's up,
> and `fetch_forecast` already degrades gracefully (returns `[]`). No fix needed for that.

## Bug 1 — auto-detect picks the wrong project

`_get_weather_project_id()` falls back to `projects[0]` when `MYIRRIGATION_PROJECT_ID` is
unset. The project list has grown and `projects[0]` is now an **unrelated** project:

```
get_projects() → [(1491,'CASTELO DE VIDE'), (763,'DIVINER ESPORÃO'), (764,'DIVINER PERDIGÕES'),
                  (1288,'ESPORÃO - NIVEL BARRAGEM'), (1044,'ESPORÃO OLIVAL'), (604,'ESPORÃO VINHA'),
                  (598,'PERDIGÕES VINHA'), (602,'PORTALEGRE'), (1129,'PRECIPITAÇÃO'),
                  (1575,'QUINTA DO AMEAL'), ...]
```

`/data/projects/1491/weather_forecast/detailed` → **406 `{"errors":["Feature not enabled"]}`**.
So without the env pin, weather forecast silently breaks. Picking `projects[0]` is unsafe.

## Bug 2 — single global project_id for all farms

`project_id` is sourced from the **global** `MYIRRIGATION_PROJECT_ID` (currently `1044` =
Esporão's "ESPORÃO OLIVAL"). `FarmCredentials` has no per-farm project id, so **Conqueiros
and Amêndoas do Lago would fetch Esporão's forecast** (1044). Weather is farm/location
specific — each farm needs its own project.

## Fix

1. Add a **per-farm `myirrigation_project_id`** (e.g. a column on `FarmCredentials`, set via
   `scripts/set_farm_credentials.py`); thread it into the adapter per farm.
2. Replace the `projects[0]` fallback with a **deliberate match** (e.g. by project name /
   configured mapping) and **fail loudly / skip forecast** if it can't be resolved, instead
   of silently using an unrelated project.
3. Confirm the correct project per farm with the user (Esporão → 1044 `ESPORÃO OLIVAL`;
   Conqueiros / ADL → TBD from their `get_projects()`).

## Acceptance criteria

- Each farm's forecast uses its own MyIrrigation project.
- With no env/DB project id configured, the adapter does not silently fetch a wrong
  project's forecast (logs + skips, or errors clearly).
- Esporão weather forecast populates `weather_observation`/forecast as before.
