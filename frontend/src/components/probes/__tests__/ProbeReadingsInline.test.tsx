import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ProbeReadingsInline } from "../ProbeReadingsInline";

const baseData: {
  depths: { depth_cm: number; readings: { timestamp: string; vwc: number }[] }[];
  events: unknown[];
  reference_lines: { field_capacity: number; wilting_point: number };
  rootzone_swc: { timestamp: string; vwc: number }[];
  root_depth_cm: number | null;
} = {
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
  rootzone_swc: [
    { timestamp: "2026-06-26T08:00:00Z", vwc: 0.09 },
    { timestamp: "2026-06-26T09:00:00Z", vwc: 0.087 },
  ],
  root_depth_cm: 60,
};

let mockData: typeof baseData | null = baseData;

vi.mock("@/hooks/useProbeReadings", () => ({
  useProbeReadings: () => ({
    data: mockData,
    loading: false,
    error: null,
    refetch: vi.fn(),
  }),
}));

vi.mock("@/components/probes/ProbeChart", () => ({
  ProbeChart: (props: { rootzoneSwc?: unknown[] }) => (
    <div data-testid="probe-chart">
      {props.rootzoneSwc && props.rootzoneSwc.length > 0 && (
        <div data-testid="rootzone-line-stub">Zona radicular (média)</div>
      )}
    </div>
  ),
  formatRootDepthHint: (rootDepthCm?: number | null) =>
    rootDepthCm == null ? null : `Zona radicular: ${Math.round(rootDepthCm)} cm (valor usado pela recomendação)`,
}));

vi.mock("@/components/probes/ProbeSumChart", () => ({
  ProbeSumChart: () => <div data-testid="probe-sum-chart" />,
}));

vi.mock("@/components/probes/ReadingsControls", () => ({
  ReadingsControls: ({
    onViewChange,
  }: {
    onViewChange: (view: "depths" | "sum") => void;
  }) => (
    <div data-testid="readings-controls">
      <button onClick={() => onViewChange("depths")}>Profundidades</button>
      <button onClick={() => onViewChange("sum")}>Soma</button>
    </div>
  ),
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

  it("renders the rootzone line and hint in the depths view when rootzone_swc is present", () => {
    mockData = baseData;
    render(
      <ProbeReadingsInline
        probeId="probe-1"
        externalId="P-1"
        href="/probes/probe-1"
        sectorId="sector-1"
      />,
    );

    fireEvent.click(screen.getByText("P-1"));

    expect(screen.getByTestId("rootzone-line-stub")).toBeInTheDocument();
    expect(screen.getByText("Zona radicular (média)")).toBeInTheDocument();
    expect(
      screen.getByText("Zona radicular: 60 cm (valor usado pela recomendação)"),
    ).toBeInTheDocument();
  });

  it("does not render the rootzone hint when rootzone_swc is empty", () => {
    mockData = { ...baseData, rootzone_swc: [], root_depth_cm: null };
    render(
      <ProbeReadingsInline
        probeId="probe-1"
        externalId="P-1"
        href="/probes/probe-1"
        sectorId="sector-1"
      />,
    );

    fireEvent.click(screen.getByText("P-1"));

    expect(screen.queryByTestId("rootzone-line-stub")).not.toBeInTheDocument();
    expect(screen.queryByText(/Zona radicular:/)).not.toBeInTheDocument();
  });

  it("explains how weighted rootzone moisture corresponds to depletion", () => {
    mockData = baseData;
    render(
      <ProbeReadingsInline
        probeId="probe-1"
        externalId="P-1"
        href="/probes/probe-1"
        sectorId="sector-1"
      />,
    );

    fireEvent.click(screen.getByText("P-1"));
    fireEvent.click(screen.getByText("Soma"));

    expect(screen.getByTestId("probe-sum-chart")).toBeInTheDocument();
    expect(screen.queryByTestId("probe-chart")).not.toBeInTheDocument();
    expect(
      screen.getByText(
        "A depleção usa esta média ponderada da zona radicular (60 cm): 0% na CC e 100% no PMP. Água disponível = 100% − depleção.",
      ),
    ).toBeInTheDocument();
  });
});
