import { cn } from "@/lib/utils";
import { SelectHTMLAttributes, forwardRef, useId } from "react";

interface SelectProps extends SelectHTMLAttributes<HTMLSelectElement> {
  label?: string;
  error?: string;
  hint?: string;
  options: { value: string; label: string }[];
  placeholder?: string;
}

export const Select = forwardRef<HTMLSelectElement, SelectProps>(
  ({ label, error, hint, options, placeholder, className, id, ...props }, ref) => {
    const generatedId = useId();
    const selectId = id ?? label?.toLowerCase().replace(/\s+/g, "-") ?? generatedId;
    const descriptionId = hint || error ? `${selectId}-description` : undefined;

    return (
      <div className="space-y-1.5">
        {label && (
          <label htmlFor={selectId} className="block text-sm font-semibold text-slate-800">
            {label}
          </label>
        )}
        <select
          ref={ref}
          id={selectId}
          aria-describedby={descriptionId}
          aria-invalid={Boolean(error)}
          className={cn(
            "block w-full rounded-xl border border-slate-300 bg-white px-3.5 py-2.5 text-sm text-slate-900 shadow-sm",
            "hover:border-slate-400 disabled:cursor-not-allowed disabled:bg-slate-50 disabled:text-slate-500",
            "focus:border-emerald-600 focus:ring-emerald-600",
            error && "border-red-400 focus:border-red-600 focus:ring-red-600",
            className,
          )}
          {...props}
        >
          {placeholder && (
            <option value="" disabled>
              {placeholder}
            </option>
          )}
          {options.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
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

Select.displayName = "Select";
