interface NumericStripProps {
  totalSectors: number;
  toIrrigate: number;
  noAction: number;
  forecastRain48h: number;
}

export function NumericStrip({ totalSectors, toIrrigate, noAction, forecastRain48h }: NumericStripProps) {
  const cells: { label: string; value: string | number; color?: string }[] = [
    { label: "Sectores no total", value: totalSectors },
    { label: "A regar hoje",       value: toIrrigate,  color: toIrrigate > 0 ? "text-terra" : "text-ink" },
    { label: "Sem rega necessária", value: noAction,    color: noAction > 0   ? "text-olive" : "text-ink" },
    { label: "Próxima reavaliação", value: "+48 h" },
    { label: "Água prevista",       value: `${forecastRain48h.toFixed(1)} mm` },
  ];

  return (
    <div className="overflow-x-auto border-t border-b border-rule-soft mt-5">
      <div className="flex min-w-[480px] sm:min-w-0">
      {cells.map((c, i) => (
        <div
          key={c.label}
          className={`flex-1 py-3.5 px-3 sm:px-4 ${i > 0 ? "border-l border-rule-soft" : ""}`}
        >
          <p className="font-mono text-[10px] tracking-[0.04em] uppercase text-ink-3 mb-1">{c.label}</p>
          <p className={`font-serif text-[22px] sm:text-[26px] font-medium leading-none tracking-[-0.01em] ${c.color ?? "text-ink"}`}>
            {c.value}
          </p>
        </div>
      ))}
      </div>
    </div>
  );
}
