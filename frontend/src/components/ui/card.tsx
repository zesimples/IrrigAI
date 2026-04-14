import { cn } from "@/lib/utils";

interface CardProps {
  className?: string;
  children: React.ReactNode;
}

export function Card({ className, children }: CardProps) {
  return (
    <div
      className={cn(
        "rounded-xl border border-black/[0.08] bg-white",
        className
      )}
    >
      {children}
    </div>
  );
}

export function CardHeader({ className, children }: CardProps) {
  return (
    <div className={cn("border-b border-black/[0.06] px-4 py-3.5", className)}>
      {children}
    </div>
  );
}

export function CardBody({ className, children }: CardProps) {
  return (
    <div className={cn("px-4 py-4", className)}>
      {children}
    </div>
  );
}

export function CardTitle({ className, children }: CardProps) {
  return (
    <h3 className={cn("text-[13px] font-medium text-irrigai-text", className)}>
      {children}
    </h3>
  );
}
