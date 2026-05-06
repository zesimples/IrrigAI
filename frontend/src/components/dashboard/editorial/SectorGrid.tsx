"use client";

import { useMemo, useState } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import type { SectorSummary } from "@/types";
import { CROP_LABELS } from "@/lib/cropConfig";
import { EditorialSectorCard } from "./SectorCard";

interface SectorGridProps {
  sectors: SectorSummary[];
  farmId: string;
}

function sortSectors(list: SectorSummary[]): SectorSummary[] {
  return [...list].sort((a, b) => {
    const aRegar = a.action === "irrigate" ? 0 : 1;
    const bRegar = b.action === "irrigate" ? 0 : 1;
    if (aRegar !== bRegar) return aRegar - bRegar;
    // Within same verdict: sort by depletion descending (most depleted first)
    const aD = a.depletion_pct ?? 50;
    const bD = b.depletion_pct ?? 50;
    return bD - aD;
  });
}

export function SectorGrid({ sectors, farmId }: SectorGridProps) {
  const searchParams = useSearchParams();
  const router = useRouter();

  // If all sectors share one crop type, tab by plot instead of crop.
  const uniqueCrops = useMemo(() => new Set(sectors.map((s) => s.crop_type ?? "other")), [sectors]);
  const tabMode: "crop" | "plot" = uniqueCrops.size <= 1 && sectors.some((s) => s.plot_name) ? "plot" : "crop";

  const tabs = useMemo(() => {
    const irrigateKeys = new Set(
      sectors.filter((s) => s.action === "irrigate").map((s) =>
        tabMode === "plot" ? (s.plot_id || s.plot_name) : (s.crop_type ?? "other")
      )
    );
    const seen = new Map<string, string>(); // key → label
    for (const s of sectors) {
      const key = tabMode === "plot" ? (s.plot_id || s.plot_name) : (s.crop_type ?? "other");
      const label = tabMode === "plot" ? s.plot_name : (CROP_LABELS[s.crop_type] ?? s.crop_type);
      if (!seen.has(key)) seen.set(key, label);
    }
    return [...seen.entries()]
      .sort(([a], [b]) => {
        const aU = irrigateKeys.has(a) ? 0 : 1;
        const bU = irrigateKeys.has(b) ? 0 : 1;
        return aU - bU;
      })
      .map(([key, label]) => ({ key, label }));
  }, [sectors, tabMode]);

  const paramKey = tabMode === "plot" ? "plot" : "crop";
  const initialTab = (() => {
    const p = searchParams.get(paramKey);
    return p && tabs.some((t) => t.key === p) ? p : tabs[0]?.key ?? null;
  })();
  const [activeTab, setActiveTab] = useState<string | null>(initialTab);
  const currentTab = activeTab && tabs.some((t) => t.key === activeTab) ? activeTab : tabs[0]?.key ?? null;

  const tabSectors = useMemo(() => {
    const filtered = sectors.filter((s) => {
      const key = tabMode === "plot" ? (s.plot_id || s.plot_name) : (s.crop_type ?? "other");
      return key === currentTab;
    });
    return sortSectors(filtered);
  }, [sectors, currentTab, tabMode]);

  function handleTabClick(key: string) {
    setActiveTab(key);
    const params = new URLSearchParams(searchParams.toString());
    params.set(paramKey, key);
    router.replace(`?${params.toString()}`, { scroll: false });
  }

  if (sectors.length === 0) return null;

  return (
    <section className="px-4 pt-5 pb-6 sm:px-8 lg:px-11">
      {/* Tab bar */}
      {tabs.length > 0 && (
        <div className="flex items-baseline gap-7 mb-4 relative overflow-x-auto pb-[1px]" role="tablist">
          {tabs.map(({ key, label }) => {
            const tabSecs = sectors.filter((s) => {
              const k = tabMode === "plot" ? (s.plot_id || s.plot_name) : (s.crop_type ?? "other");
              return k === key;
            });
            const count = tabSecs.length;
            const irrigate = tabSecs.filter((s) => s.action === "irrigate").length;
            const active = key === currentTab;
            return (
              <button
                key={key}
                role="tab"
                aria-selected={active}
                onClick={() => handleTabClick(key)}
                className={`flex items-baseline gap-2 pb-1.5 border-b-2 font-serif tracking-[-0.01em] transition-colors ${
                  active
                    ? "border-terra text-ink text-[22px] font-semibold"
                    : "border-transparent text-ink-3 text-[20px] font-normal hover:text-ink-2"
                }`}
              >
                {label}
                <span className={`font-mono text-[11px] font-medium ${active ? "text-ink-2" : "text-ink-3"}`}>
                  {count} sector{count !== 1 ? "es" : ""} · {irrigate} a regar
                </span>
              </button>
            );
          })}
          <p className="ml-auto font-mono text-[11px] text-ink-3 tracking-[0.04em] absolute right-0 bottom-2 hidden sm:block">
            Ordenado por urgência ↓
          </p>
        </div>
      )}

      {/* Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 border-t border-l border-rule bg-card">
        {tabSectors.map((s) => (
          <EditorialSectorCard key={s.sector_id} sector={s} farmId={farmId} />
        ))}
      </div>
    </section>
  );
}
