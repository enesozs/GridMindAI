import type { NextConfig } from "next";

// Static-first: the pipeline writes JSON into public/data and the site is exported as
// plain HTML/CSS/JS (no server). See docs/DECISIONS.md.
const nextConfig: NextConfig = {
  output: "export",
  trailingSlash: true,
  images: { unoptimized: true },
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
