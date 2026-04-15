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
 * - Inner pages (crumbs.length > 1 or with href): shows slim nav with back link
 */
export function AppHeader({ crumbs, right, farmDate }: AppHeaderProps) {
  const isFarmHeader =
    crumbs && crumbs.length === 1 && !crumbs[0].href;

  if (isFarmHeader) {
    return (
      <header className="px-4 pt-5 pb-5 sm:px-6 border-b border-black/[0.07]">
        <div className="mx-auto max-w-3xl flex items-start justify-between gap-4">
          <div className="flex items-center gap-3">
            <Link href="/" className="shrink-0 hover:opacity-70 transition-opacity" aria-label="Explorações">
              <Logo size={28} />
            </Link>
            <div>
              <h1 className="font-display text-[20px] font-[500] leading-none tracking-[-0.02em] text-irrigai-text">
                {crumbs[0].label}
              </h1>
              {farmDate && (
                <p className="mt-1 text-[12px] text-irrigai-text-muted">{farmDate}</p>
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

  // Slim nav for inner pages
  const parent = crumbs?.find((c) => c.href);
  const current = crumbs?.[crumbs.length - 1];

  return (
    <header className="sticky top-0 z-20 border-b border-black/[0.07] bg-white/95 backdrop-blur-sm">
      <div className="mx-auto flex h-12 max-w-3xl items-center justify-between gap-3 px-4 sm:px-6">
        <div className="flex min-w-0 items-center gap-1">
          {parent?.href ? (
            <Link
              href={parent.href}
              className="flex items-center gap-0.5 text-[13px] text-irrigai-text-muted hover:text-irrigai-text transition-colors shrink-0"
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
          {current && !current.href && (
            <>
              <span className="mx-1.5 text-black/20">/</span>
              <span className="truncate text-[13px] font-medium text-irrigai-text max-w-[200px]">
                {current.label}
              </span>
            </>
          )}
        </div>
        {right && (
          <div className="flex shrink-0 items-center gap-2">{right}</div>
        )}
      </div>
    </header>
  );
}
