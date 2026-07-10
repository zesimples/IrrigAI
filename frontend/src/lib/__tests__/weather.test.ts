import { describe, expect, it } from "vitest";
import { resolvePlotWeather } from "../weather";
import type { WeatherToday } from "@/types";

const farmWeather: WeatherToday = {
  et0_mm: 5.0,
  temperature_max_c: 30,
  temperature_min_c: 15,
  rainfall_mm: 0,
  forecast_rain_next_48h_mm: 0,
  forecast_rain_probability: null,
  humidity_pct: 50,
  wind_speed_kmh: 10,
};

const plotWeather: WeatherToday = { ...farmWeather, et0_mm: 7.7, temperature_max_c: 34 };

describe("resolvePlotWeather", () => {
  it("returns the plot's own weather when the active plot has a station", () => {
    const r = resolvePlotWeather(farmWeather, { "plot-1": plotWeather }, "plot-1");
    expect(r.weather.et0_mm).toBe(7.7);
    expect(r.plotScoped).toBe(true);
  });

  it("falls back to farm weather when the active plot has no station (single-station farm)", () => {
    const r = resolvePlotWeather(farmWeather, {}, "plot-1");
    expect(r.weather.et0_mm).toBe(5.0);
    expect(r.plotScoped).toBe(false);
  });

  it("returns farm weather when no plot is active", () => {
    const r = resolvePlotWeather(farmWeather, { "plot-1": plotWeather }, null);
    expect(r.weather.et0_mm).toBe(5.0);
    expect(r.plotScoped).toBe(false);
  });

  it("handles an absent weather_by_plot map (older backend payload)", () => {
    const r = resolvePlotWeather(farmWeather, undefined, "plot-1");
    expect(r.weather.et0_mm).toBe(5.0);
    expect(r.plotScoped).toBe(false);
  });
});
