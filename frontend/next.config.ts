import type { NextConfig } from "next";

const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8080";
const serverActionOrigins = (
	process.env.NEXT_SERVER_ACTION_ALLOWED_ORIGINS || "localhost:3000"
)
	.split(",")
	.map((origin) => origin.trim())
	.filter(Boolean);

const nextConfig: NextConfig = {
	output: "standalone",
	experimental: {
		serverActions: {
			allowedOrigins: serverActionOrigins,
		},
	},
	async rewrites() {
		return [
			{
				source: "/:path*",
				destination: `${apiUrl}/:path*`,
			},
		];
	},
	webpack(config) {
		config.module.rules.push({
			test: /\.(woff|woff2|eot|ttf|otf)$/i,
			type: "asset/resource",
			generator: {
				filename: "static/fonts/[hash][ext][query]",
			},
		});
		return config;
	},
};

export default nextConfig;
