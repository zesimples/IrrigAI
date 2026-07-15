import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { PhenologicalTimeline } from "./PhenologicalTimeline";


describe("PhenologicalTimeline", () => {
  it("selects and highlights the engine stage key", () => {
    const onSelect = vi.fn();
    const stage = {
      key: "olive_flowering",
      name_pt: "Floração",
      name_en: "Flowering",
      start_doy: 90,
      end_doy: 130,
      kc: 0.65,
    };

    render(
      <PhenologicalTimeline
        stages={[stage]}
        currentStage="olive_flowering"
        onSelect={onSelect}
      />,
    );

    const stageButton = screen.getAllByRole("button", { name: /floração/i }).at(-1)!;
    expect(stageButton).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(stageButton);
    expect(onSelect).toHaveBeenCalledWith(stage);
  });
});
