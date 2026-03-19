import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  async rewrites() {
    return [
      {
        source: ":path*",
        //destination: `${process.env.NEXT_PUBLIC_API_URL || ""}/:path*`,
        destination: "https://business-persona-ai-backend-564277634285.europe-west4.run.app/:path*",
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
