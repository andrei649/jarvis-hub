import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./lib/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      // Brand-unified tokens (docs/design/WORLDVIEW_UX_SPEC.md §1.1; brand source BRAND_BOOK.md §7).
      colors: {
        void: "#04070E",
        "void-2": "#070D18",
        surface: "rgba(9,16,28,.82)",
        "surface-2": "rgba(12,21,36,.92)",
        line: "rgba(139,196,240,.14)",
        "line-2": "rgba(139,196,240,.07)",
        signal: "#2BB8F0",
        "signal-light": "#8FE0FF",
        "signal-dim": "rgba(43,184,240,.4)",
        "signal-faint": "rgba(43,184,240,.09)",
        ink: "#EEF1F5",
        green: "#41F59B",
        amber: "#FFB23F",
        red: "#FF5A52",
        violet: "#A78BFA",
      },
      fontFamily: {
        sans: ['"Space Grotesk"', "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ['"JetBrains Mono"', "ui-monospace", "monospace"],
      },
    },
  },
  plugins: [],
};

export default config;
