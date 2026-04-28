export type Confidence = "alta" | "media" | "baixa" | "sem-sonda";

interface ConfidenceDotsProps {
  level: Confidence;
}

const LEVEL_N: Record<Confidence, number> = { alta: 3, media: 2, baixa: 1, "sem-sonda": 0 };
const LEVEL_COLOR: Record<Confidence, string> = {
  alta: "#6b8f4e",
  media: "#c9a34a",
  baixa: "#c9a34a",
  "sem-sonda": "#b5ab9d",
};

export function ConfidenceDots({ level }: ConfidenceDotsProps) {
  const n = LEVEL_N[level];
  const color = LEVEL_COLOR[level];
  return (
    <span className="inline-flex gap-[3px] items-center">
      {[1, 2, 3].map((i) => (
        <span
          key={i}
          className="h-[5px] w-[5px] rounded-full"
          style={{ backgroundColor: i <= n ? color : "#e3ddd2" }}
        />
      ))}
    </span>
  );
}

export function confidenceLabel(level: Confidence): string {
  return level === "alta" ? "alta" : level === "media" ? "média" : level === "baixa" ? "baixa" : "sem sonda";
}
