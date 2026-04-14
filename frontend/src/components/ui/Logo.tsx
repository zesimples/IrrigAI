interface LogoProps {
  size?: number;
  className?: string;
}

export function Logo({ size = 32, className }: LogoProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 32 32"
      fill="none"
      aria-label="IrrigAI"
      className={className}
    >
      <rect width="32" height="32" rx="9" fill="#166534" />
      <path
        d="M16 5c0 0-7.5 9.5-7.5 13.5a7.5 7.5 0 0015 0C23.5 14.5 16 5 16 5z"
        fill="white"
        opacity="0.95"
      />
      <path
        d="M12.5 19.5c1 2 2.5 3.2 3.5 3.2"
        stroke="#166534"
        strokeWidth="1.6"
        strokeLinecap="round"
      />
    </svg>
  );
}
