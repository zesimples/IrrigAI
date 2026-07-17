import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/** Format a number for pt-PT display: comma decimal separator, no grouping */
export function formatDecimal(value: number, digits = 1): string {
  return value.toLocaleString("pt-PT", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
    useGrouping: false,
  });
}

/** Format a number as mm with 1 decimal place */
export function formatMm(value: number): string {
  return `${formatDecimal(value, 1)} mm`;
}

/** Format a confidence score (0–1) as a percentage */
export function formatConfidence(score: number): string {
  return `${Math.round(score * 100)}%`;
}

/** Format a date in DD/MM/YYYY (pt-PT convention) */
export function formatDate(date: Date | string): string {
  const d = typeof date === "string" ? new Date(date) : date;
  return d.toLocaleDateString("pt-PT", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
  });
}

/** Format a datetime in DD/MM/YYYY HH:mm */
export function formatDateTime(date: Date | string): string {
  const d = typeof date === "string" ? new Date(date) : date;
  return d.toLocaleString("pt-PT", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}
