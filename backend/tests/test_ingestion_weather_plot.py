import inspect
from app.services import ingestion


def test_weather_ingest_accepts_plot_scope():
    for fn in (ingestion.ingest_weather_observations, ingestion.ingest_weather_forecasts):
        params = inspect.signature(fn).parameters
        assert "plot_id" in params
        assert "project_id" in params
        assert "weather_device_id" in params
