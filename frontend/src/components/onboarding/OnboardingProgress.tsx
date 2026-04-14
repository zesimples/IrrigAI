import { cn } from "@/lib/utils";

export const ONBOARDING_STEPS = [
  { id: 1, label: "Herdade", description: "Dados da exploração" },
  { id: 2, label: "Talhão & Solo", description: "Tipo de solo e talhão" },
  { id: 3, label: "Sector & Cultura", description: "Cultura e fenologia" },
  { id: 4, label: "Rega", description: "Sistema de rega" },
] as const;

interface OnboardingProgressProps {
  currentStep: number;
}

export function OnboardingProgress({ currentStep }: OnboardingProgressProps) {
  const current = ONBOARDING_STEPS.find((step) => step.id === currentStep);

  return (
    <nav aria-label="Progresso de configuração" className="mb-8">
      <div className="mb-4 rounded-2xl border border-emerald-100 bg-white/90 px-4 py-3 shadow-sm sm:hidden">
        <p className="text-xs font-semibold uppercase tracking-[0.2em] text-emerald-700">
          Passo {currentStep} de {ONBOARDING_STEPS.length}
        </p>
        {current && (
          <>
            <p className="mt-1 text-sm font-semibold text-slate-900">{current.label}</p>
            <p className="text-xs text-slate-500">{current.description}</p>
          </>
        )}
      </div>

      <ol className="flex items-start gap-0">
        {ONBOARDING_STEPS.map((step, idx) => {
          const done = currentStep > step.id;
          const active = currentStep === step.id;
          return (
            <li key={step.id} className="flex flex-1 items-center">
              <div className="flex flex-col items-center">
                <div
                  aria-current={active ? "step" : undefined}
                  className={cn(
                    "flex h-10 w-10 items-center justify-center rounded-full border-2 text-sm font-semibold transition-colors",
                    done && "border-emerald-700 bg-emerald-700 text-white",
                    active && "border-emerald-700 bg-emerald-50 text-emerald-700 shadow-sm",
                    !done && !active && "border-slate-300 bg-white text-slate-400",
                  )}
                >
                  {done ? (
                    <svg className="h-5 w-5" viewBox="0 0 20 20" fill="currentColor">
                      <path
                        fillRule="evenodd"
                        d="M16.707 5.293a1 1 0 00-1.414 0L8 12.586 4.707 9.293a1 1 0 00-1.414 1.414l4 4a1 1 0 001.414 0l8-8a1 1 0 000-1.414z"
                        clipRule="evenodd"
                      />
                    </svg>
                  ) : (
                    step.id
                  )}
                </div>
                <span
                  className={cn(
                    "mt-2 hidden text-center text-xs font-medium sm:block",
                    active ? "text-emerald-800" : "text-slate-500",
                  )}
                >
                  {step.label}
                </span>
                <span className="hidden max-w-28 text-center text-[11px] text-slate-400 sm:block">
                  {step.description}
                </span>
              </div>
              {idx < ONBOARDING_STEPS.length - 1 && (
                <div
                  className={cn(
                    "mx-2 mt-5 flex-1 border-t-2 transition-colors",
                    done ? "border-emerald-600" : "border-slate-200",
                  )}
                />
              )}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
