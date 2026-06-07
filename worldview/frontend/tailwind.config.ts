import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./lib/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        // Command-center palette: dark cockpit + signal accents.
        cockpit: "#0a0e14",
        signal: "#38bdf8",
      },
    },
  },
  plugins: [],
};

export default config;
