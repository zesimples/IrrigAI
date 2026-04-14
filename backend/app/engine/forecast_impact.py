"""Forecast impact assessment.

Examines the weather forecast to:
- Detect upcoming rain that would justify delaying irrigation
- Flag heat stress periods
- Compute effective rain expected in next 48h
"""

from app.engine.types import DailyWeather, WeatherContext

RAIN_SKIP_THRESHOLD_MM = 15.0      # mm forecast in next 48h → skip
HIGH_TEMP_THRESHOLD_C = 38.0       # °C → heat stress warning


def compute_forecast_impact(weather: WeatherContext) -> dict:
    """Assess forecast impact on irrigation decision.

    Returns a dict with:
    - rain_next_48h_mm: expected rainfall in next 2 forecast days
    - heat_stress_expected: bool
    - rain_skip_recommended: bool
    - notes: list[str]
    """
    notes: list[str] = []
    rain_next_48h = 0.0
    heat_stress = False

    if not weather.forecast:
        return {
            "rain_next_48h_mm": 0.0,
            "heat_stress_expected": False,
            "rain_skip_recommended": False,
            "notes": ["No forecast data available"],
        }

    for i, day in enumerate(weather.forecast[:2]):  # next 48h = first 2 forecast days
        rain = day.rainfall_mm or 0.0
        prob = day.rainfall_probability_pct or 100.0

        # Only count rain if probability > 30%
        if prob > 30:
            rain_next_48h += rain
            if rain > 5:
                notes.append(
                    f"Day {i+1} forecast: {rain:.0f}mm rain ({prob:.0f}% probability)"
                )

        if day.t_max is not None and day.t_max >= HIGH_TEMP_THRESHOLD_C:
            heat_stress = True
            notes.append(f"Day {i+1} heat stress: Tmax {day.t_max:.0f}°C expected")

    rain_skip = rain_next_48h >= RAIN_SKIP_THRESHOLD_MM

    return {
        "rain_next_48h_mm": round(rain_next_48h, 1),
        "heat_stress_expected": heat_stress,
        "rain_skip_recommended": rain_skip,
        "notes": notes,
    }
