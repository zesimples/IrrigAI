import type { ReactNode } from "react";

interface Props {
  title: string;
  children: ReactNode;
  action?: ReactNode;
  className?: string;
}

export function SidebarCard({ title, children, action, className }: Props) {
  return (
    <div className={`bg-card border border-rule-soft rounded-lg p-[16px_18px] ${className ?? ""}`}>
      <div className="flex items-center justify-between mb-2.5">
        <p className="font-mono text-[10px] tracking-[0.14em] uppercase text-ink-3">{title}</p>
        {action}
      </div>
      {children}
    </div>
  );
}
