import type { NextConfig } from "next";

let backend = process.env.BACKEND_URL || "http://127.0.0.1:8000";
if (!backend.startsWith("http://") && !backend.startsWith("https://")) {
  backend = `http://${backend}`;
}
backend = backend.replace(/\/+$/, "");

const nextConfig: NextConfig = {
  output: "standalone",
  async rewrites() {
    return [
      { source: "/api/:path*", destination: `${backend}/api/:path*` },
    ];
  },
};

export default nextConfig;
