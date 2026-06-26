import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ProbeReadingsInline } from "../ProbeReadingsInline";

vi.mock("@/hooks/useProbeReadings", () => ({
  useProbeReadings: () => ({
    data: {
      depths: [
        {
          depth_cm: 30,
          readings: [
            { timestamp: "2026-06-26T08:00:00Z", vwc: 0.24 },
            { timestamp: "2026-06-26T09:00:00Z", vwc: 0.23 },
          ],
        },
      ],
      events: [],
      reference_lines: { field_capacity: 0.3, wilting_point: 0.15 },
    },
    loading: false,
    error: null,
    refetch: vi.fn(),
  }),
}));

vi.mock("@/components/probes/ProbeChart", () => ({
  ProbeChart: () => <div data-testid="probe-chart" />,
}));

vi.mock("@/components/probes/ProbeSumChart", () => ({
  ProbeSumChart: () => <div data-testid="probe-sum-chart" />,
}));

vi.mock("@/components/probes/ReadingsControls", () => ({
  ReadingsControls: () => <div data-testid="readings-controls" />,
}));

vi.mock("@/lib/api", () => ({
  sectorsApi: { updateCropProfile: vi.fn() },
  probesApi: {
    interpret: vi.fn(),
    refreshWaterEvents: vi.fn(),
  },
  waterEventsApi: {
    confirm: vi.fn(),
    reject: vi.fn(),
  },
}));

describe("ProbeReadingsInline", () => {
  it("renders the probe diagnosis copy when expanded", () => {
    render(
      <ProbeReadingsInline
        probeId="probe-1"
        externalId="P-1"
        href="/probes/probe-1"
        sectorId="sector-1"
      />,
    );

    fireEvent.click(screen.getByText("P-1"));

    expect(screen.getByText("Diagnóstico da sonda")).toBeInTheDocument();
    expect(
      screen.getByText(
        "Analisa o perfil de humidade por profundidade, a tendência recente e a resposta a regas.",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText("Interpretação de padrões")).not.toBeInTheDocument();
  });
});
