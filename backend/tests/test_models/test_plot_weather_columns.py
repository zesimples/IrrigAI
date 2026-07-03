from app.models import Plot, WeatherObservation, WeatherForecast


def test_plot_has_weather_config_columns():
    p = Plot(farm_id="f", name="P", myirrigation_project_id="167", weather_device_id="574")
    assert p.myirrigation_project_id == "167"
    assert p.weather_device_id == "574"
    assert "myirrigation_project_id" in Plot.__table__.columns
    assert "weather_device_id" in Plot.__table__.columns


def test_weather_tables_have_plot_id():
    assert "plot_id" in WeatherObservation.__table__.columns
    assert "plot_id" in WeatherForecast.__table__.columns
    assert WeatherObservation.__table__.columns["plot_id"].nullable
    assert WeatherForecast.__table__.columns["plot_id"].nullable
