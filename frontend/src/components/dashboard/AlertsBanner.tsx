import Link from "next/link";
import type { AlertCounts } from "@/types";

interface AlertsBannerProps {
  counts: AlertCounts;
  farmId: string;
}

export function AlertsBanner({ counts, farmId }: AlertsBannerProps) {
  const total = counts.critical + counts.warning + counts.info;
  if (total === 0) return null;

  const isCritical = counts.critical > 0;

  const accentColor = isCritical ? "border-l-irrigai-red" : "border-l-irrigai-amber";
  const textColor = isCritical ? "text-irrigai-red-dark" : "text-irrigai-amber-dark";

  const summary = [
    counts.critical && `${counts.critical} crítico${counts.critical !== 1 ? "s" : ""}`,
    counts.warning && `${counts.warning} aviso${counts.warning !== 1 ? "s" : ""}`,
    counts.info && `${counts.info} informação`,
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    <Link
      href={`/farms/${farmId}/alerts`}
      className={`flex items-center justify-between gap-3 border border-black/[0.08] border-l-[3px] ${accentColor} rounded-r-lg px-3.5 py-2.5 text-[12px] transition-colors hover:bg-irrigai-surface`}
    >
      <div className="flex items-center gap-2.5">
        <svg width="14" height="14" viewBox="0 0 14 14" fill="none" className="shrink-0">
          <path d="M7 1L1 12h12L7 1z" stroke="currentColor" strokeWidth="1.2" fill="none" className={textColor} />
          <line x1="7" y1="5" x2="7" y2="8" stroke="currentColor" strokeWidth="1.2" className={textColor} />
          <circle cx="7" cy="10" r="0.6" fill="currentColor" className={textColor} />
        </svg>
        <span className="text-irrigai-text">
          {total} alerta{total !== 1 ? "s" : ""} activo{total !== 1 ? "s" : ""}
        </span>
        <span className="text-irrigai-text-muted">{summary}</span>
      </div>
      <span className={`font-medium ${textColor} hover:underline whitespace-nowrap`}>
        Ver
      </span>
    </Link>
  );
}
