import { cn } from "@/lib/utils";

type Variant = "default" | "irrigate" | "skip" | "reduce" | "increase" | "defer"
             | "critical" | "warning" | "info" | "success" | "muted";

const variantClasses: Record<Variant, string> = {
  // Action badges (sector recommendation)
  irrigate:  "bg-irrigai-green-bg text-irrigai-green-dark",
  skip:      "bg-irrigai-gray-bg text-irrigai-text-muted",
  reduce:    "bg-irrigai-amber-bg text-irrigai-amber-dark",
  increase:  "bg-irrigai-amber-bg text-irrigai-amber-dark",
  defer:     "bg-irrigai-amber-bg text-irrigai-amber-dark",
  // Semantic
  critical:  "bg-irrigai-red-bg text-irrigai-red-dark",
  warning:   "bg-irrigai-amber-bg text-irrigai-amber-dark",
  info:      "bg-irrigai-blue-bg text-irrigai-blue-dark",
  success:   "bg-irrigai-green-bg text-irrigai-green-dark",
  muted:     "bg-irrigai-gray-bg text-irrigai-text-hint",
  default:   "bg-irrigai-gray-bg text-irrigai-text-muted",
};

interface BadgeProps {
  variant?: Variant;
  className?: string;
  children: React.ReactNode;
}

export function Badge({ variant = "default", className, children }: BadgeProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full px-2.5 py-[3px] text-[11px] font-medium whitespace-nowrap",
        variantClasses[variant],
        className,
      )}
    >
      {children}
    </span>
  );
}
