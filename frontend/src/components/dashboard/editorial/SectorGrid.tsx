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

  const cropTabs = useMemo(() => {
    const seen = new Set<string>();
    const order: string[] = [];
    // Put crops with "irrigate" sectors first
    const irrigateCrops = new Set(sectors.filter((s) => s.action === "irrigate").map((s) => s.crop_type));
    for (const s of sectors) {
      const ct = s.crop_type ?? "other";
      if (!seen.has(ct)) { seen.add(ct); }
    }
    const sorted = [...seen].sort((a, b) => {
      const aUrgent = irrigateCrops.has(a) ? 0 : 1;
      const bUrgent = irrigateCrops.has(b) ? 0 : 1;
      return aUrgent - bUrgent;
    });
    return sorted;
  }, [sectors]);

  const initialTab = searchParams.get("crop") && cropTabs.includes(searchParams.get("crop")!)
    ? searchParams.get("crop")!
    : cropTabs[0] ?? null;
  const [activeTab, setActiveTab] = useState<string | null>(initialTab);
  const currentTab = activeTab && cropTabs.includes(activeTab) ? activeTab : cropTabs[0] ?? null;

  const tabSectors = useMemo(
    () => sortSectors(sectors.filter((s) => (s.crop_type ?? "other") === currentTab)),
    [sectors, currentTab],
  );

  function handleTabClick(ct: string) {
    setActiveTab(ct);
    const params = new URLSearchParams(searchParams.toString());
    params.set("crop", ct);
    router.replace(`?${params.toString()}`, { scroll: false });
  }

  if (sectors.length === 0) return null;

  return (
    <section className="px-4 pt-5 pb-6 sm:px-8 lg:px-11">
      {/* Tab bar */}
      {cropTabs.length > 0 && (
        <div className="flex items-baseline gap-7 mb-4 relative" role="tablist">
          {cropTabs.map((ct) => {
            const label = CROP_LABELS[ct] ?? ct;
            const count = sectors.filter((s) => s.crop_type === ct).length;
            const irrigate = sectors.filter((s) => s.crop_type === ct && s.action === "irrigate").length;
            const active = ct === currentTab;
            return (
              <button
                key={ct}
                role="tab"
                aria-selected={active}
                onClick={() => handleTabClick(ct)}
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
          <p className="ml-auto font-mono text-[11px] text-ink-3 tracking-[0.04em] absolute right-0 bottom-2">
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
