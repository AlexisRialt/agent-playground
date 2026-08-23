import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Standalone output is what the Dockerfile copies into the runtime image.
  output: "standalone",
};

export default nextConfig;
