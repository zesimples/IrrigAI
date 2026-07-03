import inspect

from app.engine.pipeline import build_weather_context


def test_build_weather_context_accepts_plot_id():
    assert "plot_id" in inspect.signature(build_weather_context).parameters
