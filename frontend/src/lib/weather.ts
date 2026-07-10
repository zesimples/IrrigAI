import type { WeatherToday } from "@/types";

/**
 * Pick the weather to show for the active plot tab.
 *
 * Plots with their own station/forecast (Innoliva polos) appear in
 * `weatherByPlot`; anything else — single-station farms, no active tab, or an
 * older backend payload without the map — falls back to the farm-level weather.
 */
export function resolvePlotWeather(
  farmWeather: WeatherToday,
  weatherByPlot: Record<string, WeatherToday> | undefined,
  activePlotId: string | null,
): { weather: WeatherToday; plotScoped: boolean } {
  const plotWeather = activePlotId ? weatherByPlot?.[activePlotId] : undefined;
  return plotWeather
    ? { weather: plotWeather, plotScoped: true }
    : { weather: farmWeather, plotScoped: false };
}
