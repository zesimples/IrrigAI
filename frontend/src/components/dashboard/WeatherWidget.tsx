import type { WeatherToday } from "@/types";

interface WeatherWidgetProps {
  weather: WeatherToday;
}

function WeatherItem({
  icon,
  label,
  value,
  sub,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  sub?: string;
}) {
  return (
    <div className="flex items-center gap-2">
      <span className="text-irrigai-text-muted">{icon}</span>
      <div>
        <p className="text-[11px] text-irrigai-text-muted leading-none">{label}</p>
        <p className="mt-0.5 text-[13px] font-medium text-irrigai-text leading-none">
          {value}
          {sub && (
            <span className="ml-1 text-[11px] font-normal text-irrigai-text-hint">{sub}</span>
          )}
        </p>
      </div>
    </div>
  );
}

// Minimal inline SVG icons matching reference style
const SunIcon = () => (
  <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
    <circle cx="8" cy="8" r="3.5" fill="#EF9F27" />
    <g stroke="#EF9F27" strokeWidth="1.2" strokeLinecap="round">
      <line x1="8" y1="1" x2="8" y2="3" />
      <line x1="8" y1="13" x2="8" y2="15" />
      <line x1="1" y1="8" x2="3" y2="8" />
      <line x1="13" y1="8" x2="15" y2="8" />
      <line x1="3.1" y1="3.1" x2="4.5" y2="4.5" />
      <line x1="11.5" y1="11.5" x2="12.9" y2="12.9" />
      <line x1="12.9" y1="3.1" x2="11.5" y2="4.5" />
      <line x1="4.5" y1="11.5" x2="3.1" y2="12.9" />
    </g>
  </svg>
);

const DropIcon = () => (
  <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
    <path d="M8 14a5 5 0 0 0 5-5C13 5 8 1 8 1S3 5 3 9a5 5 0 0 0 5 5z" fill="#85B7EB" />
  </svg>
);

const CloudIcon = () => (
  <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
    <path d="M3 9a5 5 0 1 0 10 0c0-2-2-4-4-6L8 1.5 6 4C4 6 3 7.5 3 9z"
      stroke="#B4B2A9" strokeWidth="1.2" fill="none" />
  </svg>
);

const LeafIcon = () => (
  <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
    <path d="M3 13c2-5 6-7 10-9-2 4-4 8-10 9z" stroke="#639922" strokeWidth="1.2" fill="none" />
    <line x1="3" y1="13" x2="8" y2="8" stroke="#639922" strokeWidth="1" strokeLinecap="round" />
  </svg>
);

export function WeatherWidget({ weather }: WeatherWidgetProps) {
  const hasRain = weather.forecast_rain_next_48h_mm > 5;

  const tempValue =
    weather.temperature_max_c != null
      ? `${weather.temperature_max_c.toFixed(0)}° / ${weather.temperature_min_c?.toFixed(0) ?? "—"}°C`
      : "—";

  const et0Value =
    weather.et0_mm != null ? `${weather.et0_mm.toFixed(1)} mm` : "—";

  const rainValue =
    weather.rainfall_mm != null && weather.rainfall_mm > 0
      ? `${weather.rainfall_mm.toFixed(1)} mm`
      : "0 mm";

  const forecastValue = `${weather.forecast_rain_next_48h_mm.toFixed(1)} mm`;
  const probSub =
    weather.forecast_rain_probability != null
      ? `${
          weather.forecast_rain_probability <= 1
            ? (weather.forecast_rain_probability * 100).toFixed(0)
            : weather.forecast_rain_probability.toFixed(0)
        }%`
      : undefined;

  return (
    <div className="flex flex-wrap gap-x-5 gap-y-3 rounded-xl bg-irrigai-surface px-4 py-3">
      <WeatherItem icon={<SunIcon />} label="Máx/Mín" value={tempValue} />
      <WeatherItem icon={<LeafIcon />} label="ET₀ hoje" value={et0Value} />
      <WeatherItem icon={<DropIcon />} label="Chuva hoje" value={rainValue} />
      <WeatherItem
        icon={<CloudIcon />}
        label="Previsão 48h"
        value={hasRain ? `${forecastValue} ⚠` : forecastValue}
        sub={probSub}
      />
    </div>
  );
}
