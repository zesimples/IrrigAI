import Link from "next/link";
import { ChevronLeft } from "lucide-react";
import { Logo } from "./Logo";

interface Crumb {
  label: string;
  href?: string;
}

interface AppHeaderProps {
  crumbs?: Crumb[];
  right?: React.ReactNode;
  /** When true, renders the full farm-name header (dashboard style) */
  farmDate?: string;
}

/**
 * Two modes:
 * - Dashboard (crumbs.length === 1, no href): shows farm name in Fraunces + date
 * - Inner pages (crumbs.length > 1 or with href): shows slim nav with full breadcrumb trail
 */
export function AppHeader({ crumbs, right, farmDate }: AppHeaderProps) {
  const isFarmHeader =
    crumbs && crumbs.length === 1 && !crumbs[0].href;

  if (isFarmHeader) {
    return (
      <header className="px-4 pt-5 pb-5 sm:px-8 lg:px-11 border-b border-rule bg-paper">
        <div className="flex items-start justify-between gap-4">
          <div className="flex items-center gap-3">
            <Link href="/" className="shrink-0 hover:opacity-70 transition-opacity" aria-label="Explorações">
              <Logo size={28} />
            </Link>
            <div>
              <h1 className="font-serif text-[20px] font-medium leading-none tracking-[-0.02em] text-ink">
                {crumbs[0].label}
              </h1>
              {farmDate && (
                <p className="mt-1 font-mono text-[11px] text-ink-3">{farmDate}</p>
              )}
            </div>
          </div>
          {right && (
            <div className="flex shrink-0 items-center gap-2">{right}</div>
          )}
        </div>
      </header>
    );
  }

  // Slim nav — find the back destination (first crumb with href) then render
  // all remaining crumbs as a breadcrumb trail.
  const parentIdx = crumbs ? crumbs.findIndex((c) => c.href) : -1;
  const parent = parentIdx >= 0 ? crumbs![parentIdx] : null;
  const trail = crumbs ? crumbs.slice(parentIdx + 1) : [];

  return (
    <header className="sticky top-0 z-20 border-b border-rule bg-paper/95 backdrop-blur-sm">
      <div className="mx-auto flex h-12 max-w-[1280px] items-center justify-between gap-3 px-4 sm:px-8 lg:px-11">
        <div className="flex min-w-0 items-center gap-1">
          {parent?.href ? (
            <Link
              href={parent.href}
              className="flex items-center gap-0.5 font-mono text-[12px] text-ink-3 hover:text-ink transition-colors shrink-0"
              aria-label={`Voltar para ${parent.label}`}
            >
              <ChevronLeft className="h-4 w-4" />
              <span className="hidden sm:inline">{parent.label}</span>
            </Link>
          ) : (
            <Link
              href="/"
              className="shrink-0 hover:opacity-70 transition-opacity"
              aria-label="Início"
            >
              <Logo size={24} />
            </Link>
          )}
          {trail.map((crumb, i) => {
            const isLast = i === trail.length - 1;
            return (
              <span key={i} className="flex items-center gap-1 min-w-0">
                <span className="mx-0.5 font-mono text-[11px] text-ink-3/50">/</span>
                {crumb.href ? (
                  <Link
                    href={crumb.href}
                    className="font-mono text-[12px] text-ink-3 hover:text-ink transition-colors shrink-0"
                  >
                    {crumb.label}
                  </Link>
                ) : isLast ? (
                  <span className="truncate font-mono text-[12px] font-medium text-ink max-w-[200px]">
                    {crumb.label}
                  </span>
                ) : (
                  <span className="font-mono text-[12px] text-ink-3 shrink-0">
                    {crumb.label}
                  </span>
                )}
              </span>
            );
          })}
        </div>
        {right && (
          <div className="flex shrink-0 items-center gap-2">{right}</div>
        )}
      </div>
    </header>
  );
}
