import { render, screen } from "@testing-library/react";

import { StructuredAIResult } from "../StructuredAIResult";


const interpretation = {
  summary: "O solo mantém reserva suficiente.",
  risk_level: "low" as const,
  irrigation_advice: "Não regar agora; voltar a verificar amanhã.",
  evidence: [
    {
      evidence_id: "ev_123456789abc",
      source: "water_balance.depletion_mm",
      label: "Depleção",
      value: "12,5 mm",
    },
  ],
  missing_data: ["Confirmar a uniformidade do sistema."],
  confidence_score: 0.82,
  confidence_explanation: "Sonda e meteorologia actuais.",
  recommended_actions: ["Monitorizar novamente amanhã."],
};


describe("StructuredAIResult", () => {
  it("renders structured fields and resolved evidence directly", () => {
    render(<StructuredAIResult interpretation={interpretation} />);

    expect(screen.getByText(interpretation.summary)).toBeInTheDocument();
    expect(screen.getByText(interpretation.irrigation_advice)).toBeInTheDocument();
    expect(screen.getByText("Depleção")).toBeInTheDocument();
    expect(screen.getByText("12,5 mm")).toBeInTheDocument();
    expect(screen.getByText("Monitorizar novamente amanhã.")).toBeInTheDocument();
    expect(screen.getByText("Confirmar a uniformidade do sistema.")).toBeInTheDocument();
  });

  it("does not expose internal evidence IDs or JSON paths", () => {
    render(<StructuredAIResult interpretation={interpretation} />);

    expect(screen.queryByText("ev_123456789abc")).not.toBeInTheDocument();
    expect(screen.queryByText("water_balance.depletion_mm")).not.toBeInTheDocument();
  });

  it("surfaces a degraded deterministic fallback honestly", () => {
    render(
      <StructuredAIResult
        interpretation={{ ...interpretation, degraded: true }}
      />,
    );

    expect(screen.getByRole("status")).toHaveTextContent(
      "síntese de contingência",
    );
  });

  it("hides generic/internal evidence and deduplicates user-facing labels", () => {
    render(
      <StructuredAIResult
        interpretation={{
          ...interpretation,
          evidence: [
            {
              evidence_id: "ev_id",
              source: "scope.sector.id",
              label: "Dados",
              value: "8de7fe5b-6fce-4ebc-95c4-a0ab2b055650",
            },
            {
              evidence_id: "ev_crop",
              source: "scope.sector.crop_type",
              label: "Cultura",
              value: "olive",
            },
            {
              evidence_id: "ev_stage",
              source: "scope.sector.current_phenological_stage",
              label: "Fase fenológica",
              value: "olive_flowering",
            },
            {
              evidence_id: "ev_depletion_1",
              source: "water_balance.depletion_mm",
              label: "Depleção",
              value: "29,04 mm",
            },
            {
              evidence_id: "ev_depletion_2",
              source: "recommendation_change.depletion_mm",
              label: "Depleção",
              value: "30 mm",
            },
          ],
        }}
      />,
    );

    expect(screen.queryByText("Dados")).not.toBeInTheDocument();
    expect(
      screen.queryByText("8de7fe5b-6fce-4ebc-95c4-a0ab2b055650"),
    ).not.toBeInTheDocument();
    expect(screen.getByText("Olival")).toBeInTheDocument();
    expect(screen.getByText("Floração")).toBeInTheDocument();
    expect(screen.getAllByText("Depleção")).toHaveLength(1);
    expect(screen.queryByText("30 mm")).not.toBeInTheDocument();
  });
});
