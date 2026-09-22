import { describe, it, expect, vi, beforeEach } from "vitest";
import { act, render, screen, fireEvent, waitFor } from "@testing-library/react";
import { SectorAnalysis } from "../SectorAnalysis";

vi.mock("@/lib/api", () => ({
  AI_CACHE_PREFIX: "irrigai_ai_analysis:",
  getUserScope: vi.fn(() => "user-a"),
  chatApi: { explainSector: vi.fn(), analysisVersion: vi.fn() },
  fieldObservationsApi: { create: vi.fn() },
}));

vi.mock("@/lib/utils", () => ({ formatDecimal: (n: number) => String(n) }));

import { chatApi, getUserScope } from "@/lib/api";

// This jsdom build exposes a `localStorage` object with no methods, so the cache
// under test would silently no-op. Install a real in-memory Storage instead.
function installStorage() {
  const store = new Map<string, string>();
  Object.defineProperty(window, "localStorage", {
    configurable: true,
    value: {
      getItem: (key: string) => store.get(key) ?? null,
      setItem: (key: string, value: string) => void store.set(key, String(value)),
      removeItem: (key: string) => void store.delete(key),
      clear: () => store.clear(),
      key: (index: number) => [...store.keys()][index] ?? null,
      get length() {
        return store.size;
      },
    },
  });
}

const STORED = {
  text: "• Água no solo: 8 mm",
  structured: null,
  ts: Date.now() - 60_000,
  provenance: {
    recommendation_id: "rec-1",
    context_version: "ctx-1",
    contract_version: "a3.1",
  },
};

function cacheKey(user: string, sector: string) {
  return `irrigai_ai_analysis:${user}:${sector}`;
}

describe("SectorAnalysis freshness", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    installStorage();
    (getUserScope as unknown as ReturnType<typeof vi.fn>).mockReturnValue("user-a");
  });

  it("keeps a failed freshness check historical and rechecks on focus", async () => {
    localStorage.setItem(cacheKey("user-a", "sec-1"), JSON.stringify(STORED));
    vi.mocked(chatApi.analysisVersion).mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValue(STORED.provenance);
    render(<SectorAnalysis sectorId="sec-1" />);
    await screen.findByText(/Análise histórica/);
    await waitFor(() => expect(chatApi.analysisVersion).toHaveBeenCalledTimes(1));
    fireEvent(window, new Event("focus"));
    await waitFor(() => expect(screen.queryByText(/Análise histórica/)).not.toBeInTheDocument());
    expect(chatApi.analysisVersion).toHaveBeenCalledTimes(2);
  });

  it("ignores an analysis that completes after navigation to another sector", async () => {
    localStorage.setItem(cacheKey("user-a", "sec-1"), JSON.stringify(STORED));
    localStorage.setItem(cacheKey("user-a", "sec-2"), JSON.stringify({ ...STORED, text: "Análise do segundo setor" }));
    vi.mocked(chatApi.analysisVersion).mockResolvedValue({ ...STORED.provenance, context_version: "changed" });
    let complete!: (value: Awaited<ReturnType<typeof chatApi.explainSector>>) => void;
    vi.mocked(chatApi.explainSector).mockImplementation(() => new Promise((resolve) => { complete = resolve; }));
    const view = render(<SectorAnalysis sectorId="sec-1" />);
    fireEvent.click(await screen.findByText("Actualizar análise"));
    await waitFor(() => expect(chatApi.explainSector).toHaveBeenCalled());
    view.rerender(<SectorAnalysis sectorId="sec-2" />);
    await screen.findByText("Análise do segundo setor");
    await act(async () => complete({ explanation: "Resposta atrasada", structured: null, provenance: STORED.provenance }));
    expect(screen.queryByText("Resposta atrasada")).not.toBeInTheDocument();
    expect(JSON.parse(localStorage.getItem(cacheKey("user-a", "sec-1"))!).text).toBe(STORED.text);
  });

  it("shows a stored analysis as current while its inputs are unchanged", async () => {
    localStorage.setItem(cacheKey("user-a", "sec-1"), JSON.stringify(STORED));
    (chatApi.analysisVersion as ReturnType<typeof vi.fn>).mockResolvedValue({
      recommendation_id: "rec-1",
      context_version: "ctx-1",
      contract_version: "a3.1",
    });

    render(<SectorAnalysis sectorId="sec-1" />);

    await waitFor(() => expect(chatApi.analysisVersion).toHaveBeenCalledWith("sec-1"));
    expect(screen.queryByText(/Análise histórica/)).not.toBeInTheDocument();
  });

  it("marks a stored analysis historical when the recommendation moved on", async () => {
    localStorage.setItem(cacheKey("user-a", "sec-1"), JSON.stringify(STORED));
    (chatApi.analysisVersion as ReturnType<typeof vi.fn>).mockResolvedValue({
      recommendation_id: "rec-2",
      context_version: "ctx-2",
      contract_version: "a3.1",
    });

    render(<SectorAnalysis sectorId="sec-1" />);

    await screen.findByText(/Análise histórica/);
    expect(screen.getByText("Actualizar análise")).toBeInTheDocument();
  });

  it("marks it historical when only the prompt contract changed", async () => {
    localStorage.setItem(cacheKey("user-a", "sec-1"), JSON.stringify(STORED));
    (chatApi.analysisVersion as ReturnType<typeof vi.fn>).mockResolvedValue({
      recommendation_id: "rec-1",
      context_version: "ctx-1",
      contract_version: "a4.0",
    });

    render(<SectorAnalysis sectorId="sec-1" />);
    await screen.findByText(/Análise histórica/);
  });

  it("treats a pre-A3 entry with no provenance as historical", async () => {
    localStorage.setItem(
      cacheKey("user-a", "sec-1"),
      JSON.stringify({ text: "análise antiga", structured: null, ts: Date.now() }),
    );

    render(<SectorAnalysis sectorId="sec-1" />);

    await screen.findByText(/Análise histórica/);
    // No version fetch is needed: an entry with no provenance is never current.
    expect(chatApi.analysisVersion).not.toHaveBeenCalled();
  });

  it("does not read another user's cached analysis", async () => {
    localStorage.setItem(cacheKey("user-b", "sec-1"), JSON.stringify(STORED));

    render(<SectorAnalysis sectorId="sec-1" />);

    await waitFor(() =>
      expect(screen.queryByText("• Água no solo: 8 mm")).not.toBeInTheDocument(),
    );
  });

  it("refreshing replaces the analysis and clears the historical banner", async () => {
    localStorage.setItem(cacheKey("user-a", "sec-1"), JSON.stringify(STORED));
    (chatApi.analysisVersion as ReturnType<typeof vi.fn>).mockResolvedValue({
      recommendation_id: "rec-2",
      context_version: "ctx-2",
      contract_version: "a3.1",
    });
    (chatApi.explainSector as ReturnType<typeof vi.fn>).mockResolvedValue({
      explanation: "• Água no solo: 20 mm",
      structured: null,
      provenance: {
        recommendation_id: "rec-2",
        context_version: "ctx-2",
        contract_version: "a3.1",
      },
    });

    render(<SectorAnalysis sectorId="sec-1" />);
    fireEvent.click(await screen.findByText("Actualizar análise"));

    await screen.findByText("• Água no solo: 20 mm");
    expect(screen.queryByText(/Análise histórica/)).not.toBeInTheDocument();
    const stored = JSON.parse(localStorage.getItem(cacheKey("user-a", "sec-1")) ?? "{}");
    expect(stored.provenance.context_version).toBe("ctx-2");
  });
});
