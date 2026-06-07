/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // deck.gl / luma.gl ship ESM; transpile for Next's bundler.
  transpilePackages: ["@deck.gl/core", "@deck.gl/layers", "@deck.gl/geo-layers", "@deck.gl/mapbox", "@deck.gl/react"],
};

export default nextConfig;
