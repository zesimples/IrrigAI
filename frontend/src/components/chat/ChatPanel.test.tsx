import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { ChatPanel } from "./ChatPanel";

// jsdom does not implement scrollIntoView
window.HTMLElement.prototype.scrollIntoView = vi.fn() as typeof window.HTMLElement.prototype.scrollIntoView;

vi.mock("@/lib/api", () => ({
  chatApi: { chat: vi.fn() },
  recommendationsApi: { override: vi.fn(), accept: vi.fn(), reject: vi.fn(), generateRecommendation: vi.fn() },
  calibrationApi: { run: vi.fn() },
}));

import { chatApi, calibrationApi } from "@/lib/api";

describe("ChatPanel", () => {
  beforeEach(() => { vi.clearAllMocks(); });

  it("sends history with the message", async () => {
    (chatApi.chat as any).mockResolvedValue({ reply: "olá!", proposed_action: null });
    render(<ChatPanel farmId="f1" onClose={() => {}} />);
    fireEvent.change(screen.getByPlaceholderText(/pergunta/i), { target: { value: "primeira" } });
    fireEvent.click(screen.getByLabelText("Enviar"));
    await waitFor(() => expect(chatApi.chat).toHaveBeenCalledWith("f1", "primeira", undefined, []));
  });

  it("renders a confirm card and dispatches on confirm", async () => {
    (chatApi.chat as any).mockResolvedValue({
      reply: "Proponho calibrar.",
      proposed_action: { type: "run_calibration", summary: "Correr a Calibração AI.", sector_id: "sec-9", params: {} },
    });
    (calibrationApi.run as any).mockResolvedValue({});
    render(<ChatPanel farmId="f1" sectorId="sec-9" onClose={() => {}} />);
    fireEvent.change(screen.getByPlaceholderText(/pergunta/i), { target: { value: "recalibrar" } });
    fireEvent.click(screen.getByLabelText("Enviar"));
    await screen.findByText("Correr a Calibração AI.");
    fireEvent.click(screen.getByText("Confirmar"));
    await waitFor(() => expect(calibrationApi.run).toHaveBeenCalledWith("sec-9"));
  });
});
