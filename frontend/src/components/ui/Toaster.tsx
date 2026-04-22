"use client";

import * as Toast from "@radix-ui/react-toast";
import { useToast } from "@/hooks/useToast";

const VARIANT_STYLES = {
  success: "border-irrigai-green/30 bg-irrigai-green/5 text-irrigai-green",
  error: "border-irrigai-red/40 bg-irrigai-red/5 text-irrigai-red",
  info: "border-black/[0.08] bg-white text-irrigai-text",
};

export function Toaster() {
  const { toasts, dismiss } = useToast();

  return (
    <Toast.Provider swipeDirection="right">
      {toasts.map((t) => (
        <Toast.Root
          key={t.id}
          open={true}
          onOpenChange={(open) => { if (!open) dismiss(t.id); }}
          className={`flex items-start gap-3 rounded-xl border px-4 py-3 shadow-sm transition-all data-[state=open]:animate-fade-in-up data-[state=closed]:opacity-0 ${VARIANT_STYLES[t.variant]}`}
        >
          <div className="flex-1 min-w-0">
            <Toast.Title className="text-[13px] font-medium leading-snug">
              {t.title}
            </Toast.Title>
            {t.description && (
              <Toast.Description className="mt-0.5 text-[12px] opacity-80 leading-snug">
                {t.description}
              </Toast.Description>
            )}
          </div>
          <Toast.Close
            className="shrink-0 mt-0.5 text-[18px] leading-none opacity-50 hover:opacity-80"
            aria-label="Fechar"
          >
            ×
          </Toast.Close>
        </Toast.Root>
      ))}
      <Toast.Viewport className="fixed bottom-20 sm:bottom-6 right-4 z-50 flex flex-col gap-2 w-[min(360px,calc(100vw-2rem))] outline-none" />
    </Toast.Provider>
  );
}
