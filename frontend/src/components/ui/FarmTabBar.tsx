"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

interface Tab {
  label: string;
  href: string;
}

interface FarmTabBarProps {
  farmId: string;
}

export function FarmTabBar({ farmId }: FarmTabBarProps) {
  const pathname = usePathname();

  const tabs: Tab[] = [
    { label: "Recomendações", href: `/farms/${farmId}` },
    { label: "Caudalímetros", href: `/farms/${farmId}/caudalimetros` },
  ];

  return (
    <div className="flex border-b-2 border-rule-soft px-4 sm:px-8 lg:px-11 bg-surface-subtle">
      {tabs.map((tab) => {
        const isActive =
          tab.href === `/farms/${farmId}`
            ? pathname === tab.href
            : pathname.startsWith(tab.href);
        return (
          <Link
            key={tab.href}
            href={tab.href}
            className={[
              "px-4 py-2.5 text-sm font-medium transition-colors",
              isActive
                ? "text-ink-1 border-b-2 border-ink-1 -mb-0.5"
                : "text-ink-3 hover:text-ink-2",
            ].join(" ")}
          >
            {tab.label}
          </Link>
        );
      })}
    </div>
  );
}
