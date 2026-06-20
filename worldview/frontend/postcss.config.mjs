/** @type {import('postcss-load-config').Config} */
const config = {
  plugins: {
    // Tailwind v4 moved its PostCSS plugin to a dedicated package; it also handles
    // vendor prefixing internally, so autoprefixer is no longer needed here.
    "@tailwindcss/postcss": {},
  },
};

export default config;
