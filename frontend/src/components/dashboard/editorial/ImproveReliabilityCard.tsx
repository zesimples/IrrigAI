interface Props {
  onDefineSoil: () => void;
  onConfirmStage: () => void;
}

export function ImproveReliabilityCard({ onDefineSoil, onConfirmStage }: Props) {
  return (
    <div className="relative overflow-hidden bg-terra-bg border border-rule-soft rounded-lg p-[16px_18px]">
      <span className="absolute inset-y-0 left-0 w-[3px] bg-terra rounded-l" />
      <p className="font-mono text-[10px] tracking-[0.14em] uppercase text-terra mb-2">
        Melhorar fiabilidade
      </p>
      <p className="font-serif text-[14.5px] leading-[1.45] text-ink mb-3">
        Configure o tipo de solo e confirme a fase fenológica para passar a fiabilidade de{" "}
        <strong className="font-semibold">baixa</strong> para <strong className="font-semibold">alta</strong>.
      </p>
      <div className="flex gap-1.5 flex-wrap">
        <button
          onClick={onDefineSoil}
          className="bg-ink text-paper rounded-md py-[7px] px-3 text-[12px] font-medium hover:opacity-85 transition-opacity"
        >
          Definir solo
        </button>
        <button
          onClick={onConfirmStage}
          className="bg-transparent text-ink-2 border border-rule rounded-md py-[7px] px-3 text-[12px] hover:bg-paper-in transition-colors"
        >
          Confirmar fase
        </button>
      </div>
    </div>
  );
}
