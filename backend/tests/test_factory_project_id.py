import types

from app.adapters import factory
from app.config import get_settings


def _farm_with_creds(project_id, weather_device_id):
    creds = types.SimpleNamespace(
        username="u", password="p", client_id="c", client_secret="s",
        project_id=project_id, weather_device_id=weather_device_id,
    )
    return types.SimpleNamespace(credentials=creds)


def test_weather_provider_uses_farm_project_id(monkeypatch):
    cfg = get_settings()
    monkeypatch.setattr(cfg, "WEATHER_PROVIDER", "myirrigation")
    factory._myirrigation_cache.clear()
    adapter = factory.get_weather_provider(cfg, farm=_farm_with_creds("167", "574"))
    assert adapter._project_id == "167"
    assert adapter._weather_device_id == "574"


def test_probe_provider_uses_farm_project_id(monkeypatch):
    cfg = get_settings()
    monkeypatch.setattr(cfg, "PROBE_PROVIDER", "myirrigation")
    factory._myirrigation_cache.clear()
    adapter = factory.get_probe_provider(cfg, farm=_farm_with_creds("170", None))
    assert adapter._project_id == "170"
