import { cn } from "@/lib/utils";
import { InputHTMLAttributes, forwardRef, useId } from "react";

interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  label?: string;
  error?: string;
  hint?: string;
}

export const Input = forwardRef<HTMLInputElement, InputProps>(
  ({ label, error, hint, className, id, ...props }, ref) => {
    const generatedId = useId();
    const inputId = id ?? label?.toLowerCase().replace(/\s+/g, "-") ?? generatedId;
    const descriptionId = hint || error ? `${inputId}-description` : undefined;

    return (
      <div className="space-y-1.5">
        {label && (
          <label htmlFor={inputId} className="block text-sm font-semibold text-slate-800">
            {label}
          </label>
        )}
        <input
          ref={ref}
          id={inputId}
          aria-describedby={descriptionId}
          aria-invalid={Boolean(error)}
          className={cn(
            "block w-full rounded-xl border border-slate-300 bg-white px-3.5 py-2.5 text-sm text-slate-900 shadow-sm",
            "placeholder:text-slate-400",
            "hover:border-slate-400 disabled:cursor-not-allowed disabled:bg-slate-50 disabled:text-slate-500",
            "focus:border-emerald-600 focus:ring-emerald-600",
            error && "border-red-400 focus:border-red-600 focus:ring-red-600",
            className,
          )}
          {...props}
        />
        {hint && !error && (
          <p id={descriptionId} className="text-xs leading-5 text-slate-500">
            {hint}
          </p>
        )}
        {error && (
          <p id={descriptionId} className="text-xs font-medium leading-5 text-red-700">
            {error}
          </p>
        )}
      </div>
    );
  },
);

Input.displayName = "Input";
