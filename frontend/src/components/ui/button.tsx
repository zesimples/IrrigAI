import { cn } from "@/lib/utils";
import { ButtonHTMLAttributes, forwardRef } from "react";

type Variant = "primary" | "secondary" | "ghost" | "brand" | "danger";
type Size = "sm" | "md" | "lg";

const variantClasses: Record<Variant, string> = {
  // Dark fill — for accept/confirm actions (matches design reference)
  primary:
    "bg-[#1a1a1a] text-white hover:opacity-85 active:opacity-75 border border-transparent",
  // Brand green — for generate/main CTA
  brand:
    "bg-irrigai-green text-white hover:opacity-90 active:opacity-80 border border-transparent",
  // Outlined — secondary actions
  secondary:
    "bg-transparent text-[#1a1a1a] border border-black/10 hover:bg-irrigai-surface active:bg-black/5",
  // Ghost — tertiary/inline actions
  ghost:
    "bg-transparent text-irrigai-text-muted border border-transparent hover:text-[#1a1a1a] hover:bg-irrigai-surface",
  // Danger — destructive actions
  danger:
    "bg-irrigai-red text-white hover:opacity-90 active:opacity-80 border border-transparent",
};

const sizeClasses: Record<Size, string> = {
  sm: "h-8 gap-1.5 px-3 text-[13px]",
  md: "h-9 gap-2 px-4 text-[13px]",
  lg: "h-10 gap-2 px-5 text-[14px]",
};

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  loading?: boolean;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  (
    {
      variant = "primary",
      size = "md",
      loading,
      className,
      children,
      disabled,
      type,
      ...props
    },
    ref
  ) => (
    <button
      ref={ref}
      type={type ?? "button"}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={cn(
        "inline-flex items-center justify-center rounded-lg font-medium",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-black/20 focus-visible:ring-offset-1",
        "disabled:cursor-not-allowed disabled:opacity-40",
        "transition-all duration-100",
        variantClasses[variant],
        sizeClasses[size],
        className
      )}
      {...props}
    >
      {loading && (
        <svg
          aria-hidden="true"
          className="h-3.5 w-3.5 animate-spin"
          viewBox="0 0 24 24"
          fill="none"
        >
          <circle
            className="opacity-25"
            cx="12"
            cy="12"
            r="10"
            stroke="currentColor"
            strokeWidth="4"
          />
          <path
            className="opacity-75"
            fill="currentColor"
            d="M4 12a8 8 0 018-8v8H4z"
          />
        </svg>
      )}
      {children}
    </button>
  )
);

Button.displayName = "Button";
