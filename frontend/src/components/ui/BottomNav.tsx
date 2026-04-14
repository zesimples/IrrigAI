"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

interface BottomNavProps {
  farmId: string;
}

export function BottomNav({ farmId }: BottomNavProps) {
  const path = usePathname();

  const isHome = path === `/farms/${farmId}` || path === "/";
  const isAlerts = path.includes("/alerts");
  const isIrrigation = path.includes("/irrigation");

  return (
    <nav className="fixed bottom-0 inset-x-0 z-30 border-t border-black/[0.07] bg-white/95 backdrop-blur-sm sm:hidden">
      <div className="flex justify-around py-2.5 pb-safe">
        <NavItem
          href={`/farms/${farmId}`}
          label="Início"
          active={isHome}
          icon={
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
              <path d="M2 8l6-5.5L14 8v6H2V8z" stroke="currentColor" strokeWidth="1.2" fill="none" />
            </svg>
          }
        />
        <NavItem
          href={`/farms/${farmId}/alerts`}
          label="Alertas"
          active={isAlerts}
          icon={
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
              <path d="M8 1l7 12H1L8 1z" stroke="currentColor" strokeWidth="1.2" fill="none" />
              <line x1="8" y1="5.5" x2="8" y2="9" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
              <circle cx="8" cy="11" r="0.6" fill="currentColor" />
            </svg>
          }
        />
        <NavItem
          href={`/farms/${farmId}`}
          label="Sondas"
          active={false}
          icon={
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
              <path d="M8 14a5 5 0 0 0 5-5C13 5 8 1 8 1S3 5 3 9a5 5 0 0 0 5 5z"
                stroke="currentColor" strokeWidth="1.2" fill="none" />
              <line x1="6" y1="8.5" x2="10" y2="8.5" stroke="currentColor" strokeWidth="1" />
            </svg>
          }
        />
        <NavItem
          href={isIrrigation ? "#" : `${path}`}
          label="Definições"
          active={false}
          icon={
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
              <circle cx="8" cy="8" r="5.5" stroke="currentColor" strokeWidth="1.2" fill="none" />
              <circle cx="8" cy="8" r="2" stroke="currentColor" strokeWidth="1" fill="none" />
            </svg>
          }
        />
      </div>
    </nav>
  );
}

function NavItem({
  href,
  label,
  active,
  icon,
}: {
  href: string;
  label: string;
  active: boolean;
  icon: React.ReactNode;
}) {
  return (
    <Link
      href={href}
      className={`flex flex-col items-center gap-0.5 px-4 py-0.5 text-[10px] transition-colors ${
        active ? "text-irrigai-text" : "text-irrigai-text-hint hover:text-irrigai-text-muted"
      }`}
    >
      <span className="w-4 h-4">{icon}</span>
      {label}
    </Link>
  );
}
