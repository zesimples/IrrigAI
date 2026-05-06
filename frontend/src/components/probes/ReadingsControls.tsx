"use client";

import { Button } from "@/components/ui/button";

const PRESETS = [
  { label: "24h", hours: 24 },
  { label: "3d", hours: 72 },
  { label: "7d", hours: 168 },
  { label: "30d", hours: 720 },
] as const;

const INTERVALS = [
  { label: "Bruto", value: "" },
  { label: "1h", value: "1h" },
  { label: "6h", value: "6h" },
  { label: "12h", value: "12h" },
  { label: "1d", value: "1d" },
] as const;

interface ReadingsControlsProps {
  sinceHours: number;
  interval: string;
  view: "depths" | "sum";
  onSinceChange: (hours: number) => void;
  onIntervalChange: (interval: string) => void;
  onViewChange: (view: "depths" | "sum") => void;
}

export function ReadingsControls({
  sinceHours,
  interval,
  view,
  onSinceChange,
  onIntervalChange,
  onViewChange,
}: ReadingsControlsProps) {
  return (
    <div className="flex w-full flex-col gap-3 sm:w-auto">
      <div>
        <p className="mb-1 font-mono text-[10px] tracking-[0.1em] uppercase text-ink-3">Janela</p>
        <div className="flex flex-wrap gap-1">
          {PRESETS.map((p) => (
            <Button
              key={p.hours}
              size="sm"
              variant={sinceHours === p.hours ? "primary" : "secondary"}
              onClick={() => onSinceChange(p.hours)}
            >
              {p.label}
            </Button>
          ))}
        </div>
      </div>
      <div>
        <p className="mb-1 font-mono text-[10px] tracking-[0.1em] uppercase text-ink-3">Agregação</p>
        <div className="flex flex-wrap gap-1">
          <Button
            size="sm"
            variant={view === "depths" ? "primary" : "secondary"}
            onClick={() => onViewChange("depths")}
          >
            Profundidades
          </Button>
          <Button
            size="sm"
            variant={view === "sum" ? "primary" : "secondary"}
            onClick={() => onViewChange("sum")}
          >
            Soma
          </Button>
        </div>
      </div>
      <div>
        <p className="mb-1 font-mono text-[10px] tracking-[0.1em] uppercase text-ink-3">Resolução</p>
        <div className="flex flex-wrap gap-1">
          {INTERVALS.map((iv) => (
            <Button
              key={iv.value}
              size="sm"
              variant={interval === iv.value ? "primary" : "secondary"}
              onClick={() => onIntervalChange(iv.value)}
            >
              {iv.label}
            </Button>
          ))}
        </div>
      </div>
    </div>
  );
}
