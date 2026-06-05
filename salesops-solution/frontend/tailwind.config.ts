import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        zbrain: {
          DEFAULT: "#1A55F9",
          50: "#EEF3FF",
          100: "#D8E3FE",
          200: "#A8BFFB",
          400: "#5B85FA",
          500: "#1A55F9",
          600: "#1644CC",
          700: "#10359F",
          ink: "#131426",
          muted: "#5B6275",
          surface: "#F7F8FB",
          divider: "#E5E7EE",
          // Dark-mode tokens — graphite + slate, not pure black; keeps brand
          // blue legible without harsh contrast. Tuned for AAA on small text.
          dark: "#0B0E1A",          // page background (deepest)
          "dark-elev1": "#11152A",  // card surface / elevated
          "dark-elev2": "#1A1F38",  // hover / nested cards
          "dark-divider": "#262B45",// 1px borders between elevation steps
          "dark-ink": "#E7EAF6",    // primary text
          "dark-muted": "#94A0BD",  // secondary text
          // Brand accent slightly brightened for dark-mode contrast against #0B0E1A
          "dark-accent": "#5B85FA",
        },
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "ui-monospace", "SF Mono", "Menlo", "Consolas", "monospace"],
      },
      fontFeatureSettings: {
        nums: '"tnum", "cv01", "cv11", "ss01"',
      },
      boxShadow: {
        // Light-mode elevation system — restrained, more enterprise than playful
        soft: "0 1px 2px rgba(19,20,38,0.04), 0 4px 12px rgba(19,20,38,0.06)",
        "elev-1": "0 1px 2px rgba(19,20,38,0.05)",
        "elev-2": "0 1px 2px rgba(19,20,38,0.05), 0 4px 8px rgba(19,20,38,0.06)",
        "elev-3": "0 2px 4px rgba(19,20,38,0.06), 0 12px 24px rgba(19,20,38,0.08)",
        // Dark-mode shadows are mostly inset highlight to mark elevation,
        // since true outer shadows look muddy on dark backgrounds.
        "dark-elev-1": "0 1px 0 rgba(255,255,255,0.04) inset, 0 1px 2px rgba(0,0,0,0.4)",
        "dark-elev-2": "0 1px 0 rgba(255,255,255,0.05) inset, 0 4px 12px rgba(0,0,0,0.5)",
        "ring-focus": "0 0 0 3px rgba(26,85,249,0.20)",
      },
      ringColor: {
        zbrain: "#1A55F9",
      },
      animation: {
        "fade-in": "fadeIn 180ms ease-out",
        "slide-down": "slideDown 220ms cubic-bezier(0.2,0.8,0.2,1)",
      },
      keyframes: {
        fadeIn: {
          "0%": { opacity: "0", transform: "translateY(2px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        slideDown: {
          "0%": { opacity: "0", transform: "translateY(-4px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
      },
    },
  },
  plugins: [],
} satisfies Config;
