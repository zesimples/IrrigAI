"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { farmsApi } from "@/lib/api";
import { Logo } from "@/components/ui/Logo";
import type { Farm } from "@/types";

export default function Home() {
  const router = useRouter();
  const [farms, setFarms] = useState<Farm[] | null>(null);

  useEffect(() => {
    farmsApi
      .list()
      .then((list) => {
        if (list.length === 1) {
          router.replace(`/farms/${list[0].id}`);
        } else if (list.length === 0) {
          router.replace("/onboarding");
        } else {
          setFarms(list);
        }
      })
      .catch(() => {
        // Backend unreachable — stay on this page
      });
  }, [router]);

  // Farm picker — shown when there are multiple farms
  if (farms) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center bg-white px-6">
        <div className="w-full max-w-sm space-y-6">
          <div className="flex flex-col items-center gap-3 text-center">
            <Logo size={40} />
            <p className="font-display text-[20px] font-[500] text-irrigai-text tracking-[-0.02em]">
              IrrigAI
            </p>
          </div>
          <div className="space-y-2">
            <p className="text-[12px] font-medium uppercase tracking-[0.06em] text-irrigai-text-hint px-1">
              Explorações
            </p>
            {farms.map((farm) => (
              <button
                key={farm.id}
                onClick={() => router.push(`/farms/${farm.id}`)}
                className="w-full rounded-xl bg-irrigai-surface px-4 py-3.5 text-left transition-colors hover:bg-black/[0.06] active:bg-black/[0.09]"
              >
                <p className="text-[15px] font-medium text-irrigai-text">{farm.name}</p>
                {farm.region && (
                  <p className="mt-0.5 text-[12px] text-irrigai-text-muted">{farm.region}</p>
                )}
              </button>
            ))}
          </div>
        </div>
      </div>
    );
  }

  // Loading state
  return (
    <div className="flex min-h-screen items-center justify-center bg-white">
      <div className="flex flex-col items-center gap-4 text-center">
        <Logo size={44} />
        <div className="space-y-1">
          <p className="font-display text-[16px] font-[500] text-irrigai-text tracking-[-0.01em]">
            IrrigAI
          </p>
          <p className="text-[12px] text-irrigai-text-muted">A carregar…</p>
        </div>
        <div className="mt-1 h-0.5 w-20 overflow-hidden rounded-full bg-irrigai-surface">
          <div className="h-0.5 animate-[loading_1.5s_ease-in-out_infinite] rounded-full bg-irrigai-green" />
        </div>
      </div>
    </div>
  );
}
