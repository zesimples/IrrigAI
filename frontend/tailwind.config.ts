import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: ["class"],
  content: [
    "./src/pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/components/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: ["var(--font-dm-sans)", "system-ui", "sans-serif"],
        display: ["var(--font-fraunces)", "Georgia", "serif"],
        serif: ["var(--font-fraunces)", "Georgia", "serif"],
        instrument: ["var(--font-instrument)", "Georgia", "serif"],
        mono: ["var(--font-jetbrains)", "ui-monospace", "monospace"],
      },
      colors: {
        irrigai: {
          green: "#639922",
          "green-bg": "#EAF3DE",
          "green-dark": "#27500A",
          amber: "#EF9F27",
          "amber-bg": "#FAEEDA",
          "amber-dark": "#633806",
          red: "#E24B4A",
          "red-bg": "#FCEBEB",
          "red-dark": "#791F1F",
          blue: "#85B7EB",
          "blue-bg": "#E6F1FB",
          "blue-dark": "#0C447C",
          teal: "#5DCAA5",
          purple: "#AFA9EC",
          gray: "#B4B2A9",
          "gray-bg": "#F5F4F0",
          text: "#1a1a1a",
          "text-muted": "#6b6b68",
          "text-hint": "#9b9b97",
          border: "rgba(0,0,0,0.08)",
          bg: "#ffffff",
          surface: "#F5F4F0",
        },
        // Editorial Alentejo palette
        paper: "#f5f0e6",
        "paper-in": "#ece5d5",
        card: "#fbf8f1",
        ink: "#2a2520",
        "ink-2": "#5a5048",
        "ink-3": "#8a7f74",
        rule: "#dcd3c2",
        "rule-soft": "#e8e0d0",
        terra: "#b84a2a",
        "terra-bg": "#fbf4ee",
        olive: "#6b8f4e",
        earth: "#7a5a3a",
        sky: "#d4e1d6",
        water: "#2a6f97",
      },
      borderColor: {
        DEFAULT: "rgba(0,0,0,0.08)",
      },
      keyframes: {
        "fade-up": {
          "0%": { opacity: "0", transform: "translateY(8px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
      },
      animation: {
        "fade-up": "fade-up 0.35s ease-out both",
      },
    },
  },
  plugins: [],
};

export default config;
