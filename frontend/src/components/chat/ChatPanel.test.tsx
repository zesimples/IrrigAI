import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { ChatPanel } from "./ChatPanel";

// jsdom does not implement scrollIntoView
window.HTMLElement.prototype.scrollIntoView = vi.fn() as typeof window.HTMLElement.prototype.scrollIntoView;

vi.mock("@/lib/api", () => ({
  chatApi: { chat: vi.fn() },
  recommendationsApi: { override: vi.fn(), accept: vi.fn(), reject: vi.fn() },
  sectorsApi: { generateRecommendation: vi.fn() },
  calibrationApi: { run: vi.fn() },
}));

import { chatApi, calibrationApi, sectorsApi } from "@/lib/api";

describe("ChatPanel", () => {
  beforeEach(() => { vi.clearAllMocks(); });

  it("sends history with the message", async () => {
    (chatApi.chat as any).mockResolvedValue({ reply: "olá!", proposed_action: null });
    render(<ChatPanel farmId="f1" onClose={() => {}} />);
    expect(screen.queryByText(/Powered by GPT-4o/i)).not.toBeInTheDocument();
    fireEvent.change(screen.getByPlaceholderText(/pergunta/i), { target: { value: "primeira" } });
    fireEvent.click(screen.getByLabelText("Enviar"));
    await waitFor(() => expect(chatApi.chat).toHaveBeenCalledWith("f1", "primeira", undefined, []));
  });

  it("renders a confirm card and dispatches on confirm", async () => {
    (chatApi.chat as any).mockResolvedValue({
      reply: "Proponho calibrar.",
      proposed_action: { type: "run_calibration", summary: "Correr a calibração inteligente.", sector_id: "sec-9", params: {} },
    });
    (calibrationApi.run as any).mockResolvedValue({});
    render(<ChatPanel farmId="f1" sectorId="sec-9" onClose={() => {}} />);
    fireEvent.change(screen.getByPlaceholderText(/pergunta/i), { target: { value: "recalibrar" } });
    fireEvent.click(screen.getByLabelText("Enviar"));
    await screen.findByText("Correr a calibração inteligente.");
    fireEvent.click(screen.getByText("Confirmar"));
    await waitFor(() => expect(calibrationApi.run).toHaveBeenCalledWith("sec-9"));
  });

  it("dispatches regenerate_recommendation via sectorsApi", async () => {
    (chatApi.chat as any).mockResolvedValue({
      reply: "Vou gerar uma nova recomendação.",
      proposed_action: { type: "regenerate_recommendation", summary: "Gerar nova recomendação.", sector_id: "sec-9", params: {} },
    });
    (sectorsApi.generateRecommendation as any).mockResolvedValue({});
    render(<ChatPanel farmId="f1" sectorId="sec-9" onClose={() => {}} />);
    fireEvent.change(screen.getByPlaceholderText(/pergunta/i), { target: { value: "nova recomendação" } });
    fireEvent.click(screen.getByLabelText("Enviar"));
    await screen.findByText("Gerar nova recomendação.");
    fireEvent.click(screen.getByText("Confirmar"));
    await waitFor(() => expect(sectorsApi.generateRecommendation).toHaveBeenCalledWith("sec-9"));
  });
});
