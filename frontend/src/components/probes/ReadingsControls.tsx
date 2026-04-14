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
  onSinceChange: (hours: number) => void;
  onIntervalChange: (interval: string) => void;
}

export function ReadingsControls({
  sinceHours,
  interval,
  onSinceChange,
  onIntervalChange,
}: ReadingsControlsProps) {
  return (
    <div className="flex w-full flex-col gap-3 sm:w-auto">
      <div>
        <p className="mb-1 text-xs font-medium uppercase tracking-wide text-slate-500">Janela</p>
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
        <p className="mb-1 text-xs font-medium uppercase tracking-wide text-slate-500">Agregação</p>
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
