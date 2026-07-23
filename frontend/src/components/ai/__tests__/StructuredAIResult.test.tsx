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
});
