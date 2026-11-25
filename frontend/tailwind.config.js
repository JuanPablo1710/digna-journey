/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    colors: {
      transparent: "transparent",
      current: "currentColor",
      "brand-yellow": "var(--brand-yellow)",
      "brand-green": "var(--brand-green)",
      "brand-gray": "var(--brand-gray)",
      ...Object.fromEntries([
        "page", "surface", "subtle", "ink", "muted", "line", "primary", "primary-strong", "primary-soft",
        "on-primary", "success", "success-soft", "warning", "warning-soft", "danger", "danger-soft",
        "danger-line", "info", "info-soft", "info-line",
      ].map((name) => [name, `var(--color-${name})`])),
    },
    fontFamily: { sans: ["var(--font-body)"] },
  },
  plugins: [],
};

