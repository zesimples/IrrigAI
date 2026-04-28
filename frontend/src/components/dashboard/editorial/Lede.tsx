import type { SectorSummary, WeatherToday } from "@/types";
import { CROP_LABELS } from "@/lib/cropConfig";

interface LedeProps {
  farmName: string;
  region: string | null;
  sectors: SectorSummary[];
  weather: WeatherToday;
}

function buildHeadline(sectors: SectorSummary[]): { main: string; italic: string | null } {
  const irrigate = sectors.filter((s) => s.action === "irrigate");
  if (irrigate.length === 0) {
    return { main: "Hoje todos os sectores podem esperar.", italic: null };
  }

  const byCrop = new Map<string, number>();
  const safeCropSet = new Set<string>();
  for (const s of sectors) {
    const label = CROP_LABELS[s.crop_type] ?? s.crop_type;
    if (s.action === "irrigate") byCrop.set(label, (byCrop.get(label) ?? 0) + 1);
    else safeCropSet.add(label);
  }

  const nums = ["", "Um", "Dois", "Três", "Quatro", "Cinco", "Seis", "Sete", "Oito", "Nove", "Dez"];
  const toWord = (n: number) => (n >= 1 && n <= 10 ? nums[n] : String(n));
  const deCrop = (l: string): string => {
    const m: Record<string, string> = { Olival: "do olival", Amendoal: "do amendoal", Vinha: "da vinha", Milho: "do milho", Tomate: "do tomate" };
    return m[l] ?? `do ${l.toLowerCase()}`;
  };
  const artCrop = (l: string): string => {
    const m: Record<string, string> = { Olival: "o olival", Amendoal: "o amendoal", Vinha: "a vinha", Milho: "o milho", Tomate: "o tomate" };
    return m[l] ?? l.toLowerCase();
  };

  const total = irrigate.length;
  const sWord = (n: number) => (n === 1 ? "sector" : "sectores");
  const vWord = (n: number) => (n === 1 ? "precisa" : "precisam");

  if (byCrop.size === 1) {
    const [[crop, count]] = byCrop.entries();
    const main = `${toWord(count)} ${sWord(count)} ${deCrop(crop)} ${vWord(count)} de rega hoje;`;
    if (safeCropSet.size === 1) {
      const [safe] = safeCropSet;
      return { main, italic: `${artCrop(safe)} pode esperar.` };
    }
    if (safeCropSet.size > 1) return { main, italic: "os outros podem esperar." };
    return { main: main.replace(";", "."), italic: null };
  }

  const main = `${toWord(total)} ${sWord(total)} precisam de rega hoje;`;
  if (safeCropSet.size === 1) {
    const [safe] = safeCropSet;
    return { main, italic: `${artCrop(safe)} pode esperar.` };
  }
  if (safeCropSet.size > 1) return { main, italic: "os outros podem esperar." };
  return { main: main.replace(";", "."), italic: null };
}

function buildSubtext(sectors: SectorSummary[], weather: WeatherToday): string {
  const et0 = weather.et0_mm != null ? `ET₀ ${weather.et0_mm.toFixed(1)} mm` : null;
  const rain48 = weather.forecast_rain_next_48h_mm > 0
    ? `${weather.forecast_rain_next_48h_mm.toFixed(1)} mm previstos nas próximas 48h`
    : "sem chuva prevista nas próximas 48 horas";
  const cropGroups = new Map<string, number>();
  for (const s of sectors.filter((x) => x.action === "irrigate")) {
    const label = CROP_LABELS[s.crop_type] ?? s.crop_type;
    cropGroups.set(label, (cropGroups.get(label) ?? 0) + 1);
  }
  const urgentCrop = cropGroups.size > 0
    ? `O ${[...cropGroups.keys()].map((l) => l.toLowerCase()).join(" e ")} em ${sectors.find((s) => s.action === "irrigate")?.current_stage ? "fase activa" : "défice"} pede prioridade.`
    : "";
  return [et0 ? `A evapotranspiração mantém-se ${et0}` : null, rain48, urgentCrop].filter(Boolean).join(". ").replace(/\.\./g, ".");
}

export function Lede({ farmName, region, sectors, weather }: LedeProps) {
  const { main, italic } = buildHeadline(sectors);
  const subtext = buildSubtext(sectors, weather);

  const boletimRows: [string, string][] = [
    ["Máx / Mín", weather.temperature_max_c != null && weather.temperature_min_c != null
      ? `${Math.round(weather.temperature_max_c)}° / ${Math.round(weather.temperature_min_c)}°C`
      : "—"],
    ["ET₀", weather.et0_mm != null ? `${weather.et0_mm.toFixed(1)} mm` : "—"],
    ["Chuva hoje", weather.rainfall_mm != null ? `${weather.rainfall_mm.toFixed(1)} mm` : "0 mm"],
    ["Previsão 48h", `${weather.forecast_rain_next_48h_mm.toFixed(1)} mm`],
    ["Vento", weather.wind_speed_kmh != null ? `${Math.round(weather.wind_speed_kmh)} km/h` : "—"],
    ["Hum. rel.", weather.humidity_pct != null ? `${Math.round(weather.humidity_pct)}%` : "—"],
  ];

  return (
    <section className="border-b border-rule px-4 pt-5 pb-5 sm:px-8 lg:px-11">
      <div className="grid grid-cols-1 gap-8 lg:grid-cols-[1.5fr_1fr] lg:gap-12">
        {/* Main lede */}
        <div>
          <p className="font-mono text-[10px] tracking-[0.18em] uppercase text-terra mb-2.5">
            Recomendação do dia · {farmName}{region ? ` · ${region}` : ""}
          </p>
          <h1 className="font-serif text-[28px] sm:text-[36px] lg:text-[42px] font-normal leading-[1.05] tracking-[-0.02em] text-ink" style={{ textWrap: "balance" } as React.CSSProperties}>
            {main}{" "}
            {italic && (
              <em className="font-instrument not-italic text-terra">{italic}</em>
            )}
          </h1>
          {subtext && (
            <p className="mt-3 text-[14px] leading-[1.55] text-ink-2 max-w-[560px]" style={{ textWrap: "pretty" } as React.CSSProperties}>
              {subtext}
            </p>
          )}
        </div>

        {/* Boletim */}
        <aside className="bg-card border border-rule-soft rounded-md p-4">
          <p className="font-mono text-[10px] tracking-[0.16em] uppercase text-ink-3 mb-3">
            Boletim · hoje
          </p>
          <div className="grid grid-cols-2 gap-x-5 gap-y-3.5">
            {boletimRows.map(([label, value]) => (
              <div key={label}>
                <p className="font-mono text-[10px] tracking-[0.04em] uppercase text-ink-3 mb-1">{label}</p>
                <p className="font-serif text-[17px] font-medium text-ink leading-none">{value}</p>
              </div>
            ))}
          </div>
        </aside>
      </div>
    </section>
  );
}
