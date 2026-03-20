import type { NextConfig } from "next";

/* eslint-disable @typescript-eslint/no-explicit-any */
const BACKEND_URL =
  (globalThis as any).process?.env?.BACKEND_URL ||
  "https://business-persona-ai-backend-z3c6kkmdua-ez.a.run.app";

const nextConfig: NextConfig = {
  output: "standalone",
  async rewrites() {
    return [
      {
        source: "/:path*",
        destination: `${BACKEND_URL}/:path*`,
      },
    ];
  },
  webpack(config) {
    config.module.rules.push({
      test: /\.(woff|woff2|ttf|eot)$/,
      type: "asset/resource",
    });
    return config;
  },

};

export default nextConfig;
