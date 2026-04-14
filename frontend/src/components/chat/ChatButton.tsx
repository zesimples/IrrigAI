"use client";

import { useState } from "react";
import { MessageCircle, X } from "lucide-react";
import { ChatPanel } from "./ChatPanel";

interface ChatButtonProps {
  farmId: string;
  sectorId?: string;
}

export function ChatButton({ farmId, sectorId }: ChatButtonProps) {
  const [open, setOpen] = useState(false);

  return (
    <>
      {open && (
        <ChatPanel farmId={farmId} sectorId={sectorId} onClose={() => setOpen(false)} />
      )}
      <button
        onClick={() => setOpen((o) => !o)}
        className="fixed bottom-4 right-4 z-50 flex h-14 w-14 items-center justify-center rounded-full bg-emerald-700 text-white shadow-lg transition-all duration-200 hover:bg-emerald-600 hover:shadow-xl sm:bottom-6 sm:right-6"
        aria-label={open ? "Fechar assistente" : "Abrir assistente"}
        aria-expanded={open}
      >
        {open ? <X className="h-5 w-5" /> : <MessageCircle className="h-5 w-5" />}
      </button>
    </>
  );
}
