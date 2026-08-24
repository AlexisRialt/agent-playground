import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Standalone output is what the Dockerfile copies into the runtime image.
  output: "standalone",
  // The CLI checker's detached child process cannot return output in restricted
  // build environments. TypeScript 5 provides the compiler API fallback.
  experimental: {
    useTypeScriptCli: false,
    webpackBuildWorker: false,
  },
};

export default nextConfig;
