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
      },
      borderColor: {
        DEFAULT: "rgba(0,0,0,0.08)",
      },
    },
  },
  plugins: [],
};

export default config;
