import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Static export: every page is prerendered to HTML at build time.
  // No server, no runtime data fetching, no API key anywhere in the deployment.
  output: "export",
  images: { unoptimized: true },
  trailingSlash: true,
};

export default nextConfig;
