import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  webpack(config) {
    config.module.rules.push({
      test: /\.(woff|woff2|ttf|eot)$/,
      type: "asset/resource",
    });
    return config;
  },
};

export default nextConfig;
