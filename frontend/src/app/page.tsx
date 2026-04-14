"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { farmsApi } from "@/lib/api";
import { Logo } from "@/components/ui/Logo";

export default function Home() {
  const router = useRouter();

  useEffect(() => {
    farmsApi
      .list()
      .then((farms) => {
        if (farms.length > 0) {
          router.replace(`/farms/${farms[0].id}`);
        } else {
          router.replace("/onboarding");
        }
      })
      .catch(() => {
        // Backend unreachable — stay on this page
      });
  }, [router]);

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
